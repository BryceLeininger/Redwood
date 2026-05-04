"""Microsoft Graph client for OES using delegated device-code authentication."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from msal import PublicClientApplication, SerializableTokenCache

from .config import OESConfig

GRAPH_API_ROOT = "https://graph.microsoft.com/v1.0"


class GraphConfigurationError(RuntimeError):
    """Raised when Graph credentials are missing."""


@dataclass(slots=True)
class GraphAuthResult:
    account_username: str | None
    token_source: str
    scopes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_username": self.account_username,
            "token_source": self.token_source,
            "scopes": self.scopes,
        }


class MicrosoftGraphClient:
    def __init__(self, config: OESConfig) -> None:
        if not config.graph_client_id:
            raise GraphConfigurationError("OES_GRAPH_CLIENT_ID is required for Microsoft Graph access.")

        self.config = config
        self._token_cache = SerializableTokenCache()
        self._load_cache(config.token_cache_path)
        self._app = PublicClientApplication(
            client_id=config.graph_client_id,
            authority=f"https://login.microsoftonline.com/{config.graph_tenant_id}",
            token_cache=self._token_cache,
        )
        self._http = httpx.Client(timeout=30.0)

    def close(self) -> None:
        self._http.close()

    def authenticate(self, interactive: bool = True) -> GraphAuthResult:
        token_result, token_source = self._acquire_token_result(interactive=interactive)
        account = (token_result.get("id_token_claims") or {}).get("preferred_username")
        return GraphAuthResult(
            account_username=account,
            token_source=token_source,
            scopes=list(self.config.graph_scopes),
        )

    def _acquire_token_result(self, interactive: bool) -> tuple[dict[str, Any], str]:
        accounts = self._app.get_accounts()
        token_result: dict[str, Any] | None = None
        token_source = "cache"

        if accounts:
            token_result = self._app.acquire_token_silent(list(self.config.graph_scopes), account=accounts[0])

        if not token_result and interactive:
            flow = self._app.initiate_device_flow(scopes=list(self.config.graph_scopes))
            if "user_code" not in flow:
                raise RuntimeError(f"Could not create device flow: {json.dumps(flow, indent=2)}")
            print(flow.get("message", "Complete device authentication in your browser."))
            token_result = self._app.acquire_token_by_device_flow(flow)
            token_source = "device_code"

        if not token_result or "access_token" not in token_result:
            error_payload = token_result or {"error": "no_token", "error_description": "No access token returned."}
            raise RuntimeError(f"Microsoft Graph authentication failed: {json.dumps(error_payload, indent=2)}")

        self._save_cache(self.config.token_cache_path)
        return token_result, token_source

    def list_inbox_messages(self, limit: int = 25) -> list[dict[str, Any]]:
        params = {
            "$top": str(limit),
            "$orderby": "receivedDateTime DESC",
            "$select": (
                "id,subject,receivedDateTime,bodyPreview,isRead,categories,importance,"
                "from,internetMessageId,webLink"
            ),
        }
        response = self._request("GET", "/me/mailFolders/inbox/messages", params=params)
        return list(response.get("value", []))

    def list_sent_messages(self, limit: int = 200) -> list[dict[str, Any]]:
        params = {
            "$top": str(limit),
            "$orderby": "sentDateTime DESC",
            "$select": "id,subject,sentDateTime,bodyPreview,toRecipients",
        }
        response = self._request("GET", "/me/mailFolders/sentitems/messages", params=params)
        return list(response.get("value", []))

    def list_calendar_events(self, days: int = 14, limit: int = 25) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days)
        params = {
            "startDateTime": start.isoformat(),
            "endDateTime": end.isoformat(),
            "$top": str(limit),
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,organizer,location,attendees,webLink",
        }
        response = self._request("GET", "/me/calendarView", params=params)
        return list(response.get("value", []))

    def create_reply_draft(self, message_id: str, comment: str = "") -> dict[str, Any]:
        return self._request(
            "POST",
            f"/me/messages/{message_id}/createReply",
            json_body={"comment": comment},
        )

    def add_attachment_to_message(
        self,
        message_id: str,
        file_name: str,
        content: bytes,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": file_name,
            "contentType": content_type or "application/octet-stream",
            "contentBytes": base64.b64encode(content).decode("ascii"),
        }
        return self._request("POST", f"/me/messages/{message_id}/attachments", json_body=payload)

    def send_message(self, message_id: str) -> None:
        self._request("POST", f"/me/messages/{message_id}/send", json_body={})

    def delete_message(self, message_id: str) -> None:
        self._request("DELETE", f"/me/messages/{message_id}")

    def create_task(self, title: str, due_at: str | None = None, body: str = "") -> dict[str, Any]:
        list_id = self._default_task_list_id()
        payload: dict[str, Any] = {"title": title}
        if body:
            payload["body"] = {"content": body, "contentType": "text"}
        if due_at:
            payload["dueDateTime"] = {"dateTime": due_at, "timeZone": "UTC"}
        return self._request("POST", f"/me/todo/lists/{list_id}/tasks", json_body=payload)

    def _default_task_list_id(self) -> str:
        response = self._request("GET", "/me/todo/lists", params={"$top": "50"})
        lists = list(response.get("value", []))
        if not lists:
            raise RuntimeError("No Microsoft To Do lists were returned by Graph.")
        preferred = next((item for item in lists if item.get("displayName", "").lower() == "tasks"), None)
        target = preferred or lists[0]
        return str(target["id"])

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token_result, _ = self._acquire_token_result(interactive=True)
        access_token = token_result.get("access_token")
        if not access_token:
            raise RuntimeError("No Graph access token is available after authentication.")
        response = self._http.request(
            method=method,
            url=f"{GRAPH_API_ROOT}{path}",
            params=params,
            json=json_body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Graph request failed ({response.status_code}): {response.text or '<no response body>'}"
            )
        if response.content:
            return dict(response.json())
        return {}

    def _load_cache(self, cache_path: Path) -> None:
        if cache_path.exists():
            self._token_cache.deserialize(cache_path.read_text(encoding="utf-8"))

    def _save_cache(self, cache_path: Path) -> None:
        if self._token_cache.has_state_changed:
            cache_path.write_text(self._token_cache.serialize(), encoding="utf-8")