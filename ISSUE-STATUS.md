# Paco backlog status

This change is a testable desktop implementation, not completion of every acceptance criterion in issues #3–#16. No issue was closed or marked complete. Local fixture coverage is distinguished from live validation below.

| Issue | Implemented in this branch | Still required before closing |
| --- | --- | --- |
| #3 Source history | Missing snapshots retain mapping/history, unavailable/reassigned/cancelled/completed outcomes, reappearance/reopening reuse, verified GitHub state checks, dependencies remain blocked on disappearance, legacy primary-calendar key migration | Live replay of all provider-specific cancellation and visibility cases; broader positive-state checks for non-GitHub trackers |
| #4 Commitment reconciliation | Multiple citations can be linked to one task, explicit owner/requester, timezone-aware deadlines, editable task corrections with conflict-aware undo, explicit merge helper, reviewed model completions | Semantic cross-source matching, full merge/split undo, two-week keep/postpone/archive flow, multilingual precision/false-merge evaluation |
| #5 Sources | GitHub review requests, Slack DM/mention evidence, Outlook flagged messages, Jira/Asana/Todoist adapters, native Apple Reminders, account identity checks and sync errors | Live account validation, OAuth refresh/onboarding polish, authorized tracker completion write-back and conflict handling |
| #6 Waiting for replies | Persistent timers and editable drafts, grounded Gmail reply resolution, autoreply protection, drafts survive restart | Detect new outgoing requests automatically; exact-recipient/text approval and immediate pre-send recheck for delivery inside Paco (currently send in source app) |
| #7 Planning and calendar | Local feasible plan, one daily-plan banner after first eligible wake/run, estimates/deadlines, selected Google calendars plus Apple read access, conflicts/join links, Google move preview with attendee notice and ETag check | Selected Apple calendar controls and Apple move writes; calendar/live sleep-wake replays; attendee commitments in plans |
| #8 Meetings | Common transcript JSON import, replay identity, speaker/timestamp evidence, partial-transcript handling, grounded model decisions/assignment proposals, explicit acceptance and post-meeting routine trigger | Post-meeting document drafts. Call/microphone capture and local transcription are now implemented locally (see feature #17 below) but still need live validation |
| #9 Desktop context | Opt-in app/idle flow protection rechecked at notification delivery, plus disabled-by-default per-app Accessibility text capture, pre-capture app/window exclusions, conservative browser/terminal/AI-chat exclusions, secret redaction, pause, seven-day retention, evidence export/deletion | Separate permissioned window-image fallback; live permission revocation and capture/deletion verification across apps |
| #10 Personal memory | Person/project/text/time-scoped cited search, explicit editable writing preferences/goals used by chat, snooze-aware reminder adaptation, persistent notification replies, explicit cadence feedback and reset, task-bound attribution, rejected completion evidence retained, evidence tombstones | Broader learned-pattern proposals with user-visible evidence and correction feedback evaluation |
| #11 Desktop | Native menu bar, fixed Control–Option–P shortcut, menu-bar-only companion with a monochrome parrot icon, setup-only default window, five original expressions, compact actionable cream/peach banners with expandable replies and resumable conversations, source/model setup, background sync, login-startup registration, optional advanced workspace | Configurable global shortcut; full first-login and permission-revocation acceptance, contextual writing insertion |
| #12 MCP | Local stdio, separate live read/write grants, task operations, cited context/search, sessions, durable change polling, mid-session revocation tests | Push change subscriptions, broader privacy tools, independent external-MCP operation preview broker, live Codex-against-disposable-DB test |
| #13 Routines | Opt-in explicit-request-history discovery across three days, local digest proposal/trial, schedule/meeting-import/missing-reply triggers, history/pause/revoke/rejection persistence | Semantic equivalence grouping, wider connector actions/capability checks, measured savings, richer natural-language triggers |
| #14 Delegation | Reviewed briefs, isolated worktrees pinned to a commit, Claude/Codex protocol adapters, durable events/results, exact-session follow-ups, cancellation, orphan-process guard, blocked restart instead of replay | Live provider runs and approval round trips; merge reconciliation; explicit administrative/document edits and externally verified receipts |
| #15 Evaluation | Seven-day deterministic policy replay; mail semantic harness retained; source/agent protocol fixtures, offline behavior and consent tests; actual Mac app/banner checked | Actual local/hosted model comparison, full workload quality/cost/latency measurements, actual login/logout, sleep/wake and permission-revocation checks |
| #16 Speak to own agent | macOS Dictation into a reviewable text field, explicit provider/workspace selection, locally authenticated CLI sessions and exact follow-ups, tool/denial events, visible API-key access boundary | Existing-session discovery and ambiguous-context resolution, full spoken live success/follow-up/denial demonstration with both authenticated providers |

