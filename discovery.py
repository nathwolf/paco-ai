"""Read-only sources feeding Paco's local reminders."""
import argparse
import json
import projects
import mail_reasoning
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path.home() / "Library/Application Support/Paco"
CONFIG = ROOT / "sources.json"
SCOPES = ["https://www.googleapis.com/auth/" + name for name in
          ("gmail.readonly", "calendar.events.readonly", "tasks.readonly", "drive.metadata.readonly")]
def configure(args):
    if args[:1] == ["model"]:
        settings = mail_reasoning.configure(args[1:])
        ROOT.mkdir(parents=True, exist_ok=True)
        config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
        config["model"] = settings
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(config))
        tmp.replace(CONFIG)
        return
    parser = argparse.ArgumentParser(prog="paco connect")
    parser.add_argument("source", choices=["github", "google", "linear"])
    parser.add_argument("--client", type=Path)
    opt = parser.parse_args(args)
    ROOT.mkdir(parents=True, exist_ok=True)
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    if opt.source == "linear":
        import keyring
        from getpass import getpass
        token = getpass("Linear read-only personal API key: ").strip()
        if not token:
            parser.error("missing Linear key")
        keyring.set_password("paco.linear", "personal", token)
        config["linear"] = True
    elif opt.source == "github":
        exe = shutil.which("gh")
        if not exe:
            parser.error("install GitHub CLI and run gh auth login first")
        login = subprocess.check_output([exe, "api", "user", "--jq", ".login"], text=True).strip()
        config["github"] = [exe, login]
    else:
        import keyring
        from google_auth_oauthlib.flow import InstalledAppFlow
        if not opt.client:
            parser.error("provide --client with your Google Desktop OAuth client JSON")
        flow = InstalledAppFlow.from_client_secrets_file(str(opt.client), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")
        keyring.set_password("paco.google", "oauth", creds.to_json())
        config["google"] = True
    tmp = CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(config))
    tmp.replace(CONFIG)


def github(settings, now):
    exe, account = settings
    def api(*args):
        return subprocess.check_output([exe, "api", *args], text=True, timeout=60)
    if api("user", "--jq", ".login").strip() != account:
        raise ValueError("GitHub account changed; reconnect it")
    rows = api("--paginate", "issues?filter=assigned&state=open&per_page=100", "--jq",
               '.[] | [.html_url,.title] | @json')
    for line in rows.splitlines():
        url, title = json.loads(line)
        yield url, title, now


def google_session():
    import keyring
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    raw = keyring.get_password("paco.google", "oauth")
    if not raw:
        raise ValueError("reconnect Google")
    return AuthorizedSession(Credentials.from_authorized_user_info(json.loads(raw)))


def google_rows(source, now, intervals=None):
    with google_session() as session:
        def get(url, params):
            response = session.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        def pages(url, field, **params):
            while True:
                data = get(url, params)
                yield from data.get(field, [])
                if not data.get("nextPageToken"):
                    break
                params["pageToken"] = data["nextPageToken"]
        if source == "tasks":
            root = "https://tasks.googleapis.com/tasks/v1/"
            for group in pages(root + "users/@me/lists", "items"):
                prefix = root + "lists/" + quote(group["id"], safe="") + "/tasks"
                for task in pages(prefix, "items", showCompleted="false"):
                    yield task["selfLink"], task["title"], now
        elif source == "calendar":
            stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
            url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
            for event in pages(url, "items", singleEvents="true", timeMin=stamp(now),
                               timeMax=stamp(now + 86400)):
                start = event.get("start", {}).get("dateTime")
                declined = any(a.get("self") and a.get("responseStatus") == "declined"
                               for a in event.get("attendees", []))
                if start and not declined and event.get("status") != "cancelled":
                    begins = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
                    ends = event.get("end", {}).get("dateTime")
                    if intervals is not None and ends and event.get("transparency") != "transparent":
                        intervals.append((begins, datetime.fromisoformat(ends.replace("Z", "+00:00")).timestamp()))
                    if begins > now:
                        yield event["id"], "Prepare for " + event.get("summary", "meeting"), begins - 900

def reconcile(db, source, rows, now):
    # Fetch the entire snapshot successfully before expiring any previous entries.
    rows = list(rows)
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS discovered (
            source TEXT, key TEXT, task_id INTEGER, scheduled REAL,
            PRIMARY KEY(source,key))""")
        previous = {r[0]: r[1:] for r in db.execute(
            "SELECT key,task_id,scheduled FROM discovered WHERE source=?", (source,))}
        for key, title, due in rows:
            old = previous.pop(key, None)
            if old:
                task_id, scheduled = old
                db.execute("UPDATE task SET title=? WHERE id=?", (title, task_id))
                if source == "calendar" and due != scheduled:
                    db.execute("UPDATE task SET due=? WHERE id=? AND state='open'", (due, task_id))
                    db.execute("UPDATE discovered SET scheduled=? WHERE task_id=?", (due, task_id))
            else:
                cursor = db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)",
                                    (title, due))
                db.execute("INSERT INTO discovered VALUES(?,?,?,?)", (source, key, cursor.lastrowid, due))
        if source != "gmail":
            for key, (task_id, _) in previous.items():
                db.execute("UPDATE task SET state='done' WHERE id=?", (task_id,))
                db.execute("DELETE FROM discovered WHERE source=? AND key=?", (source, key))


def sync(db):
    if not CONFIG.exists():
        return
    config = json.loads(CONFIG.read_text())
    sources = (["github"] if "github" in config else []) + (
        ["tasks", "calendar", "drive", "gmail"] if config.get("google") else [])
    if config.get("linear"):
        sources.insert(0, "linear")
    for source in sources:
        try:
            now = time.time()
            if source == "linear":
                import keyring
                reconcile(db, source, projects.linear_rows(keyring.get_password("paco.linear", "personal"), now), now)
                continue
            if source == "drive":
                with google_session() as session:
                    projects.drive(session, db)
                continue
            if source == "gmail":
                if config.get("model"):
                    with google_session() as session:
                        mail_reasoning.sync(db, session, config["model"])
                else:
                    print("Gmail discovery requires paco.py connect model", file=sys.stderr)
                continue
            intervals = []
            rows = github(config[source], now) if source == "github" else google_rows(source, now, intervals)
            reconcile(db, source, rows, now)
            if source == "calendar":
                with db:
                    db.execute("DELETE FROM busy")
                    db.executemany("INSERT INTO busy VALUES(?,?)", intervals)
        except Exception as exc:
            print(f"{source} sync failed ({type(exc).__name__}); retained prior tasks", file=sys.stderr)
