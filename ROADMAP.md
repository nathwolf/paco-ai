# Delivery milestones

| Milestone | Build | Demonstration required |
| --- | --- | --- |
| 1. Local foundation | Python package with uv, SQLite migrations, event worker, CLI, model gateway interface, persistent scheduler and macOS notification delivery. | Create a task, receive a notification, snooze, restart the service, then receive one reminder at the revised time. Complete the task and verify future reminders stop. Repeat offline. |
| 2. Source awareness | Desktop authentication, Gmail, Calendar and GitHub incremental sync, model extraction and evidence-backed reconciliation. | Import a promise, revise its deadline, link a sent deliverable and close it. Replay duplicate pages and an expired cursor. Inspect the evidence behind every transition. |
| 3. Daily accountability | Objectives, calendar-aware planner, focus sessions, SwiftUI controls, Spanish prompts and escalating reminders. | Replay a workday containing a moved meeting, an ignored task and a blocker. Verify the revised plan and notification history. |
| 4. Personal adaptation | Drive, one project tracker, selected local Git repos, optional activity signals and weekly review. | Explain a repeated blocker using recorded outcomes. Accept or dismiss a preference and verify its effect on later recommendations. |
| 5. Extended execution | Local model adapter, approved external writes, voice, animations and optional mobile delivery. | Compare hosted and local extraction on the same fixtures. Verify an approved write exactly once where the provider supports idempotency and reconcile ambiguous outcomes before retry. |

Begin with the CLI-to-notification path in milestone 1. Use synthetic data in CI. Validate notification actions, login startup and sleep recovery on a real Mac; validate provider authentication separately with an explicitly selected account.
