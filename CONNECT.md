# Connect sources and local agents

Use the same Python 3.11+ environment for setup and the desktop app:

```sh
.venv/bin/python -m pip install -r requirements.txt
```

## Google

Enable Gmail, Calendar, Tasks and Drive APIs in a Google Cloud project. Create a Desktop OAuth client and download its JSON. The default scopes are read-only.

```sh
.venv/bin/python paco.py connect google --client ~/Downloads/client_secret.json
.venv/bin/python paco.py connect model anthropic YOUR_MODEL_ID --allow-cloud-mail
.venv/bin/python paco.py sync
```

The API-key prompt is hidden. The same seven choices as Settings work here (see [Models](#models)); for example `connect model ollama qwen3:8b`, `connect model private MODEL --endpoint http://localhost:1234/v1`, `connect model claude_code --allow-cloud-mail`, or `connect model bedrock MODEL_ID --region us-east-1 --allow-cloud-mail`. Local models need no `--allow-cloud-mail`. Hosted processing of other categories is enabled individually in desktop Settings. Existing configurations without explicit category consent need to be saved again.

Gmail starts with recent incoming/outgoing threads, then uses a durable history cursor. Up to four changed threads are analyzed each cycle. Quotes ground new tasks and completion suggestions, but cannot prove a model understood the conversation; completions require review. Tracked waiting-for requests can be resolved by grounded substantive replies from the expected sender. Recognized automated replies do not stop their timer. Follow-up drafts are saved locally and sent manually in the source application.

Primary Google Calendar is the default. To select multiple calendars, set the `calendars` array in `~/Library/Application Support/Paco/sources.json` to their IDs. Explicit Google `outOfOffice` events protect time off. Timed meetings protect focus. Calendar conflicts and join/source links appear in Today.

To enable Google event moves, reconnect with **`--calendar-write`**. A proposed move shows the new time and attendees, then requires **Approve move & notify attendees**. The event's ETag is rechecked before writing. An uncertain write is not retried automatically. Apple events are read-only.

## Mattermost

Paco reads recent direct/group messages and threads personally mentioning your username from channels you belong to. It checks a 14-day window every five minutes while the Mac is awake and active. Full reply context is considered; a mention alone is not a commitment. Up to four changed conversations are analyzed per cycle. Every proposed task must cite an exact message excerpt. Repeated syncs do not recreate the same cited task. Forgetting a message also removes its task citations and prevents reimport.

Create a confidential OAuth application in your Mattermost team's **Integrations → OAuth 2.0 Applications**, with callback `http://127.0.0.1:18773/callback`. Leave **Is Trusted** unchecked. Run:

```sh
.venv/bin/python -m mattermost --base https://YOUR-MATTERMOST-SERVER
```

Enter the client ID and hidden client secret when prompted, then open the printed localhost link in your work browser profile. The loopback flow verifies state and uses PKCE. Credentials, including refresh tokens, stay in macOS Keychain; account settings contain no secrets. Mattermost grants broader account permissions than read-only. Paco's account connector implements only a fixed list of read endpoints. Replies use a separate member bot restricted to your private DM. Authorize only if you accept that provider-level grant.

In **Controls → Model → Allow this model to read**, enable **Mattermost direct messages and mentions** to allow your selected hosted model (including Codex CLI) to extract tasks. Without this permission, context is stored locally but is not analyzed by a hosted model. Message context stays in the local database; only structured tasks sync to the company service. **Disconnect** removes Paco's local account token; revoke the OAuth app in Mattermost as well to invalidate the server-side grant.

### Talk to Paco and update tasks

Create a member bot (username `paco`) in **Integrations → Bot Accounts** and create its access token in that signed-in administrator session. Mattermost deliberately forbids OAuth applications from creating personal/bot access tokens; do not enable server-wide personal access tokens to work around that restriction. The setup command can create the bot if permitted, then asks for its token with a hidden prompt:

```sh
.venv/bin/python -m mattermost_bot --setup
```

The command verifies the token belongs to that bot, stores it in macOS Keychain, adds the bot to your team, and binds its private DM to your connected Mattermost user ID. The bot has Member permissions; it is not an administrator. Paco's runtime rejects other recipients, public/group channels, bot-authored commands and other users' requests. **Controls → Sources → Mattermost → Message Paco** opens the DM.

Examples: “Add a task to review the proposal”, “Juan will handle that; keep it open”, “Remind me in five hours”, “That is done”, and “What should I focus on?” It uses the conversation to resolve references, asks when ambiguous, and confirms only committed changes. Each reply and change has a durable receipt so restarting does not replay it. If delivery is uncertain, Paco checks for its receipt instead of blindly sending again. Send a new message to correct a command; editing a processed message does not undo or rerun it.

Private DMs are checked approximately every 15 seconds while Paco is running and the Mac is awake/unlocked. Messages sent while the Mac is unavailable wait until it returns. Background conversation discovery remains on the five-minute cycle. Neither path uses a model without the Mattermost processing permission.

For existing tasks, new statements from you can update status, priority, deadlines, reminder times, assignment, and task details. Passive discovery only updates tasks already associated with that conversation/channel; a direct DM with Paco can explicitly reference any of your local tasks. Older messages cannot overwrite later edits, and a task changed during interpretation is checked again before saving. Changes reported by someone else become pending proposals. Ask Paco “show pending changes” and confirm the proposal you want applied. Controls shows the pending count. Assignment to Juan is a task label, not delivery to Juan's Paco account.

Only task fields sync to the company service. Raw source messages and bot processing history stay on the Mac (selected context is sent to your approved model). Disconnect removes both local credentials; revoke the OAuth grant and bot token in Mattermost to invalidate them at the provider.

## Other sources

GitHub uses the account authenticated in `gh` and checks its identity before polling. Connect in Settings or run `paco.py connect github`. GitHub requested reviews are also imported. Disappearing assignments become unavailable, retaining identity and history. A positive provider completion may satisfy dependencies; disappearance alone cannot. When an open item disappears from a task tracker (GitHub, GitLab, Linear, Jira, Asana, Todoist, Microsoft To Do, Google Tasks, Apple Reminders), Paco stops reminding and asks in the workspace whether you finished it.

Linear can be connected in Settings or with `paco.py connect linear`. Drive metadata and explicitly tracked local Git repositories remain available through the CLI:

```sh
.venv/bin/python paco.py track /absolute/path/to/repo
.venv/bin/python paco.py activity
```

Additional desktop adapters use independently entered tokens stored in Keychain:

| Source | Read behavior | Token / limits |
| --- | --- | --- |
| Slack | Recent DMs and mentions as searchable evidence; review before creating tasks | User token with `search:read`; source account is workspace/user |
| GitLab | Open issues assigned to you and merge requests awaiting your review (`Review: …`) | Personal access token with `read_api`; optional `https://gitlab.example.com` for self-hosted |
| Linear | Your assigned, unfinished issues | Personal API key |
| Outlook | Flagged messages | Microsoft Graph OAuth bearer token with appropriate delegated mail/profile access; manual reconnect on expiry |
| Outlook Calendar | Next seven days of meetings: busy time, Teams/online join links, attendees, “Prepare for …” tasks | Graph token with `Calendars.Read`; cancelled, declined and all-day events are skipped; “free” events don’t block time |
| Microsoft To Do | Unfinished tasks in all your lists | Graph token with `Tasks.Read` |
| Jira Cloud | Issues assigned to the authenticated user | OAuth bearer token and `https://your-team.atlassian.net` site |
| Asana | Incomplete assigned tasks in the user's workspaces | Personal/OAuth access token |
| Todoist | Open tasks | Personal/OAuth access token |
| Apple Reminders | Incomplete reminders | Explicit macOS Reminders permission |
| Apple Calendar | Timed events and busy intervals | Explicit macOS Calendar permission |

Every task keeps a link back to its source (issue, email thread, meeting join link, Apple app), shown as **Open** in banners. These adapters do not yet implement completion write-back. Their fixture tests are not proof of successful live authentication or organization-specific permissions.

## Models

Choose in **Settings → Model** (with **Test connection**) or with `paco.py connect model`:

| Provider | Setup | Notes |
| --- | --- | --- |
| `ollama` | `ollama pull qwen3:8b`, then the model name | Local; needs no data permissions |
| `private` | Any OpenAI-compatible `/v1` server: LM Studio, llama.cpp `llama-server`, vLLM, LiteLLM | `http://` only for localhost (counts as local); remote servers need `https://`. Optional key |
| `claude_code` | `npm i -g @anthropic-ai/claude-code`, run `claude` once to sign in | Uses your Claude subscription. Runs `claude -p` with no tools, one turn, in an empty temp folder; API-key environment variables are removed so the subscription is used |
| `codex_cli` | Install Codex, run `codex login` | Uses your ChatGPT plan. Runs `codex exec` in a read-only sandbox in an empty temp folder |
| `anthropic` | API key from console.anthropic.com | |
| `bedrock` | Region and a Bedrock API key; model or inference-profile ID copied from the Bedrock console | Uses the Converse API. IAM access keys / SigV4 profiles are not supported yet |
| `openai` | API key | |

Hosted choices only receive the categories you tick. Meeting summaries can use a separate model (Meeting notes → preferences).

## Local agent sessions

Connect the executable and a trusted Git repository in Settings. The reviewable brief identifies the base commit, whether uncommitted changes are omitted, the objective, and acceptance requirements. Session events expose tool availability, progress, permission denials, and results. Follow-ups use the recorded provider session ID, never an implicit “last session.” Restart blocks uncertain sessions rather than duplicating an action. Cancellation targets the process group and PID identity is checked when recovering an existing process.

Local-agent permissions are independent of an API model connection. Some required approvals must still be completed in the provider's own interface. The bridge does not grant blanket permissions or automatically enable tools.

## Scoped local MCP

Grant only the scopes a named local client needs:

```sh
.venv/bin/python paco.py mcp-grant my-agent tasks.read memory.read sessions.read
.venv/bin/python paco.py mcp --client my-agent
```

Configure the latter command as a local stdio MCP server in your agent. Add `tasks.write` only when the agent should create or edit Paco tasks. Revoke all scopes with `paco.py mcp-grant my-agent`. Each call checks the current grant; the tool list also reflects it. The protocol exposes tasks, cited memory/context packs, session status and change-cursor polling. Push subscriptions and an independent external-MCP operation broker remain unfinished.

## Local state

`tasks.sqlite3` contains tasks, citations, drafts, preferences, agent session metadata and history. `sources.json` contains source settings without API secrets. Do not commit either file. Desktop exports show stored evidence and preferences. Forgetting an item removes its evidence text and tombstones its source identity. Screenshots are not collected. Audio is captured only during meeting notes you start yourself, transcribed in memory and never saved as audio.

The database uses SQLite write-ahead logging, so `tasks.sqlite3-wal` and `tasks.sqlite3-shm` appear beside it. They belong to the database: back up or move all three together, preferably while Paco is quit. Deleting evidence or a transcript also truncates the log.

## Company task service / ChatGPT web

The remote company MCP uses OAuth and a task-only database. This differs from the local MCP's access to Mac context. See [COMPANY.md](COMPANY.md) for the endpoint, account setup, tool catalog, sync behavior and exact privacy boundary.
