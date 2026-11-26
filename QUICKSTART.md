# Try Paco on your Mac

Open **Paco** in **Applications**. The installed app has Paco's parrot artwork; it lives in the menu bar as a small monochrome parrot icon. Opening the app brings up Tasks, including when Paco is already running. Controls contains your settings. Login startup stays quiet after setup. Settings follow your Mac’s light or dark appearance automatically. Click the menu-bar icon for settings, holiday mode and expression previews. Control–Option–P opens the same small menu. Paco uses a private local database and a loopback-only backend. Developers can also use `run-paco.command` or the locally built `build/Paco.app`.

The development checkout has a prepared `.venv` and a built Mac app. On a fresh checkout, use Python 3.11 or later and Apple's Command Line Tools:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python build_app.py
./run-paco.command
```

If macOS refuses to open a downloaded executable, build it locally using the commands above. The app is locally signed, not notarized for distribution.

## The four tabs

- **Tasks** opens by default. Talk with Paco at the top, or choose **Turn into tasks** to review a project/list breakdown before adding it. Use **New task** for a quick manual entry. Below, switch between List, Board, Calendar and Gantt; search and filter by project, area, tag or state, and sort by deadline, priority, project or title. Select a task to edit its notes, deadline, project, tags, owner, estimate and urgency. Gantt currently shows estimated work windows ending at deadlines, not independently planned start dates or drag-to-reschedule dependencies.
- **Meetings** offers capture in the native Mac app, suggests a unique current or upcoming calendar event within 15 minutes, and lists previous meetings, summaries and actions. Calendar suggestions remain optional and ambiguous overlaps require your choice.
- **Sessions** starts a named 15–90 minute focus session, optionally linked to a task. The timer survives closing/reopening the app. These sessions silence all Paco notifications, including upcoming-meeting reminders, until the session ends. They do not block websites or other applications. Recent sessions stay local. Advanced agent work, routines and memory search remain under the secondary link here.
- **Controls** groups connections, models, hours, projects, flow protection and other settings in collapsible sections. Light/dark appearance follows macOS. Decorative section dividers stay removed. The visual direction is softly Duolingo-inspired: rounded typography and shapes, warm leaf green, small pastel accents, and shallow depth on primary actions. Keep it compact and calm; avoid neon green, oversized gamification, or copying Duolingo’s branding.

## First try

1. Connect the sources you want Paco to follow in the initial settings sheet. Connected sources sync in the background; no daily dashboard visit is needed.
2. Optionally connect a model, then set your work hours and weekdays. A new database starts with Monday–Friday, 09:00–18:00.
3. Preview all **five expressions**: friendly, impatient, angry, furious and red rage. Notifications use a compact 364 × 126 cream/peach bubble while retaining the 100 × 100 character image. Red rage is reserved for explicitly urgent tasks at least three days overdue.
4. Leave **Start Paco when I log in** checked and click **Done — keep Paco running**. Settings close; Paco keeps syncing and checking for reminders. The desktop corner stays clear between notifications; use the menu-bar icon for settings and conversation.
5. Choose **Holiday — urgent only** from Paco's menu when away. Ordinary overdue or high-priority tasks do not become emergencies. Only explicitly urgent tasks may interrupt time off, at most twice per task per day, six hours apart.
6. Notifications offer **Done**, **Later** (15 minutes) and either **Open** or **Focus**. When the task came from somewhere you can open — a GitHub or GitLab issue, an email thread, a Jira/Linear/Todoist/Asana task, a meeting's video link — **Open** takes you straight there and starts a 25-minute focus session; hover it to see where it goes (“Open in GitHub”, “Join meeting”, “Open email”). Tasks without a destination keep **Focus**. Coloured chips say why now (red for urgent or late, orange for due within a day, for example “Urgent”, “2 days late”, “~45 min”), the task title is in bold and Paco’s nudge sits underneath. The daily-plan notification offers **Show plan**. With Spanish selected, banner wording is in Spanish. Focus sessions and meetings in progress suppress even urgent reminders. The exception is the reminder for an upcoming meeting: it arrives about 15 minutes before the start with a blue “Starts in 10 min” chip and **Join meeting**, even during task-level focus, flow protection or a focus day (a timed session from the Sessions tab silences these too) — holidays, days off and **Pause reminders** still silence it. **Pause reminders** suppresses all automatic reminders. Explicit previews remain available.

Routine unanswered reminders gradually back off and are capped at eight per task per day. Repeated snoozes also lengthen the interval. Snoozed tasks remain quiet until their chosen time. These are transparent policies, not claims of a fully trained personal behavior model.

## Projects and focus days

In **Settings → Projects & focus days**, add a project for each client or piece of work (“Client A”, “Paco”) with an area (“Consulting”, “Development”, “Marketing”). Task notifications show a short monochrome category label such as `#oles`, alongside the source icon and urgency. Repository owner/path labels stay out of the banner. Tasks can be filtered by project.

