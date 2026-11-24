# Discover tasks on macOS

Use a persistent Python virtual environment. For Google, install the OAuth client and macOS Keychain support into the same interpreter used to install the login service:

```sh
python3 -m venv ~/.paco-venv
source ~/.paco-venv/bin/activate
python -m pip install google-auth-oauthlib keyring requests
```

For GitHub, install GitHub CLI, run `gh auth login`, then `python paco.py connect github`. Paco reads open issues assigned to that login across accessible repositories.

For Google, enable Gmail, Calendar and Tasks APIs in one Google Cloud project. Create a Desktop OAuth client, download its JSON, and authorize the desired account:

```sh
python paco.py connect google --client ~/Downloads/client_secret.json
python paco.py connect model ollama YOUR_INSTALLED_MODEL
python paco.py sync
python paco.py list
python paco.py install
```

Connect either provider independently. Re-run install to update an older service. The service polls every five minutes. It discovers open Google Tasks and upcoming timed primary-calendar meetings. Gmail starts with incoming and outgoing threads active in the last seven days, then follows mailbox history using a durable cursor and queue, without a phrase filter. It analyzes up to four changed threads per cycle, using up to twelve recent messages and 4,500 characters of body text per message. Attachments are excluded. A later reply can resolve an existing task when the model identifies supporting text. Check inferred tasks: a valid quotation does not guarantee the model understood it.

Start Ollama and install a chat model that supports JSON output before selecting the local option. Alternatively run `python paco.py connect model openai YOUR_MODEL --allow-cloud-mail` and enter the API key at the hidden prompt. This explicitly permits sending thread excerpts, sender and recipient details, and existing same-thread tasks to OpenAI. Credentials are stored through keyring. Re-run install after updating the checkout. Reminders continue independently while the sync worker waits for a model.

To check a configured model's judgment on synthetic conversations, run `python eval_mail.py`. No personal email is used in this evaluation.

## Planning and desktop controls

Run `python paco.py desktop` with a Python installation that includes Tk. Closing the window leaves the installed service running. You can start a focus session, snooze, block, resume or complete the selected task. Use `python paco.py plan` to see eligible tasks and their ranking. Meeting and focus protection apply to notifications as well as the plan. Demo configuration:

```sh
python paco.py set hours 9-18
python paco.py set goal "Paid mining pilot"
python paco.py estimate 1 45 --goal "Paid mining pilot" --deadline 2027-01-08T17:00
python paco.py set language es
python paco.py set voice on
python paco.py review
```

Review summarizes seven days of recorded actions. Two snoozes of the same task prompt Paco to suggest a five-minute first step. Estimated tasks must fit before the next known timed meeting. Unestimated tasks remain eligible.

## Project sources and actions

Enable the Drive API and reconnect Google to authorize metadata access. Run `python paco.py activity` for recent Drive files and the latest commit in each explicitly tracked repo. Add a repo with `python paco.py track /absolute/path/to/repo`. For assigned Linear issues, install requests and keyring in the service environment and run `python paco.py connect linear`. Enter a personal read-only API key at the prompt.

For an assigned GitHub issue, `python paco.py draft-comment TASK_ID "text"` saves a local draft. Use `python paco.py publish DRAFT_ID` to review the target and text and explicitly approve posting. An uncertain delivery is checked for its receipt before another attempt. Read-only GitHub credentials can still be used for discovery.

Inspect the source and stored supporting quotes with `python paco.py evidence TASK_ID`.

Use `python paco.py depends TASK PREREQUISITE` to withhold a task until its prerequisite is complete. Both IDs must already exist. Paco rejects cycles. Remove a dependency with `python paco.py unlink TASK PREREQUISITE`.
