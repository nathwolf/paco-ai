# Paco: internal pilot setup

Paco runs on **macOS 14.2 or newer**, on Apple silicon and Intel Macs.
Company service: **https://paco.optimai.cl**. ChatGPT endpoint:
**https://paco.optimai.cl/mcp**.

## For a colleague

1. Ask your administrator for your own Paco username and password.
2. Download `Paco-0.6.2-macOS.zip` from the [pilot release](https://github.com/nathwolf/paco-ai/releases/tag/v0.6.2-pilot) and unzip it.
3. Open **Install Paco.command**. If macOS blocks it, use **System Settings → Privacy & Security → Open Anyway** for this downloaded installer, then open it again. This pilot is not Apple-notarized; do not disable Gatekeeper globally.
4. Wait for installation. The installer downloads a checksum-verified private Python runtime and dependencies; you do not need Homebrew or Xcode. Internet access is required. It installs the app into Applications (your own Applications folder if the system folder is not writable).
5. Click the small Paco icon in the menu bar. Under **Controls → Company task account**, use `https://paco.optimai.cl` and your own credentials.
6. Choose your model under Controls. For Codex CLI, install/sign in to Codex on your Mac first; for another supported provider, enter your own connection. Your colleague's model credentials are not included in the installer. Enable calendar, microphone, and system-audio access only for the features you choose to use.

After installation the downloaded folder can be deleted. Paco starts at login and keeps its runtime and private data under `~/Library/Application Support/Paco`. Opening Paco from Applications brings up Tasks. The five expressions, meetings, focus sessions, and light/dark controls are included.

Each account has its **own** tasks and projects. Naming an assignee does not share a task with that person's account. Shared team projects and cross-account delegation are not included in this pilot. Transcripts, summaries, and activity are not uploaded by company sync; configured model processing has its own consent settings. Audio is never saved.

## Connect ChatGPT web

For task creation and editing, use a ChatGPT Business or Enterprise/Edu workspace that allows custom MCP connections. In Business, an administrator/owner creates and publishes the connection.

1. Open **Plugins → + → Add custom MCP server**. In the legacy interface use **Workspace settings → Apps → Create**.
2. Name: **Paco**. Endpoint: **https://paco.optimai.cl/mcp**. Authentication: **OAuth**. Dynamic client registration is supported; no shared client secret is needed.
3. Sign in with your own Paco account, review the tools, and create/install the connection.
4. In a new chat select **@Paco** and try: “Show my Paco tasks. Add a task to review the proposal tomorrow.” Confirm the write if ChatGPT asks, then check that it appears in the Mac app.
5. To make it available to the workspace, publish the tested connection using the workspace app/plugin controls. Each colleague connects their own Paco account.

See [OpenAI's current connection guide](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt). Plan restrictions and menu labels can change. The public MCP and OAuth flows are integration-tested; an actual ChatGPT workspace connection must still be completed in your account.

## Administrator: create a colleague's account

From a computer that can SSH to OVH:

```sh
ssh -t ubuntu@ovh 'cd /home/ubuntu/paco && .venv/bin/python -m server.admin --db data/paco.sqlite3 create-user alice'
```

Replace `alice` with the colleague's username. Enter a unique password at the private prompt and share it directly with that colleague. There is no public signup. Use `reset-password alice` instead of `create-user alice` to change a password; this revokes existing sessions.

## Current deployment and recovery

The production task service is on **OVH**, not the former `issnathalia` host. Hostinger DNS maps `paco.optimai.cl` to OVH. The existing Caddy HTTPS proxy supplies and renews the certificate. Systemd starts Paco after boot, restarts it after failure, checks health every two minutes, and creates daily database backups (seven retained). These are same-server backups; they do not replace an independent off-server backup policy. No service can guarantee availability if its host or network is down.

The November 26 migration recovered the account and synchronized structured records available on the Mac. The old host was offline, so any changes present only there could not be recovered. Preserve its old database for reconciliation when it returns; do not resume syncing clients to the old address.

Read [COMPANY.md](COMPANY.md) for operations, privacy, and data recovery details.
