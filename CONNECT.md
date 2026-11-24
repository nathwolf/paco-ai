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

Connect either provider independently. Re-run install to update an older service. The service polls every five minutes. It discovers open Google Tasks and upcoming timed primary-calendar meetings. Gmail discovery reads incoming and outgoing threads active in the last seven days, with no phrase filter. It analyzes up to four changed threads per cycle, using up to twelve recent messages and 4,500 characters of body text per message. Attachments are excluded. A later reply can resolve an existing task when the model identifies supporting text. Check inferred tasks: a valid quotation does not guarantee the model understood it.

Start Ollama and install a chat model that supports JSON output before selecting the local option. Alternatively run `python paco.py connect model openai YOUR_MODEL --allow-cloud-mail` and enter the API key at the hidden prompt. This explicitly permits sending thread excerpts, sender and recipient details, and existing same-thread tasks to OpenAI. Credentials are stored through keyring. Re-run install after updating the checkout. Reminders continue independently while the sync worker waits for a model.

To check a configured model's judgment on synthetic conversations, run `python eval_mail.py`. No personal email is used in this evaluation.
