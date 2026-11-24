# Local data model

SQLite is the source of truth. Use SQLAlchemy and versioned Alembic migrations. Store instants in UTC and retain the source time zone and date-only deadlines. Use FTS5 for local lookup. Optional embeddings reference deletable records.

| Records | Fields and constraints |
| --- | --- |
| Account, source scope, cursor | Provider, external account ID, selected scope, cursor, last success and error. Unique account and scope pair. |
| Event, evidence | Stable provider key, revision, timestamp, source URL, retained excerpt, lease and processing status. Deduplicate by account, scope and event key. |
| Objective, project, person | User-defined priority, project membership, external identities and aliases. |
| Task, dependency | Project, owner, next action, status, estimate, due time, confidence, follow-up and correction flags. Unique dependency edges. Reject cycles. |
| Task revision, evidence link | Previous and new value, actor, reason, evidence IDs and time. Preserve user overrides by field until explicitly cleared. |
| Plan block, intervention | Task, start/end, protected flag, scheduled delivery, escalation level, delivery key, response and next eligible time. |
| Observation, preference | Context, intervention, outcome, sample size, inferred preference and user decision. Keep inferences editable. |
| Action request | Target, payload digest, approver, expiry, execution status and provider receipt. A changed payload requires new approval. |

## Reconciliation rules

An outgoing promise can create an open task. Match on stable source links and owner before considering semantic similarity. Ambiguous matches stay pending review. A document edit records progress. A proposed deadline change remains provisional until accepted. A sent deliverable linked to the same commitment can close it and create a separate follow-up. Waiting tasks stay out of the actionable queue until a response or follow-up time arrives. An explicit user correction wins over subsequent inferred changes. Preserve the conflicting evidence for inspection.
