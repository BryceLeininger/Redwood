"""Microsoft Graph client utilities for Outlook mailbox operations."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import msal
import requests

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = [
    "User.Read",
    "Mail.ReadWrite",
    "Mail.Send",
    "Calendars.ReadWrite",
    "offline_access",
]


@dataclass(frozen=True)
class GraphAuthConfig:
    tenant_id: str
    client_id: str
    scopes: List[str]
    token_cache_path: Path

    @classmethod
    def from_env(cls) -> "GraphAuthConfig":
        tenant_id = os.getenv("MS_TENANT_ID", "").strip()
        client_id = os.getenv("MS_CLIENT_ID", "").strip()
        scopes_raw = os.getenv("MS_GRAPH_SCOPES", "").strip()
        cache_path_raw = os.getenv("MS_TOKEN_CACHE_PATH", "").strip()

        if not tenant_id:
            raise ValueError("MS_TENANT_ID is not set.")
        if not client_id:
            raise ValueError("MS_CLIENT_ID is not set.")

        scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()] or list(DEFAULT_SCOPES)
        if cache_path_raw:
            token_cache_path = Path(cache_path_raw)
        else:
            token_cache_path = Path(".graph_token_cache.bin")

        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            scopes=scopes,
            token_cache_path=token_cache_path,
        )


class MicrosoftGraphClient:
    """Small wrapper around Microsoft Graph for mailbox and calendar automation."""

    def __init__(self, config: GraphAuthConfig) -> None:
        self.config = config
        self._token_cache = msal.SerializableTokenCache()
        self._app = msal.PublicClientApplication(
            client_id=self.config.client_id,
            authority=f"https://login.microsoftonline.com/{self.config.tenant_id}",
            token_cache=self._token_cache,
        )
        self._load_cache()

    def _load_cache(self) -> None:
        cache_path = self.config.token_cache_path
        if cache_path.exists():
            self._token_cache.deserialize(cache_path.read_text(encoding="utf-8"))

    def _persist_cache(self) -> None:
        if not self._token_cache.has_state_changed:
            return
        cache_path = self.config.token_cache_path
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(self._token_cache.serialize(), encoding="utf-8")

    def _get_access_token(self) -> str:
        accounts = self._app.get_accounts()
        result: Optional[Dict[str, Any]] = None

        if accounts:
            result = self._app.acquire_token_silent(self.config.scopes, account=accounts[0])

        if not result or "access_token" not in result:
            flow = self._app.initiate_device_flow(scopes=self.config.scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Unable to start device login flow: {json.dumps(flow, indent=2)}")
            print(flow["message"])
            result = self._app.acquire_token_by_device_flow(flow)

        if not result or "access_token" not in result:
            details = result.get("error_description") if isinstance(result, dict) else str(result)
            raise RuntimeError(f"Microsoft Graph authentication failed: {details}")

        self._persist_cache()
        return str(result["access_token"])

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        token = self._get_access_token()
        url = f"{GRAPH_BASE_URL}{path}"
        request_headers = {"Authorization": f"Bearer {token}"}
        if headers:
            request_headers.update(headers)

        response = requests.request(
            method=method,
            url=url,
            params=params,
            json=json_payload,
            headers=request_headers,
            timeout=30,
        )

        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": {"message": response.text}}
            message = payload.get("error", {}).get("message", response.text)
            raise RuntimeError(f"Graph API request failed ({response.status_code}): {message}")

        if response.text:
            try:
                return response.json()
            except ValueError:
                return {}
        return {}

    def get_inbox_messages(self, *, top: int = 10, unread_only: bool = False) -> List[Dict[str, Any]]:
        top = max(1, min(top, 100))
        params: Dict[str, Any] = {
            "$top": top,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,webLink",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        payload = self._request("GET", "/me/messages", params=params)
        return payload.get("value", [])

    def get_message(self, message_id: str) -> Dict[str, Any]:
        message_id = message_id.strip()
        if not message_id:
            raise ValueError("message_id cannot be empty.")

        return self._request(
            "GET",
            f"/me/messages/{message_id}",
            params={"$select": "id,subject,from,receivedDateTime,isRead,bodyPreview,webLink"},
        )

    def create_reply_draft(self, message_id: str, body_text: str) -> Dict[str, Any]:
        message_id = message_id.strip()
        body_text = body_text.strip()
        if not message_id:
            raise ValueError("message_id cannot be empty.")
        if not body_text:
            raise ValueError("body_text cannot be empty.")

        draft = self._request("POST", f"/me/messages/{message_id}/createReply")
        draft_id = draft.get("id")
        if not draft_id:
            raise RuntimeError("Graph did not return draft id from createReply.")

        updated = self._request(
            "PATCH",
            f"/me/messages/{draft_id}",
            json_payload={
                "body": {
                    "contentType": "Text",
                    "content": body_text,
                }
            },
        )
        return {
            "draft_id": draft_id,
            "subject": updated.get("subject", draft.get("subject")),
            "web_link": updated.get("webLink", draft.get("webLink")),
        }

    def create_calendar_event(
        self,
        *,
        subject: str,
        start_datetime: str,
        end_datetime: str,
        timezone: str = "Pacific Standard Time",
        attendees: Optional[List[str]] = None,
        body_text: str = "",
    ) -> Dict[str, Any]:
        subject = subject.strip()
        start_datetime = start_datetime.strip()
        end_datetime = end_datetime.strip()
        timezone = timezone.strip() or "Pacific Standard Time"
        if not subject:
            raise ValueError("subject cannot be empty.")
        if not start_datetime:
            raise ValueError("start_datetime cannot be empty.")
        if not end_datetime:
            raise ValueError("end_datetime cannot be empty.")

        attendee_list = attendees or []
        payload = {
            "subject": subject,
            "body": {"contentType": "Text", "content": body_text},
            "start": {"dateTime": start_datetime, "timeZone": timezone},
            "end": {"dateTime": end_datetime, "timeZone": timezone},
            "attendees": [
                {"emailAddress": {"address": email, "name": email}, "type": "required"}
                for email in attendee_list
            ],
        }
        event = self._request("POST", "/me/events", json_payload=payload)
        return {
            "event_id": event.get("id"),
            "subject": event.get("subject"),
            "start": event.get("start", {}),
            "end": event.get("end", {}),
            "web_link": event.get("webLink"),
        }
