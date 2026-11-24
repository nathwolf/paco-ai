# Product requirements

Paco should be able to manage a working day while the interface is closed. The user sets goals and working hours, selects sources and can correct any inferred commitment.

| Capability | Observable behavior |
| --- | --- |
| Awareness | A new assignment, changed meeting or sent reply reaches the local record with a source link and last-sync time. |
| Memory | Remember who owes the next move, why a task exists, what changed and which fields the user corrected. |
| Planning | Recommend a concrete next action that fits the available time. Explain which goal, deadline or dependency gives it priority. Replan on material changes. |
| Accountability | Repeat an unanswered reminder during working hours. Escalate from a prompt to playful irritation, then offer a smaller first step. Keep escalation state across restarts. |
| Learning | Compare estimated and observed duration, starts after reminders, repeated snoozes and common blockers. Show the evidence for a proposed preference and let the user correct it. |
| Execution | Automatically maintain local tasks. Draft external actions, display proposed changes for approval and record verified outcomes. |

## Notification behavior

Start protects a focus interval. Snooze sets a specific next eligible time. Blocked records a reason, next owner and follow-up date. Done closes the task and cancels pending reminders. Ignoring a delivered prompt schedules another within configurable cadence and daily limits. Meetings, quiet hours and active focus defer interruptions. Deliver a fresh recommendation after wake. Users can adjust persistence, language, voice and tone separately. Report unknown activity as unknown.

## Evaluation

Replay synthetic working weeks with labeled commitments, contradictory evidence, reassignment and changing deadlines. Measure extraction precision and recall, duplicate tasks, false closures, actionable recommendations, starts following reminders, sync lag and API cost. Compare reminder variants within comparable tasks. Track dismissed and mistimed alerts alongside starts.
