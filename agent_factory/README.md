# Agent Factory

`agent_factory` is a meta-agent project: one factory agent creates other machine-learning specialist agents.

Each generated specialist agent has:
- A trained task model (`classification` or `regression`) from labeled CSV data.
- A topic knowledge index from local docs (`.txt`, `.md`, `.csv`, `.json`, `.log`, `.rst`).
- Runtime commands for task prediction and topic Q&A.

## Quick Start

1. Install dependencies:

```bash
python -m pip install -r agent_factory/requirements.txt
```

2. Create a specialist agent:

```bash
python -m agent_factory.cli create-agent \
  --name "SupportRouter" \
  --description "Routes user support requests to the right queue." \
  --topic "Customer Support" \
  --task-type classification \
  --dataset agent_factory/examples/support_training.csv \
  --knowledge agent_factory/examples/knowledge \
  --input-column input \
  --target-column target \
  --output-dir generated_agents
```

3. Run task prediction:

```bash
python -m agent_factory.cli predict \
  --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS \
  --input "I was charged twice this month"
```

4. Ask a topic question:

```bash
python -m agent_factory.cli ask \
  --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS \
  --question "How should billing disputes be handled?" \
  --top-k 3
```

5. Inspect agent metadata:

```bash
python -m agent_factory.cli describe --agent-dir generated_agents/supportrouter_YYYYMMDD_HHMMSS
```

6. List all generated agents:

```bash
python -m agent_factory.cli list --output-dir generated_agents
```

## Dataset Format

Training dataset must be CSV with at least two columns:

- `input`: text used for training.
- `target`: label (classification) or numeric value (regression).

You can rename these with `--input-column` and `--target-column`.

## Notes

- Small datasets (<10 rows) are trained and evaluated on the same data.
- Larger datasets use a holdout split for evaluation metrics.
- Topic answers are retrieval-based excerpts from indexed knowledge docs.

## Bootstrap the Three Requested Agents

This project includes a helper script that creates:
- `OutlookEmailManager`
- `LandDealUnderwriter`
- `HousingMarketResearcher`

Run:

```bash
python -m agent_factory.bootstrap_requested_agents
```

## Outlook Integration Without Admin Access

If you do not have Azure admin access, use local Outlook Desktop automation:
- No tenant ID required
- No app client ID required
- Uses your existing signed-in Outlook profile on Windows

Requirements:
- Windows
- Outlook Desktop installed and signed in
- `pywin32` installed (included in `requirements.txt` for Windows)

Quick workflow (no long IDs needed):

```bash
python -m agent_factory.cli outlook-local-inbox --top 20 --unread-only
```

This command caches message indexes in `generated_agents/outlook_local_cache.json` so follow-up commands can use `--index`.

```bash
python -m agent_factory.cli outlook-local-read --index 1
```

```bash
python -m agent_factory.cli outlook-local-draft-reply --index 1 --agent-dir generated_agents/outlookemailmanager_YYYYMMDD_HHMMSS
```

```bash
python -m agent_factory.cli outlook-local-mark --index 1
```

```bash
python -m agent_factory.cli outlook-local-move --index 1 --folder "Inbox/Archive"
```

```bash
python -m agent_factory.cli outlook-local-triage --agent-dir generated_agents/outlookemailmanager_YYYYMMDD_HHMMSS --top 15 --unread-only --auto-draft --max-drafts 5
```

Additional local commands:

```bash
python -m agent_factory.cli outlook-local-folders --query "inbox"
```

```bash
python -m agent_factory.cli outlook-local-drafts --top 20
```

```bash
python -m agent_factory.cli outlook-local-send-draft --index 1
```

```bash
python -m agent_factory.cli outlook-local-draft-reply --index 1 --body "Thanks, I will review and follow up." --send-now
```

```bash
python -m agent_factory.cli outlook-local-create-event --subject "Deal Call" --start "2026-02-06T14:00:00" --end "2026-02-06T15:00:00" --attendees analyst@company.com
```

## One-Button Outlook Agent Panel

This project now includes an Outlook add-in with one ribbon button: `Launch Agent`.

Clicking that single button opens a chat panel where you orchestrate tasks by typing commands.

### 1. Start the panel server

```bash
run_outlook_agent_panel.bat
```

This runs `agent_factory.outlook_panel_server` at `https://localhost:8765` and serves the panel UI.