Each project has its own persistent local tracker. Open **Tasks → Project trackers** to see active/completed counts, blocked dependencies, urgent and overdue work, deadlines within three days, the next available task, and recent changes. Trackers refresh every 30 seconds while Paco is running and the Mac is awake/unlocked, and refresh on demand when you view them or ask Paco about project status. Connected services keep their own sync intervals; the trackers describe the tasks Paco has actually received, not unobserved work. They do not create additional notification streams or override holidays/focus protection. Project summaries are available to the app chat, task-notification replies, and your private Mattermost bot conversation. Empty projects mean no linked tasks yet, not that a project is finished.

- **Hints** tag work automatically: words, email domains (`@clienta.com`), repository paths (`github.com/clienta/`) or issue-key prefixes (`CLA-`) that only that project's work contains. Specific hints can refine broad overlapping hints; conflicting independent clues remain for review. Your categories take priority over automatic repository buckets.
- **Your model sorts the rest** when it may read your tasks (**My requests and local tasks**, or any local model). It only picks one of your projects or none, and reconsiders automatic assignments when tasks or categories change. Explicit task-level choices stay pinned.
- **Your choice wins.** Change a task's project in **Edit** in Today & workspace; Paco never re-tags it.
- **Focus day.** Choose a project under **Focus day** (Settings, or **Focus day** in Paco's menu) and only that project checks in until the end of today. Tasks you marked urgent still interrupt, and so do upcoming-meeting reminders. The morning plan, call-outs and late-task counts follow the same focus. Choose **All projects** to end it early.

## Paco only works while you're here

Paco rests when nobody is at the Mac: screen locked, display asleep or lid closed (without an external display), another user's session in front, or the Mac asleep. While resting, syncing, reminders, flow checks and call-outs all pause, and nothing queues up to scream at you on return — so Claude or a build running with the lid closed doesn't keep Paco busy. It picks up again within seconds of unlocking. Lid closed with an external monitor counts as present.

## Protect your flow

In **Settings → Protect my flow**, choose your work apps and how long a pause should be before Paco can interrupt (1–5 minutes; default 2). This is opt-in for new installations. When enabled, Paco checks the foreground app and seconds since the last interaction locally, before scheduling and again before displaying queued reminders. It collects no screen images, document text or keystroke values, and no window titles (call-outs, below, are the one opt-in exception: browser titles, used for the decision and never saved), sends no activity to a model, and overwrites a single latest snapshot rather than retaining an activity history. Turning it off deletes that snapshot.

Recent activity in a selected work app defers reminders. Switching between work apps stays protected; briefly visiting another app gets 30 seconds of grace. Long idle periods and the lock screen remain quiet. Explicitly urgent tasks also wait unless you enable the separate interruption option; meetings, manual focus and temporary quiet periods remain protected regardless.

The list starts with common coding, design, document and AI work apps. Edit it to match your tools. Add a browser only if you want activity anywhere in that browser to count as work—Paco does not inspect tabs or decide whether a page is productive. Reading without interaction can look like a pause; choose a longer threshold or start a manual focus session for that work. If the activity signal is unavailable or stale, the existing calendar, quiet-hours and manual-focus rules still apply, and Settings reports the unavailable signal.

## Call me out

In **Settings → Call me out**, Paco can get furious when you're slacking. Before interrupting, the same activity check looks at what you're doing. If you've been on something that's clearly not work for a minute and you're behind, Paco sends a red-rage banner that names it, shows your most overdue task with a roast written by the model, shakes and plays a loud, high-pitched parrot screech. "Behind" means at least the chosen number of late tasks (1, 2, 3 or 5; default 3), or any late task you marked urgent. **On by default**, scream included; turn it off in the same section.

- **Paco decides what counts as slacking.** With **Let Paco decide** on, your configured model judges the activity (app name and, for browsers, the window title) against your late tasks: a coding tutorial for a task you're on is work; Reels are not. It answers distraction, work or unsure, and only "distraction" triggers a call-out. Each distinct activity is judged once and remembered in memory for six hours, and the model is asked at most 30 times an hour — and only when a call-out could actually happen (you're behind, a minute on the same thing, not a work app, nothing protected).
- **Permission.** A hosted model (Claude API, Bedrock, OpenAI, Claude Code, Codex) only receives your activity if you tick **What I'm doing** in the Model section; your late-task titles are included only with **My requests and local tasks**. A local model (Ollama, or your own server on this Mac) needs no permission. Without a usable model, games and a built-in list of common distractions (Instagram, TikTok, YouTube…) still work.
- **Fine-tune (optional).** **Always call out** and **Never call out** take apps or sites and override the model. Your Protect-my-flow work apps are never called out or sent to the model. Games are always called out.
- **Browser titles** are read only while call-outs are on and only with Accessibility permission (**Allow the browser check**). They're used for the decision and never saved; only a hash of the current activity is stored.
- Every protection still wins: meetings, focus sessions, **Pause reminders**, holidays, days off and outside working hours never get a call-out. Idle or locked screens don't count. At most every 15 minutes and 8 times a day. Call-outs name what you were doing, so they're deleted after a day. Untick **Scream** for a silent (still furious) call-out; **Hear the scream** and **Preview a call-out** let you try it.

