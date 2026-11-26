# Paco company tasks and ChatGPT

Paco 0.5 adds a company task account and reviewable project breakdowns. The Mac remains a menu-bar companion. Choose **Add tasks from text…** from its parrot menu, paste a list or project brief, and review the proposed tasks before adding them. You can edit titles, details and owners, or remove tasks. Paco proposes projects, areas, tags, parent tasks and dependencies; it flags unclear commitments instead of inventing deadlines. The configured model processes the brief (currently Codex CLI on Nathalia's Mac).

## Connect ChatGPT

The permanent MCP address is **https://paco.optimai.cl/mcp**, served from OVH. Hostinger manages the DNS record. The existing Caddy reverse proxy terminates HTTPS and renews certificates automatically. The old temporary Cloudflare address is retired. See [TEAM-SETUP.md](TEAM-SETUP.md) for the short colleague and ChatGPT instructions.

In ChatGPT's custom MCP/plugin setup, add this URL with **OAuth**, then sign in to your Paco account. Dynamic client registration is supported, so no shared client secret is needed. Availability and menu names depend on your ChatGPT plan and workspace policy. See [OpenAI's connection guide](https://developers.openai.com/plugins/deploy/connect-chatgpt/).

Try: “Read my Paco projects. Turn this brief into a plan, show me the breakdown, then add it after I approve.” Or: “Add a task to review the launch proposal.” Read current revisions before updates. A stale update is rejected rather than overwriting another edit.

Available tools: `tasks_list`, `task_get`, `task_create`, `task_update`, `projects_list`, `project_create`, `plan_format`, `plan_preview`, `plan_apply`. List tools paginate; follow `next`. Stable request IDs make retries idempotent. Batch plans contain at most 80 tasks and 20 new projects and apply atomically.

## Codex and other desktop MCP clients

Paco 0.5.1 includes `company_mcp.py`, a stdio bridge to the same nine company-task tools. On the original pilot Mac it is already registered as **paco** in Codex and verified through a real Codex tool call. It reads the connected account from Paco's installed database and retrieves its device token from macOS Keychain; no token is copied into Codex configuration.

For another MCP-capable desktop client on this Mac, use this command and argument:

```text
Command: /Users/YOUR_MAC_USERNAME/Library/Application Support/Paco/.venv/bin/python
Argument: /Users/YOUR_MAC_USERNAME/Library/Application Support/Paco/company_mcp.py
```

Sign in through Paco settings first. The bridge follows that account's current service address and reports a reconnect error if its session expires. It exposes company tasks and projects, not meeting transcripts or local activity. Remote clients such as ChatGPT use the HTTPS/OAuth connection above. An LLM needs an MCP-capable host to use these tools; model inference alone does not establish an MCP connection.

## What is stored where

| Data | Location |
| --- | --- |
| Tasks, descriptions, status, urgency, owners, dates, estimates, goals, project/area catalog, tags, parents, dependencies, source links | Mac and authenticated company task service |
| Meeting transcripts (14 days by default), summaries, speaker evidence | Mac only; meeting-model processing still follows your configured model and consent |
| Activity history, screen/context observations, reply history, original pasted briefs | Not uploaded by company sync |
| Model credentials and company device token | macOS Keychain; the company password is not saved by Paco |
| Company passwords | Argon2id hashes on the server |
| OAuth tokens | Only token hashes plus expiry/scope/account metadata on the server |

Each manually created account has its own task catalog. Knowing another person's task ID does not grant access. An assignee name is task metadata, not a shared inbox or permission grant. This version has no cross-account project sharing. Every task on a connected Mac syncs to that account, including tasks in a Personal area; use a separate database/macOS account for work that must remain outside the company task store.

The task API rejects unsupported fields such as transcripts and activity. Text deliberately placed in an allowed task description is still task data, so avoid pasting raw private records into task descriptions through ChatGPT.

Sync runs about every 30 seconds while the Mac is awake. Offline changes remain local and retry automatically. Different-field edits merge. Conflicting edits to the same field are shown in Settings, where you choose the version to keep. Completion, cancellation and archiving sync. Deleting a project locally does not delete its remote record; shared project deletion is not implemented. Device sign-in lasts 30 days; Settings requests reconnection when it expires. Disconnect revokes the device session when online and always removes the local credential.

## Server operations

Installation: `/home/ubuntu/paco` on `ubuntu@ovh`. The Python service binds only `127.0.0.1:8765`; Caddy supplies HTTPS. SQLite uses WAL transactions, revisions, account-scoped queries and durable idempotency receipts. For this small internal service, SQLite avoids a separate database daemon and uses little disk or memory. Data is in `data/paco.sqlite3` with private filesystem permissions. No model or audio stack is installed on the server.

Deploy the `server/` directory, `task_contract.py`, and `intake.py` to `/home/ubuntu/paco`, preserving `data/` and `.venv/`. Then run:

```sh
cd /home/ubuntu/paco
sh server/install-user-service.sh https://paco.optimai.cl
sudo loginctl enable-linger ubuntu
```

On OVH, `/home/ubuntu/.config/marktwin/playground-caddy/paco.caddy` contains the site configuration from `server/paco.caddy`. The existing Caddyfile imports `/config/paco.caddy`; the `marktwin-playground-caddy` container uses host networking and restarts unless explicitly stopped. Port 80 belongs to another application, so certificate validation uses TLS-ALPN on port 443. Do not replace the whole Caddyfile or restart unrelated applications when deploying Paco. Validate and reload the existing proxy:

```sh
sudo docker exec marktwin-playground-caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo docker exec marktwin-playground-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
curl --fail https://paco.optimai.cl/health
```

The task service and daily maintenance timer start automatically. The health timer retries a failed loopback probe, then restarts an unresponsive task service. The server uses Streamable HTTP with JSON responses. Maintenance removes expired authentication state and keeps the seven latest daily database snapshots in `data/backups`. These are same-server recovery copies, not offsite backups. The task change feed remains available for offline clients; operation retry receipts expire after 90 days. The old Quick Tunnel is no longer part of this deployment.

```sh
systemctl --user status paco-company.service
systemctl --user list-timers paco-maintenance.timer
journalctl --user -u paco-company.service --since today
curl http://127.0.0.1:8765/health
.venv/bin/python -m server.admin --db data/paco.sqlite3 create-user alice
.venv/bin/python -m server.admin --db data/paco.sqlite3 reset-password alice
.venv/bin/python -m server.admin --db data/paco.sqlite3 revoke-sessions alice
.venv/bin/python -m server.admin --db data/paco.sqlite3 disable-user alice
.venv/bin/python -m server.admin --db data/paco.sqlite3 list-users
.venv/bin/python -m server.admin --db data/paco.sqlite3 maintenance
```

Create/reset commands prompt privately for passwords. Resetting a password or disabling an account revokes existing sessions. There is no public registration endpoint. OAuth uses authorization code + S256 PKCE, exact registered callbacks, short-lived single-use codes, resource-bound access tokens and rotating refresh tokens. The login form has CSRF protection; login, authorization and registration are rate limited. Access logging is disabled to keep authorization codes out of request logs.

To restore, stop the service, preserve the current `data/` directory, restore a selected SQLite snapshot to `data/paco.sqlite3` without carrying over old WAL/SHM files, set mode 600, and restart. A restore rewinds sync revisions: disconnect existing clients and reinitialize their company sync mapping from the restored catalog before resuming writes.

## Verification

Install `server/requirements.txt` and run `python -m unittest test_company -v` for isolation, OAuth/PKCE, token revocation, transactional plans, private-field rejection, offline retry, forward dependencies, focus preservation and conflict handling. Run the full repository suite before installing the Mac app with `python paco.py install`. Public HTTPS availability and a real ChatGPT account connection are separate from local/tunneled tests.