### 2. Sideload the add-in in Outlook

Use the manifest file:

`outlook_addin/manifest.xml`

Typical path in Outlook:
- `Get Add-ins` -> `My add-ins` -> `Add a custom add-in` -> `Add from file`
- Select `outlook_addin/manifest.xml`

### 3. Use the panel

Open any message in Outlook and click `Launch Agent`.

Supported panel commands:
- `help`
- `status`
- `inbox 10`
- `unread 10`
- `triage 10 unread`
- `read 2`
- `draft 2`
- `draft 2 send`
- `mark read 2`
- `move 2 to Inbox/Archive`
- `folders inbox`
- `drafts 20`
- `send draft 1`
- `event "Deal Call" 2026-02-10T14:00:00 2026-02-10T15:00:00 attendees=analyst@company.com`

## Desktop App (No Outlook Add-in Needed)

If your company blocks Outlook add-in sideloading, use the standalone desktop app.

### Launch directly

```bash
run_outlook_agent_desktop.bat
```

This launch mode uses `pythonw`, so no terminal window stays visible.

### Add a Desktop shortcut (double-click to start)

```bash
install_outlook_agent_desktop_shortcut.bat
```

This creates:
- `Outlook Agent Desktop.lnk` on your Windows Desktop

### In-app usage

Use commands or natural language like:
- `help`
- `inbox 10`
- `triage 10 unread`
- `read 1`
- `draft 1`
- `mark read 1`
- `move 1 to Inbox/Archive`
- `review all my emails to learn about my job`
- `check unread emails`
- `draft a reply to the first message`

### Learning over time

The desktop app now persists learned mappings and history at:
- `generated_agents/outlook_agent_learning.json`

Teach it custom phrases:
- `learn "morning sweep" => triage 20 unread`
- `when i say quick inbox do inbox 8`
- `forget "morning sweep"`
- `memory`

## Outlook + Microsoft Graph Integration

`OutlookEmailManager` is now wired to Microsoft Graph for:
- Reading inbox messages
- Creating draft replies
- Creating calendar events
- Inbox triage using the trained specialist model

### 1. Azure App Registration Setup

Create an app registration in Azure AD and allow public client flow (device code flow).

Required delegated Microsoft Graph permissions:
- `User.Read`
- `Mail.ReadWrite`
- `Mail.Send`
- `Calendars.ReadWrite`
- `offline_access`

Grant admin consent if your tenant policy requires it.

### 2. Environment Variables

Set these before running Outlook commands:

```powershell
$env:MS_TENANT_ID = "<your-tenant-id>"
$env:MS_CLIENT_ID = "<your-app-client-id>"
```

See `agent_factory/.env.outlook.example` for a template.

Optional:

```powershell
$env:MS_GRAPH_SCOPES = "User.Read,Mail.ReadWrite,Mail.Send,Calendars.ReadWrite,offline_access"
$env:MS_TOKEN_CACHE_PATH = ".graph_token_cache.bin"
```

### 3. Commands

Read inbox:

```bash
python -m agent_factory.cli outlook-inbox --top 20 --unread-only
```

Create a draft reply from explicit text:

```bash
python -m agent_factory.cli outlook-draft-reply --message-id "<message-id>" --body "Thanks, I will follow up by end of day."
```

Create a draft reply generated by `OutlookEmailManager`:

```bash
python -m agent_factory.cli outlook-draft-reply --message-id "<message-id>" --agent-dir generated_agents/outlookemailmanager_YYYYMMDD_HHMMSS
```

Create calendar event:

```bash
python -m agent_factory.cli outlook-create-event --subject "Deal Review" --start "2026-02-06T14:00:00" --end "2026-02-06T15:00:00" --timezone "Pacific Standard Time" --attendees analyst@company.com broker@company.com
```

Triage inbox with `OutlookEmailManager` model:

```bash
python -m agent_factory.cli outlook-triage --agent-dir generated_agents/outlookemailmanager_YYYYMMDD_HHMMSS --top 15 --unread-only
```

Triage and auto-create draft replies for `draft_reply` predictions:

```bash
python -m agent_factory.cli outlook-triage --agent-dir generated_agents/outlookemailmanager_YYYYMMDD_HHMMSS --top 15 --unread-only --auto-draft --max-drafts 5
```
