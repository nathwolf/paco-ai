# Run Paco on your Mac

With Python 3.8 or newer, run these commands from the repository checkout:

```sh
python3 paco.py add "Finish the proposal scope" --priority 5
python3 paco.py install
python3 paco.py list
```

The installer copies the script into your user Application Support directory and registers a login service. Keep the Python interpreter used for installation available. Allow Script Editor notifications in macOS settings if prompted. Re-run install after updating Paco.

Use the ID printed by add in place of 1 below:

```sh
python3 paco.py start 1 25
python3 paco.py snooze 1 10
python3 paco.py block 1
python3 paco.py resume 1
python3 paco.py done 1
```

The service selects one eligible task per minute, highest priority first. An unanswered task becomes eligible again after 15 minutes. Focus and snooze delay that task. Block suspends it until resumed. Commands operate on local SQLite state. This version uses manual tasks and fixed reminder wording. It can deliver at any hour while the Mac is awake. A crash between notification delivery and database commit may repeat one alert.

To disable startup and stop the service, run:

```sh
launchctl bootout gui/$(id -u)/com.paco.reminders
rm ~/Library/LaunchAgents/com.paco.reminders.plist
```

Run the offline lifecycle test with `python3 -m unittest test_paco`.