The screech is an original synthesised sound (`assets/sounds/paco-screech.wav`: four squawks pitched around 2.2–3.6 kHz, 1.7 s, peaking at −1 dBFS and played at full volume; `tools/make_screech.py` regenerates it). Your Mac's volume still applies.

### Separate private model for activity checks

In **Call me out → Model for activity checks**, choose a separate provider without changing the main conversation/meeting model. The activity model has its own consent for app/browser titles and task titles. When a localhost endpoint forwards to a different computer, enable **This localhost address forwards to another computer** so Paco still requires that consent. Disable the JSON response-format option for servers that only support JSON through prompting.

Nathalia's installed setup uses the existing **Qwen3.6-35B-A3B** model through Colibri on `ubuntu@ovh`, served as `tello-dev-qwen`. The main model remains Codex CLI. Colibri binds only to the server's loopback interface; the Mac connects over an encrypted SSH tunnel at `http://127.0.0.1:18766/v1`. Both services start automatically. The model receives the current app/browser title and permitted late-task titles for a decision. Raw titles are not saved by Paco or company sync; Colibri prompt debugging is disabled. This is title-based classification, not screenshot understanding.

The CPU model took about 11 seconds per warm classification in validation. While it thinks, Paco keeps checking whether the situation changed: switching back to work, locking the screen, entering quiet time, or losing the activity signal cancels the call-out. A cached verdict is reconsidered when task context or model configuration changes. Model uncertainty produces no model-triggered call-out. Normal flow protection remains based on your selected work apps and recent input.

Operations:

```sh
ssh ubuntu@ovh 'systemctl --user status paco-colibri.service'
launchctl print gui/$(id -u)/com.paco.ovh-model-tunnel
curl http://127.0.0.1:18766/health
```

The server unit template is `tools/paco-colibri.service`; the installed tunnel is `~/Library/LaunchAgents/com.paco.ovh-model-tunnel.plist`. The server has no public model port. Settings can switch this activity provider later without moving your company task database.

## Reply directly to Paco

Every native notification has **Reply**. The bubble expands only while you talk, keeps its original character size, and stays open while you type or wait for an answer. Press Return or Send. **Talk to Paco…** in the menu reopens the latest real notification and its last answer after dismissal or restart.