## Readiness round — projects, links, presence, providers

- **Implemented:** projects/areas with hint and model tagging, manual override, focus days (urgent and meeting reminders still interrupt); take-me-there links from every source in banners and the workspace; meeting reminders ~15 minutes before start that pass focus/flow but not holidays/pause; tracker disappearance asks “did you finish it?”; Paco rests while locked, asleep, display off/lid closed or another user is in front (Python loops and native polling); model providers Ollama, private OpenAI-compatible server, Claude Code, Codex CLI, Claude API, Bedrock (API key), OpenAI with **Test connection**; GitLab, Linear (Settings), Microsoft To Do and Outlook Calendar connectors; call-outs and scream on by default, louder and higher.
- **Tested offline:** `test_readiness.py`, `test_models.py`, `test_slacking.py` (recorded API shapes, fake CLIs, mocked presence).
- **Still required:** native build and on-device check of the focus-day menu, rest/wake and Open buttons; live account checks for GitLab, Linear, Microsoft To Do, Outlook Calendar, Bedrock, Claude Code and Codex; Bedrock SigV4; Outlook mail beyond flagged messages.

## Verified locally

- Native macOS app compiled and locally signed.
- Native interface opened, a task was created, and focus protection was visible.
- Menu-bar startup without a floating character, the five-expression menu, and compact top-right expression banners were visually verified. The notification character remains 100 × 100; the bubble is now 364 × 126.
- Login configuration and persisted setup completion have offline tests; actual logout/login remains untested.
- Python unit/integration tests cover policy, source history, transcripts, consent, HTTP origin/auth checks, MCP revocation, connector response fixtures, calendar stale-write rejection, and both CLI protocols using disposable fake agents and real isolated Git worktrees.
- The synthetic week produced zero ordinary holiday interruptions, zero ordinary out-of-hours interruptions, zero meeting interruptions, and zero false closures in the reassignment case. This measures the encoded scenarios, not general intelligence.
- Notification reply tests cover temporary absence, explicit urgency/completion, attribution clarification, focus, persisted cadence feedback, request replay, model consent, bounded proposal schemas, cancellation, stale proposals and HTTP delivery suppression. Model interpretation is tested with fixtures, not a live Claude account.
- Flow-policy tests cover active work, app-switch grace, idle/lock, fresh and stale signals, urgent overrides, manual-focus precedence, opt-out, metadata minimization, and queued HTTP alerts.
- Optional Python dependencies were installed into the project `.venv`.
- Background loops (sync, reminders, flow protection, desktop capture) log and retry a failing pass instead of stopping silently, and show it in Settings' source status until they recover. The database uses WAL with one-time schema setup per process; forgetting evidence or a transcript truncates the log. Covered by `test_reliability.py` (offline).

## Not performed

No personal API key was read from another app, no hosted-model evaluation was run, no live agent task was delegated, no email or other message was sent, no calendar event was modified, and no new macOS privacy permission was accepted. Login startup was not installed. Account-dependent features need the user's explicit setup in Paco and subsequent live validation.

## Meeting feature #17 — local implementation

Implemented native menu-bar start/pause/resume/finish, microphone/system audio capture
without application audio files, bounded local Whisper queues, transcript expiry
(default 14 days), per-user and per-type summary formats, separate summary provider
settings including a private HTTPS endpoint, contextual extraction plus reconciliation,
validated citations, reviewable owners/conditions, explicit personal task acceptance,
correction preservation and summary copying. Native build and deterministic lifecycle
checks pass. A synthetic 9.35-second utterance transcribed locally in about 2 seconds;
the real PCM queue-to-transcript path also passed with no audio files in the session
directory. The review page was visually checked in dark mode.

