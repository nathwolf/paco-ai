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
python paco.py sync
python paco.py list
python paco.py install
```

Connect either provider independently. Re-run install to update an older service. The service polls every five minutes. It discovers open Google Tasks, upcoming timed primary-calendar meetings and possible first-person commitments in recent sent Gmail snippets. Mail matches are review prompts; quoted text can match, and commitments outside snippets can be missed. Meeting reminders start fifteen minutes before the meeting and expire on the first successful sync after it begins. Superseded assignments disappear from the active queue after successful sync. Manual tasks remain available. Google authorization currently supports one account per installation; use a separate installation/database when switching identities. All extraction runs locally.