- “Remember me in 5 hrs I will be out” postpones that task and holds all reminders during the temporary absence. Reminders resume when your working hours and focus/meeting rules allow; this is not an alarm guaranteed to fire outside working hours.
- “That is super important” explicitly marks this task urgent. “That is not urgent” removes the exception.
- “That is done” completes the task in Paco. This does not write completion back to an external tracker.
- “That is what Juan did” records context and asks whether this task is complete. It does not silently close or reassign it. “Yes he did” answers that follow-up; “Juan completed this” is explicit completion with attribution.
- “Help me focus for 45 minutes” protects a focus session. “I'm out for 2 hours” and “I'm back” manage temporary quiet time without changing holiday settings.
- “Bother me less” remembers a slower cadence. “Check in more often” speeds it up within existing quiet periods and daily limits. “What have you learned” explains this feedback; “reset my reminder preferences” resets frequency.

These direct instructions work locally without an API key. Other phrasing and planning questions use your configured model and require **My requests and local tasks** consent for hosted processing. The model sees the current notification/task, recent replies in that conversation, and accepted feedback. Model-interpreted changes are displayed before execution: choose **Apply**, reply “yes”, or cancel. Suggestions expire after ten minutes and reject changed tasks. Failed requests retain your typed reply; retrying does not apply the same instruction twice.

Replies, task context and explicit frequency preferences persist locally. Paco already backs off after repeated snoozes and checks reminder eligibility every 30 seconds, while sources sync about every five minutes. This is adaptive reminder policy and conversational context, not model training or continuous cloud surveillance. A model is called when you ask for broader interpretation or advice.

## Model: local, your own server, or your subscription

In **Settings → Model**, choose where Paco thinks, then **Test connection** — it sends a tiny ping and tells you exactly what went wrong (missing key, wrong model ID, server not running, CLI not signed in).

| Choice | What you enter | Where data goes |
| --- | --- | --- |
| **Ollama** | Installed model name, e.g. `qwen3:8b` | Stays on this Mac |
| **My own server** | OpenAI-compatible URL (LM Studio `http://localhost:1234/v1`, llama.cpp, vLLM, or `https://…` on your server), model, optional key | Stays on this Mac for `localhost`; otherwise your server |
| **Claude Code** | Nothing (optional model alias) — uses your signed-in `claude` CLI and subscription | Anthropic |
| **Codex CLI** | Nothing (optional model) — uses your signed-in `codex` CLI | OpenAI |
| **Claude API** | Model ID and API key | Anthropic |
| **AWS Bedrock** | Model or inference-profile ID, region, Bedrock API key | Your AWS account |
| **OpenAI API** | Model ID and API key | OpenAI |

Keys are stored with macOS Keychain through `keyring`, not in the database, prompts, or source config. Both CLIs run in an empty temporary folder and only answer the question: Claude Code with no tools and a single turn, Codex in its read-only sandbox. Bedrock uses a Bedrock API key (bearer token); IAM access keys/SigV4 profiles aren't supported yet.

For anything that leaves the Mac, tick what the model may read: **My requests and local tasks**, **Gmail excerpts**, **Meeting text**, **What I'm doing**. Local models get everything they need without ticking. Without any model, local tasks, planning, notifications, project hints, links and preferences still work; Gmail task extraction, call-out judging and model project tagging don't.