Still to validate/extend: actual call capture with user-granted macOS permissions,
long calls and hardware/device combinations, live summary-model reasoning quality,
speaker diarization/identity mapping, selected-process capture, semantic task matching
across different meetings, and integrated attendee lookup/approved sending. No summary
model is configured on the development machine, so no live-model accuracy score is
claimed. Changes are local and have not been pushed as part of this implementation.


## Calendar-assisted speaker identity — local implementation

Apple Calendar and Google Calendar sync now retain attendee names, self markers,
response status and email identities without changing the legacy email-list field.
The capture dialog offers nearby events and suggests only a single unambiguous
current event. A one-to-one calendar match supplies a tentative label; group
invitations never imply voice identity. Speaker provenance reaches action extraction,
and calendar-only owner guesses are downgraded rather than becoming confident
commitments.

Added a permission-gated native Zoom Accessibility adapter with an explicit
Zoom-only audio source, an optional Google Meet extension with write-only,
meeting-scoped local pairing, and local Whisper word-timestamp alignment. Mixed
speakers, duplicate names, stale/missing markers and conflicting call sources stay
unnamed. Manual corrections take precedence. Speaker timelines expire with the
transcript; no voiceprint or audio recording is stored.

Verified with calendar/identity/bridge unit tests, HTTP scope tests, native label
parser fixtures, Meet DOM fixtures, native compilation, and an actual in-memory
Whisper run aligned to synthetic Zoom timing signals. The calendar/provenance UI
was checked in dark mode. These are not live Zoom/Meet compatibility tests: the
Zoom parser supports a narrow English label grammar and the Meet adapter depends
on exposed semantic DOM markers. The extension has not been installed, no new OS
permissions have been granted, and no personal meeting has been captured. The
user must enable the desired integration and validate it in a real call. Changes
remain local and unpushed.

## Laptop validation and catalog review — 25 November 2026

Reviewed the new model adapters, source links, focus days, presence gating and
notification interface. Fixed collection of the Codex final answer before temporary
folder cleanup. Model inference uses ephemeral sessions; Claude inference disables
configured MCP servers and hooks. Installed runtime now has its own local Python
environment and does not depend on the external checkout.

Strengthened automatic project discovery, ambiguity handling, word/domain boundaries,
learning from manual corrections, stale-response rejection, classification reasons,
reviewable suggestions, automatic area classification and area filters. Added nine
catalog regression tests and a real subprocess regression for the Codex adapter.

Validation: 185 Python tests passed; seven-day reminder replay passed; seven live
Codex catalog scenarios passed (including automatic project/area discovery). All nine
live meeting reasoning cases passed after fixing the reconciliation schema and
handling passive waiting as a constraint rather than a to-do. Real local Whisper
transcribed 9.35 seconds of generated speech into four segments with no gaps or saved
audio files. Native microphone/system-audio capture and installed UI validation are
recorded separately in the final laptop check report.

Final on-device result: installed Paco 0.4.0 captured actual microphone and system
audio through the native app, transcribed six segments without gaps, and generated
an evidence-aware summary with reviewable actions. No saved recording files were
found. Four reply scenarios passed against the installed HTTP backend (five-hour
snooze, urgency, ambiguous attribution, completion); the test task was archived.
Empty failed capture attempts were removed; the successful test notes remain.

The first real capture revealed Python-attributed macOS recording permissions.
Native startup now uses LaunchServices so Paco has its own privacy identity. After
permission approval and restart, native capture passed. Finder startup also adds
standard user CLI locations to PATH. The installed environment passes all 185
Python tests; a fixture shebang was fixed to support paths containing spaces.
Paco is running under its login LaunchAgent with setup complete, no active capture,
and Codex CLI connected. No work sources are connected yet. Multi-person Zoom/Meet
speaker adapters still need real-call validation. Full local check results are in
`build/laptop-validation.json` and the installed Paco data directory.
