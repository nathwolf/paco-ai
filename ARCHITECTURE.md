# Architecture

Paco is a single-user, macOS-first modular monolith. A Python service owns the SQLite database and runs independently of the SwiftUI menu bar app. A CLI exercises the same application commands. A login service starts the runtime. After wake it reconciles missed work and delivers at most one current reminder per commitment.

## From a source change to a reminder

1. Each connector performs a bounded initial import, then resumes from its per-account cursor. Commit normalized events and the next cursor in one transaction. A unique source-event key makes retries safe. Back off on rate limits, flag expired credentials, and rebuild the affected scope if a cursor expires.
2. A worker leases pending events, fetches the minimum context and proposes structured changes. Validate model output with Pydantic. Apply accepted changes, append evidence and mark the event processed atomically. Expired leases can be reclaimed.
3. The planner fits actionable tasks into free intervals around fixed commitments. Rank by deadline slack, strategic priority and delay cost. Respect dependency order, available duration and protected focus. Penalize moving an existing block. Start with a deterministic heuristic, then compare OR-Tools CP-SAT against it on replayed days.
4. A persistent scheduler wakes each minute to evaluate due reminders. Store a stable delivery identifier before calling the macOS notification adapter. Reconcile pending deliveries after restart. Route notification actions back through the same commands as the CLI.
5. Morning and evening jobs build the plan and reconcile unfinished work. A weekly job compares time spent with stated objectives and proposes changes in reminder timing or style.

## Connector contracts

| Source | Initial and incremental strategy |
| --- | --- |
| Gmail | Selected recent threads, then mailbox history by account. Read sent messages as evidence of delivery. |
| Calendar | Selected calendars with per-calendar sync tokens. Reconcile cancellations, recurring instances and time zones. |
| GitHub | Selected repos, issues, PRs and review requests. Poll with conditional requests and follow pagination. |
| Drive and Docs | Selected files or folders and a Drive changes cursor. Fetch document excerpts on demand. |
| Project tracker | Start with one tracker selected by the user. Map assignments, due dates and status transitions to source events. |
| Local Git and activity | Watch explicitly selected repos. Optionally import ActivityWatch time intervals with exclusions and idle detection. |

Initial polling targets are 3 minutes for Gmail, 2 for Calendar, 5 for GitHub and 15 for Drive. Make these configurable. Add MCP adapters for on-demand tools. Use separate desktop OAuth credentials for each Google account and restricted GitHub credentials. Store secrets in Keychain.

## Models and permissions

Use one typed model gateway for extraction, relevance assessment and reminder wording. Adapters accept a task type, minimized context and output schema. Record latency, usage and model version. Bound cost and retries. Start with a hosted API chosen at configuration time. Exercise the same contract against Ollama or MLX later. Offline planning and escalation use persisted facts and templates. A model outage leaves extraction pending.

Keep credentials and personal data outside the checkout. Use owner-only local storage on encrypted disk, configurable retention, deletion and encrypted backups. Hosted processing requires explicit selection of permitted sources. Treat retrieved text as evidence. Only application commands can authorize actions. Bind any FastAPI service to loopback with per-install authentication. Shared writes require approval of the exact target and payload, followed by outcome verification. Disable arbitrary shell execution.