An API key or CLI supplies model inference. It does **not** import Claude.ai chats, connector permissions, or other apps. The workspace (**Today & workspace…** in Paco's menu, or **More of Paco** at the bottom of Settings) has your plan, commitments, follow-ups, routines, memory search and the **Talk** screen, which uses the configured model for advice and reviewable planning changes.

For execution, connect **Claude Code** or **Codex CLI** to an explicitly trusted Git repository in Settings. These use the locally installed agent's existing authentication and configured tools. In the advanced workspace, prepare a request in **Talk**, review the brief, then approve it. Paco creates a separate Git worktree from the displayed commit, records the provider session, and supports follow-ups and cancellation. Uncommitted work in the original repository is not copied. Claude Code runs in its default permission mode: an action that needs approval is denied, reported in session events, and the session ends as blocked. Codex runs non-interactively (`approval_policy=never`) inside its `workspace-write` sandbox: it does not ask before running commands, but it can only write within the session's worktree and temporary folders. Paco never passes flags that disable either provider's sandbox or permission checks. A blocked session is not silently retried.

Use macOS Dictation in the message field to speak and review the transcript before sending. Dictation is handled by macOS; Paco itself captures audio only during meeting notes you start explicitly (see [Meeting notes](#meeting-notes-macos)).

## Connections and memory

- GitHub: sign in with `gh auth login`, then connect in Settings. Assigned issues and requested PR reviews are separate sources.
- Google: follow [CONNECT.md](CONNECT.md) with your Desktop OAuth client.
- In **Settings → Connect another account** (tokens saved in Keychain): **GitLab** (assigned issues and merge requests awaiting your review; gitlab.com or your own instance), **Linear**, **Jira**, **Asana**, **Todoist**, **Microsoft To Do**, **Outlook** (flagged emails), **Outlook Calendar** (meetings, busy time, Teams links) and **Slack** (DMs and mentions as evidence). These are tested against recorded API responses, not live accounts. Microsoft and Jira OAuth tokens need reconnecting when they expire.
- **What you did.** When something disappears from a tracker (GitHub, GitLab, Linear, Jira, Asana, Todoist, Microsoft To Do, Google Tasks, Apple Reminders), Paco stops reminding you and asks in the workspace whether you finished it, instead of silently marking it done. Paco doesn't write completion back to trackers.
- Apple Calendar / Reminders: connect in Settings and grant the corresponding macOS permission yourself. Calendar access is read-only for Apple events.
- Import a meeting transcript as JSON in **Memory & meetings**. See `examples/meeting.json`. Search by words, person or project. A model can propose quoted decisions and assignments; you confirm ownership before creating a task. Link a quote to an existing task to reconcile sources without guessing.
- Tasks with a web source show a link such as **Open in GitHub** or **Open email** in Today & workspace, and **Open** in their banner. Paco only opens web links, its own meeting notes, and Apple Calendar/Reminders — never other URL schemes.
- Desktop text capture is off by default. Enable particular apps and Accessibility permission explicitly. Browsers, terminals, AI chats and password managers are excluded. Text is redacted locally and retained for seven days. No screenshots are captured.

The full backlog is **not finished**. [ISSUE-STATUS.md](ISSUE-STATUS.md) distinguishes implemented paths, tested behavior, and missing acceptance criteria. In particular, model quality, live account integration, live agent execution, sleep/wake, and login-startup acceptance have not been certified.

## Login startup

The setup checkbox registers this checkout to run at the next login. Keep its drive and Python environment available. Closing settings leaves Paco running; **Quit Paco** stops it until the next launch or login. Uncheck the option and save settings to disable future login launches.

Alternatively, install a copy of the current version into Application Support:

```sh
.venv/bin/python paco.py install
```

This installs the real native app bundle, including its Finder icon, into `/Applications/Paco.app` (or your personal Applications folder when the shared folder is not writable). Its private runtime, data, assets and virtual environment live in `~/Library/Application Support/Paco`; the installed app does not need the development checkout or external drive. Keep that private runtime available. The installer starts the desktop service and configures login startup. Re-run after updating Paco. Quit any development copy using the same database before installing.

To stop login startup:

```sh
launchctl bootout gui/$(id -u)/com.paco.reminders
rm ~/Library/LaunchAgents/com.paco.reminders.plist
```

## Checks

```sh
.venv/bin/python paco.py doctor
.venv/bin/python -m unittest discover -v
.venv/bin/python eval_workweek.py
node --check web/app.js
node --check web/setup.js
```

Background problems are logged by error type and code location only, never task or message content: to the terminal when started with `run-paco.command`, or to `service.log` beside the database under login startup. While a background loop (sync, reminders, flow protection or desktop capture) keeps failing, Settings lists it under source status, for example “Paco reminders: … — retrying automatically”; the entry disappears once it recovers.

`eval_workweek.py` exercises deterministic reminder policy, not model judgment. `eval_mail.py` uses synthetic mail with your configured model and may incur API charges; it was not run without a configured key.

## Meeting notes (macOS)

Open **Paco → Meeting notes**. The first version uses local multilingual Whisper
for speech recognition and a separately configured model for interpreting meetings.
The app's minimum version is macOS 14.2; the current development build was checked
on an Apple Silicon Mac running macOS 26.6.1, not across all supported hardware.

1. Install the optional speech dependencies with
   `.venv/bin/python -m pip install -r requirements-meetings.txt`.
2. In Meeting notes, choose **Prepare local speech recognition**. This downloads
   the Whisper small model once (approximately 500 MB). Subsequent transcription
   uses local model files, including when offline. The development machine already
   has these dependencies and model files installed.
3. In **My meeting preferences**, set your name, language, transcript retention
   (14 days by default), and preferred summary format. Save different formats for
   meeting types such as planning, client or one-to-one.
4. Choose a summary model: inherit Paco's main model, Claude, OpenAI, local Ollama,
   or your own OpenAI-compatible HTTPS server (base URL ending in `/v1`). Hosted
   and private-server inference requires explicit permission to send meeting text.
   Keys go into Keychain. An API key does not inherit another app's integrations.
5. Choose **Paco → Start meeting notes…**, name the meeting, then select microphone
   plus call audio or microphone only. macOS may request Microphone and Screen &
   System Audio Recording permission. Only audio callbacks are registered; Paco
   does not collect meeting screen images. System mode currently includes all
   system audio except Paco. Use headphones and avoid other audio during calls.
6. The menu-bar dot indicates capture. Pause/resume or finish there. Capture stops
   on sleep or a reported device/stream failure. Queued audio is transcribed before
   analysis starts. Ordinary Paco reminders stay quiet during capture.
7. Review the summary and suggested actions. “Why Paco thinks this” shows the
   supporting turns while the transcript exists. Correct speakers or action owners
   when needed. Only explicitly accepted personal actions enter the plan; conditional
   actions start blocked until their dependency is resolved. Other people's work
   stays in the meeting notes. Reassigning an accepted action away from yourself
   archives its personal reminder. Use “Reformat existing notes” to change a saved
   summary, including after transcript expiration.

Interpretation uses extraction followed by a conversation-wide reconciliation pass
and a separate formatting pass. It considers indirect acceptance, conditions,
retractions, handoffs, completed work and ambiguity. Citations must match actual
transcript segments. Confidence is a model judgment, not a calibrated probability.
A claim having a valid quote does not prove its interpretation is correct; review
important commitments. Calendar attendees and optional call-app speaking signals can now label remote turns.
Calendar-only names remain tentative. Microphone-only meetings use “In-room participants”
because a shared microphone does not identify an individual. See the speaker setup below.

Audio travels through bounded RAM buffers over authenticated loopback HTTP into
local speech recognition. There are no application audio files, playback, audio
exports, or audio uploads. Overload discards audio and marks a gap. This does not
make a forensic guarantee about macOS paging or crash handling. Transcript expiry
is enforced on access, startup and periodically; SQLite secure deletion is enabled.
Local data is owner-readable only and relies on the Mac's disk protections (such
as FileVault), not application-level database encryption. External backups and
copies already shared elsewhere are outside Paco's deletion control; restored
transcripts are checked against their original expiry before app retrieval.

Summaries, user edits and reviewed actions survive transcript expiry. Quotes are
not duplicated in the durable action records. Deleting an entire meeting removes
its notes and action context, while tasks explicitly added to your plan remain.
Sharing currently means reviewing and copying a summary; automatic attendee
lookup and approved sending through external channels are not implemented.

For a transcript-only trial, import `examples/meeting-context.json` from Meeting
notes. It includes an indirect offer, acceptance, a later handoff, an unmet condition,
a suggestion that is not agreed work, and already-completed work. Run the optional
live reasoning regression check with `.venv/bin/python eval_meetings.py` after
configuring a summary model. It uses synthetic conversations and a disposable DB.
The deterministic tests use model fixtures; they do not measure live model accuracy.


## Calendar context and speaker names

Start meeting notes from Paco's menu. The start dialog lists calendar events near
now and suggests an event only when exactly one is currently in progress. Select
another event or “No calendar event” when necessary. Apple and Google sync now
retain attendee names, emails, current-user markers and response status. Calendar
access must already be connected; existing accounts pick up attendee data on their
next successful sync. Declined invitations and room/resource entries are excluded
from candidate people. Legacy email-only calendar rows remain compatible.

In a linked one-to-one call, a fresh invite with one identified self participant
and one other participant provides a **tentative calendar name**. A group invite
never maps voices by list order. Observed call rosters suppress that fallback when
speaker timing is missing. The review UI exposes the name's source, uncertainty,
and explanation; user corrections override it. Model action extraction receives
this context and cannot upgrade an invite-only speaker guess to a confident
implicit commitment.

**Zoom on macOS (experimental adapter):** enable “Identify Zoom speakers” in
Meeting preferences, use “Enable macOS speaker access…” to request Accessibility
permission, and save preferences. When starting capture, choose **Zoom audio only**.
This limits system audio capture to Zoom, so another app's audio is not attributed
to a Zoom participant. A linked Zoom URL preselects this audio source. The adapter
polls only Zoom's participant-tile Accessibility labels during capture, reads no
text-field/chat values or screenshots, and stops on pause/finish. Its initial parser
recognizes a narrow English tile-label grammar. Missing permission, unsupported
Zoom labels, duplicate display names and overlapping active speakers leave turns
unnamed. The parser is tested with synthetic labels; its live macOS Zoom interface
coverage still needs verification with granted permissions. Do not treat parser
fixtures as proof of compatibility with every Zoom version.

**Google Meet in Chrome (optional development extension):** load the repository's
`extensions/meet-speakers` folder using Chrome → Extensions → Developer mode →
Load unpacked. Start Paco capture, open Meeting preferences, and choose **Create
Meet connection code**. On the selected Meet call tab, open the extension popup and
paste the code. This version pairs per meeting; smoother persistent pairing remains
future work. A pairing can write speaker metadata only, cannot read tasks or call
models, is bound to one active meeting and call URL, expires after four hours or
when the meeting ends, and can be revoked with **Disconnect Meet**. The extension
keeps its token in session memory, injects only after the user connects the active
Meet tab, and sends names/active-speaker markers to authenticated loopback HTTP.
It does not capture audio, captions, screenshots or chat. Unsupported Meet markup
reports unavailable instead of inferring a speaker from a selected or pinned tile.
Avoid other system audio during Meet capture. The unpacked extension is provided
but has not been installed or tested in a real Meet call on this machine.

Local Whisper word timestamps align words with the call-app timeline. Stable turns
are grouped by speaker; a boundary guard keeps uncertain handoff words unnamed.
Speaker sample timelines and per-segment identity metadata expire with the
transcript. Summaries/action citations retain names, timestamps and their source;
calendar attendee context remains with the meeting until it is deleted. No voice
profile or audio recording is stored.

References informing the adapters:
[Notion's Zoom behavior](https://www.notion.com/help/get-speaker-labels-in-zoom-calls),
[Apple EventKit participant fields](https://developer.apple.com/documentation/eventkit/ekparticipant/url),
[community Zoom tile-label observations on Windows](https://github.com/bidheyakthapa/meet-speaker-detector),
and [a Meet DOM speaker-indicator reference](https://github.com/afreediz/MeetCheat).
These describe integration approaches; they do not establish live compatibility of
Paco's adapters. Native label fixtures can be run by compiling
`native/MeetingSpeakers.m` with `native/MeetingSpeakersTests.m`, linking Cocoa and
ApplicationServices. Python identity/bridge tests run with
`.venv/bin/python -m unittest test_meeting_identity`.

## Installed laptop build and automatic catalog

`python paco.py install` prepares a separate Python environment and app under
`~/Library/Application Support/Paco`, adds `~/Applications/Paco.app`, and enables
login startup. The external checkout is no longer needed to run the installed
copy. After editing source code, install again to update that copy. Finish any
meeting capture before updating.

Paco now creates project catalog entries from explicit repository/tracker groups
as connected tasks arrive. It uses bounded word/domain hints, source groups and
manual corrections; conflicting clues stay unassigned. A correction teaches other
tasks in the same repository or issue project, while conflicting corrections keep
that source ambiguous. “No project” is also a durable manual choice. Deleting an
automatically discovered project prevents that source from recreating it.

With task-model permission, the model receives task titles, goals, source groups,
project definitions and examples of corrections. High-confidence matches may be
assigned automatically; uncertain matches appear as suggestions with a reason.
The model can infer an area for automatically discovered projects from their task
examples. User-specified areas remain authoritative. Task edits, new clues and
catalog changes cause automatic tags to be reconsidered. The workspace filters
by both project and area. Hover a project chip to see why Paco chose it.

Meeting notes can also be started and finished directly from their native window.
The `--capture permissions` diagnostic on the native executable reports existing
microphone, screen/audio and Accessibility grants without requesting new ones.

For a long list or project brief, choose **Add tasks from text…** in the parrot menu. Review Paco's proposed tasks, owners, projects and dependencies before applying. Connect your internal account under **Company task account** in Settings to sync tasks with ChatGPT. See [COMPANY.md](COMPANY.md) for connection and storage details.

### Quieter tasks and project brains

The default Tasks view and reminders include accepted work assigned to you. Imported
conversation requests wait in **To review** until you accept them; an explicit promise
in your own sent message may be accepted automatically. Calendar events provide context
without automatically creating a preparation obligation. Exact duplicates with matching
project, owner and deadline link to one task while retaining their source evidence.
Use the status filter to inspect suggestions, reference items, other responsibilities,
dismissed items and duplicate links. Nothing is deleted by this migration.

Open **Tasks → Project trackers → Edit project brain** to set a project's goal,
milestone, scope, roles, stakeholders, decisions and source links. **New project** creates
a shared brief. Use each person's username or email; add their other account identities
as aliases. Roles distinguish execution, management, review, decisions and staying
informed. A management role does not automatically assign you your colleagues' execution
work. An explicit personal task or accepted suggestion can establish your own commitment.

Briefs are shared with signed-in company members. Any member can create/edit them in this
internal version; role labels are not permissions. Saves require the company service and
use revisions: if someone changed the brief, refresh it and reapply your draft. Paco keeps
the draft on failed saves. Private task lists, raw source conversations, meeting transcripts
and activity history are not shared through a project brief. Trackers show the tasks known
to this Mac, not a complete view of every colleague's private work. While the Mac is awake,
Paco refreshes project facts and uses the briefs in task extraction, classification and chat.

### Talking to Paco in Mattermost groups and channels

Add **@paco** as a member of the group or channel, then mention him explicitly, for
example `@paco resume este hilo y separa las responsabilidades de cada persona`.
Paco sends a normal message in that chat, rather than nesting his reply in a thread.
Mention him again for follow-ups; ordinary messages,
quoted mentions and other bots do not trigger replies. Both Paco and the connected
owner must belong to the conversation. Paco does not automatically join channels.

Shared replies use only the current thread, never your private task list, DM history,
project briefs, email or activity. Participants can ask questions, plan and summarize
what was discussed. The connected owner can also explicitly ask to add a new personal
task or reminder. Existing private-task updates and private-account questions stay in
the owner's direct message with Paco; other participants cannot modify that account.

Controls → Sources → Mattermost has **Reply to @paco in groups and channels**.
Like private replies, it runs while this Mac is awake and unlocked. An authenticated
Mattermost WebSocket wakes the reply worker on your DM or an explicit shared @paco mention.
Events only trigger a check: the worker fetches and validates the message and channel
before reasoning or replying. A 30-second fallback check and reconnect catch-up recover
missed events. Typing, ordinary channel chatter and Paco's own messages do not trigger replies.
The connection reconnects automatically and closes when you disable the bot or lock the Mac.
Codex-backed chat and Mattermost replies use low
reasoning effort; meeting analysis and other background reasoning keep their existing settings.
No new server service or administrator bot privileges are required.
Delivery receipts prevent replaying replies or creating tasks twice after an uncertain
network response. An uncertain send is reconciled against bot-authored receipts, never
blindly retried. Shared conversation text is fetched for the reply, not copied into the
company database. The local queue retains the answer and delivery metadata.

### Focus sessions, breaks and your tree

Sessions has a focus timer and a tree for the last seven days. Each timer that finishes
its planned focus time earns one parrot; ending early does not. The counters show completed
sessions and their focus minutes. These are completed timers, not an AI judgment that the
work was successful. Older sessions fall out of the rolling seven-day window. A larger
flock grows onto additional trees you can scroll through.

Choose **Add a break after focusing** for a Pomodoro-style focus/rest cycle. You can also
choose **Take a break** during a session: Paco saves the remaining focus time and keeps
reminders quiet. When that break ends, the focus timer waits for **Resume focus**, so time
doesn't run out while you are away. A completed session's final break ends on its own;
start the next focus session when ready. Pauses and remaining time survive an app restart.

Meetings shows up to 12 current/upcoming events from connected calendars over the next
seven days. The cloud icon is green when company sync is current with no pending changes
or conflicts, and red otherwise; hover it for the reason. Interface labels do not select
accidentally; inputs, chat replies, task titles and meeting notes remain copyable.
