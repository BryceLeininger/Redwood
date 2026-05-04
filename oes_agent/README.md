# Outlook Email Secretary

`oes_agent` is a standalone Outlook Email Secretary for this repo. It is designed to run without laptop admin rights, keep a local approval queue, and avoid sending or deleting mail unless you explicitly approve the action.

## Current Capabilities

- Sync Outlook inbox messages through Microsoft Graph
- Sync Outlook inbox and calendar directly from the local Outlook desktop client on Windows, without an app registration
- Sync upcoming calendar events
- Triage email with heuristic logic and optional OpenAI assistance
- Generate draft-reply approvals instead of sending automatically
- Turn email action items into reminders
- Queue Microsoft To Do task creation behind approval
- Serve a mobile-friendly local dashboard for laptop or phone browser access

## Safety Model

- Reading inbox and calendar can be autonomous once authenticated
- Draft generation is autonomous, but creating the draft in Outlook still goes through approval
- Sending mail, deleting mail, and task creation require explicit approval
- The dashboard stores local state in `data/output/oes_agent`

## Install

From the repo root:

```powershell
python -m pip install -r oes_agent/requirements.txt
```

If you want live Graph access, copy the example env file and fill it in:

```powershell
Copy-Item oes_agent/.env.example .env
```

If you do not have an app registration, OES can still run against the Outlook desktop client installed on this laptop. This requires:

- Windows
- Outlook desktop already installed and signed in
- `pywin32` available in the virtual environment

That local-outlook mode is what OES will use automatically for `sync --live` when `OES_GRAPH_CLIENT_ID` is not set.

## Required Microsoft Graph Setup

You need an Entra app registration that supports delegated permissions. The app should have these Microsoft Graph delegated scopes:

- `User.Read`
- `Mail.Read`
- `Mail.ReadWrite`
- `Mail.Send`
- `Calendars.ReadWrite`
- `Tasks.ReadWrite`
- `offline_access`

Set the client ID in `.env`:

```env
OES_GRAPH_CLIENT_ID=your-app-client-id
OES_GRAPH_TENANT_ID=common
```

If your Microsoft 365 tenant blocks self-service app registrations, you will need the app registration created for you by your Microsoft 365 administrator. Laptop admin rights are not required.

If you are able to create an app registration yourself, make it a public client application for OES:

1. Open the Microsoft Entra admin center and create a new app registration.
2. Use a supported account type that matches your mailbox.
For work or school only: `Accounts in this organizational directory only`.
For personal Outlook.com or mixed support: `Accounts in any organizational directory and personal Microsoft accounts`.
3. Under Authentication, set `Allow public client flows` to `Yes`.
4. For the mobile/desktop platform, add `https://login.microsoftonline.com/common/oauth2/nativeclient` if you want the standard desktop redirect configured.
5. Add delegated Microsoft Graph permissions for `User.Read`, `Mail.Read`, `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `Tasks.ReadWrite`, and `offline_access`.

OES uses the device-code flow, which is supported for public client applications.

## Commands

Check local readiness:

```powershell
python -m oes_agent doctor
```

Authenticate with Microsoft Graph using device code flow:

```powershell
python -m oes_agent auth
```

If you do not have an app registration, skip `auth` and use the desktop Outlook fallback instead.

Load the included sample inbox cache into OES:

```powershell
python -m oes_agent sync
```

Sync live Outlook and calendar data:

```powershell
python -m oes_agent sync --live
```

Behavior of `sync --live`:

- If `OES_GRAPH_CLIENT_ID` is set, OES uses Microsoft Graph.
- If it is not set, OES attempts to read from the local Outlook desktop client.

Run the dashboard locally:

```powershell
python -m oes_agent serve --host 127.0.0.1 --port 8787
```

Windows launcher:

```powershell
run_oes_agent.bat
```

## Phone Access

For same-network phone access, start the server on all interfaces:

```powershell
python -m oes_agent serve --host 0.0.0.0 --port 8787
```

Then open `http://<your-laptop-ip>:8787` on the phone. If Windows Firewall prompts you, allow access on your private network.

## Credentials I Still Need From You For Live Mailbox Access

- `OES_GRAPH_CLIENT_ID`
- optionally `OES_GRAPH_TENANT_ID` if you do not want `common`
- confirmation whether this is a work/school Microsoft 365 mailbox or a personal Outlook mailbox

OpenAI is optional because the agent falls back to heuristic triage. If you want the best drafting quality, keep `OPENAI_API_KEY` configured.

## No-App-Registration Path

If you do not have an app registration today, the fastest path is:

1. Run `python -m oes_agent doctor` to confirm desktop Outlook is available.
2. Run `python -m oes_agent sync --live` to pull mail and calendar from the local Outlook app.
3. Run `python -m oes_agent serve --host 0.0.0.0 --port 8787` to use OES from the laptop and phone browser.

This mode depends on the laptop staying on and Outlook staying signed in, but it avoids the Microsoft Graph app-registration blocker.
