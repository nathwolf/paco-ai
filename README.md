# paco-ai

**A project tracker for those who need a little pressure to keep going.**

Paco is a local AI assistant that connects to your project management tools, calendars, emails, and messaging apps to figure out what you're supposed to be doing, how things are progressing, and whether you're actually getting things done.

Instead of waiting for you to check your to-do list, Paco checks on you.

It remembers your commitments, follows up on unfinished tasks, asks uncomfortable questions, and gives you that little push you sometimes need.

## The idea

Most productivity tools help you organize your work. Paco wants to make sure you actually do it.

- **Stay informed.** Understand your projects and commitments across different tools.
- **Check in.** Ask how things are going, what's blocking you, and what you've accomplished.
- **Follow up.** Remember what you promised to do and bring it up again.
- **Keep you accountable.** A little pressure, a little persistence, and no pretending that ignored tasks have disappeared.

Local-first. Your projects, conversations, and commitments should remain under your control.

The goal isn't another productivity dashboard. It's an assistant that notices when you're falling behind and actually says something about it.


## Install the internal pilot

Download the [Mac pilot installer](https://github.com/nathwolf/paco-ai/releases/tag/v0.6.2-pilot). See [TEAM-SETUP.md](TEAM-SETUP.md) for colleague setup, ChatGPT connection, and account creation. Company endpoint: `https://paco.optimai.cl/mcp`. Accounts currently have separate task catalogs; shared team projects are not implemented.

## Try the companion

Paco now lives in the Mac menu bar with a simple monochrome parrot icon. Set up connections once, then let it sync and check in through compact top-right notifications. All five original expressions are supported, with warm cream-to-peach colors, holiday and focus protection, Claude API configuration, and local Claude Code/Codex session bridges. Settings stay closed after setup; login startup is available there. Reply directly to notifications to postpone, mark urgency or completion, explain context, protect focus, and teach Paco a better check-in frequency. Broader conversation uses the configured model, with review before model-interpreted changes.

Open `run-paco.command` from this checkout. See [QUICKSTART.md](QUICKSTART.md) for setup and [CONNECT.md](CONNECT.md) for account connections. The current implementation is a trial build; [ISSUE-STATUS.md](ISSUE-STATUS.md) records the remaining acceptance criteria across the open backlog.

Meeting notes now have a macOS capture path, local in-memory speech recognition,
14-day transcript expiry, personal summary formats and evidence-backed action review.
See [meeting setup and current limitations](QUICKSTART.md#meeting-notes-macos).

### Company task account and bulk planning

Paco 0.5 can turn a pasted brief into a reviewed task plan and sync structured tasks to a small internal company service. The same account is available through an authenticated remote MCP for ChatGPT. Meeting transcripts and activity do not enter that task store. See [company setup, privacy boundary, and administration](COMPANY.md).
