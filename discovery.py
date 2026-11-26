"""Read-only sources feeding Paco's local reminders."""
import argparse
import json
import os
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
        write_config(config)
        return
    parser = argparse.ArgumentParser(prog="paco connect")
    parser.add_argument("source", choices=["github", "google", "linear"])
    parser.add_argument("--client", type=Path)
    parser.add_argument('--calendar-write',action='store_true',help='allow explicitly approved calendar moves with attendee notifications')
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
        scopes = SCOPES + (["https://www.googleapis.com/auth/calendar.events"] if opt.calendar_write else [])
        flow = InstalledAppFlow.from_client_secrets_file(str(opt.client), scopes)
        creds = flow.run_local_server(port=0, prompt="consent")
        keyring.set_password("paco.google", "oauth", creds.to_json())
        config["google"] = True
        config['calendar_write'] = opt.calendar_write
    write_config(config)


def write_config(config):
    """Private atomic write. A unique temporary file keeps concurrent saves from interleaving."""
    import tempfile
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG.parent, prefix=".sources-", suffix=".tmp")  # created 0600
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(config, file)
        os.replace(tmp, CONFIG)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


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


def github_reviews(settings, now):
    exe, account = settings
    who = subprocess.check_output([exe,'api','user','--jq','.login'],text=True,timeout=20).strip()
    if who != account:
        raise ValueError('GitHub account changed; reconnect it')
    page = 1
    while True:
        query = quote('is:pr is:open review-requested:'+account, safe='')
        data = json.loads(subprocess.check_output([exe,'api',f'search/issues?q={query}&per_page=100&page={page}'],text=True,timeout=30))
        if data.get('incomplete_results') or data.get('total_count',0)>1000:
            raise ValueError('Incomplete review snapshot; retained prior tasks')
        for item in data['items']:
            yield item['html_url'], 'Review: '+item['title'], now
        if page*100 >= data['total_count']:
            break
        page += 1


def google_session():
    import keyring
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import AuthorizedSession
    raw = keyring.get_password("paco.google", "oauth")
    if not raw:
        raise ValueError("reconnect Google")
    return AuthorizedSession(Credentials.from_authorized_user_info(json.loads(raw)))


def google_rows(source, now, intervals=None, absences=None, calendars=None, events_out=None, people_out=None):
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
            events = []
            for calendar in calendars or ['primary']:
                url = 'https://www.googleapis.com/calendar/v3/calendars/'+quote(calendar,safe='')+'/events'
                events.extend((calendar,e) for e in pages(url, 'items', singleEvents='true', timeMin=stamp(now),timeMax=stamp(now+7*86400)))
            for calendar, event in events:
                start = event.get("start", {}).get("dateTime")
                declined = any(a.get("self") and a.get("responseStatus") == "declined"
                               for a in event.get("attendees", []))
                if event.get('eventType') == 'outOfOffice' and not declined and event.get('status') != 'cancelled':
                    def event_time(part):
                        value = part.get('dateTime') or part['date']
                        if 'dateTime' in part:
                            return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
                        from zoneinfo import ZoneInfo
                        zone = event.get('start',{}).get('timeZone')
                        parsed = datetime.fromisoformat(value)
                        return parsed.replace(tzinfo=ZoneInfo(zone)).timestamp() if zone else parsed.timestamp()
                    if absences is not None:
                        absences.append((calendar+':'+event['id'],event_time(event['start']),event_time(event['end']),event.get('summary','Time off'),'calendar'))
                    continue
                if start and not declined and event.get("status") != "cancelled":
                    begins = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp()
                    ends = event.get("end", {}).get("dateTime")
                    if events_out is not None and ends:
                        events_out.append((calendar+':'+event['id'],calendar,event.get('summary','Meeting'),begins,
                            datetime.fromisoformat(ends.replace('Z','+00:00')).timestamp(),
                            event.get('hangoutLink') or event.get('htmlLink',''),event.get('etag',''),
                            json.dumps([a.get('email','') for a in event.get('attendees',[])])))
                    if people_out is not None and ends:
                        import meeting_identity
                        people_out.append((calendar+':'+event['id'],json.dumps(meeting_identity.normalize_people(event.get('attendees',[]))),now))
                    if intervals is not None and ends and event.get("transparency") != "transparent":
                        intervals.append((begins, datetime.fromisoformat(ends.replace("Z", "+00:00")).timestamp()))
                    if begins > now:
                        yield calendar+':'+event["id"], "Prepare for " + event.get("summary", "meeting"), begins - 900

TRACKERS = {'tasks','apple_reminders','todoist','asana','jira','linear','microsoft_todo','gitlab'}


def reconcile(db, source, rows, now):
    # Fetch the entire snapshot successfully before expiring any previous entries.
    rows = list(rows)
    with db:
        db.execute("""CREATE TABLE IF NOT EXISTS discovered (
            source TEXT, key TEXT, task_id INTEGER, scheduled REAL,
            PRIMARY KEY(source,key))""")
        if source=='calendar':
            for key,_,_ in rows:
                if key.startswith('primary:') and not db.execute('SELECT 1 FROM discovered WHERE source=? AND key=?',(source,key)).fetchone():
                    legacy=key[len('primary:'):]
                    db.execute('UPDATE discovered SET key=? WHERE source=? AND key=?',(key,source,legacy))
                    db.execute('UPDATE source_state SET key=? WHERE source=? AND key=?',(key,source,legacy))
                    db.execute('UPDATE source_event SET key=? WHERE source=? AND key=?',(key,source,legacy))
        previous = {r[0]: r[1:] for r in db.execute(
            "SELECT key,task_id,scheduled FROM discovered WHERE source=?", (source,))}
        for key, title, due in rows:
            old = previous.pop(key, None)
            if old:
                task_id, scheduled = old
                db.execute("UPDATE task SET title=? WHERE id=? AND NOT EXISTS(SELECT 1 FROM task_override WHERE task=? AND title IS NOT NULL)", (title, task_id, task_id))
                prior = db.execute("SELECT status,previous_state FROM source_state WHERE source=? AND key=?", (source,key)).fetchone()
                if prior and prior[0] != "active":
                    db.execute("UPDATE task SET state=? WHERE id=? AND state IN ('unavailable','cancelled') AND NOT EXISTS(SELECT 1 FROM task_override WHERE task=? AND state IN ('done','archived','incorrect','cancelled','blocked'))",
                               (prior[1] if prior[1] in ('open','blocked') else 'open',task_id,task_id))
                    if prior[0]=='completed' and not db.execute('SELECT 1 FROM task_override WHERE task=? AND state IS NOT NULL',(task_id,)).fetchone():
                        db.execute("UPDATE task SET state='open' WHERE id=? AND state='done'",(task_id,))
                    db.execute("INSERT INTO source_event(source,key,task,outcome,at) VALUES(?,?,?,'reappeared',?)", (source,key,task_id,now))
                if source == "calendar" and due != scheduled:
                    db.execute("UPDATE task SET due=? WHERE id=? AND state='open'", (due, task_id))
                    db.execute("UPDATE discovered SET scheduled=? WHERE task_id=?", (due, task_id))
            else:
                cursor = db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)",
                                    (title, due))
                db.execute("INSERT INTO discovered VALUES(?,?,?,?)", (source, key, cursor.lastrowid, due))
                task_id = cursor.lastrowid
            db.execute("INSERT OR REPLACE INTO source_state VALUES(?,?,'active',NULL)", (source,key))
        if source != "gmail":
            for key, (task_id, _) in previous.items():
                prior = db.execute("SELECT status FROM source_state WHERE source=? AND key=?", (source,key)).fetchone()
                if prior and prior[0] != 'active':
                    continue
                state = db.execute("SELECT state FROM task WHERE id=?", (task_id,)).fetchone()[0]
                # A missing assignment is not proof of delivery. Preserve identity and dependencies.
                db.execute("INSERT OR REPLACE INTO source_state VALUES(?,?,'unavailable',?)", (source,key,state))
                db.execute("UPDATE task SET state='unavailable' WHERE id=? AND state IN ('open','focus','blocked') AND NOT EXISTS(SELECT 1 FROM task_override WHERE task=? AND state IN ('done','archived','incorrect','cancelled','blocked'))", (task_id,task_id))
                db.execute("INSERT INTO source_event(source,key,task,outcome,at) VALUES(?,?,?,'unavailable',?)", (source,key,task_id,now))
                # Gone from an open-items list almost always means finished there: ask, never assume.
                if source.split(':')[0] in TRACKERS and state in ('open','focus','blocked'):
                    db.execute("INSERT INTO source_event(source,key,task,outcome,at) VALUES(?,?,?,'suggested_completion',?)", (source,key,task_id,now))


def source_outcome(db, source, key, outcome, now):
    """Only a positive provider observation may satisfy a dependency."""
    if outcome not in ('completed','cancelled','reassigned','unavailable'):
        raise ValueError('Unknown source outcome')
    row = db.execute('SELECT task_id FROM discovered WHERE source=? AND key=?',(source,key)).fetchone()
    if not row:
        raise ValueError('Unknown source identity')
    state = {'completed':'done','cancelled':'cancelled','reassigned':'unavailable','unavailable':'unavailable'}[outcome]
    with db:
        db.execute('UPDATE task SET state=? WHERE id=? AND NOT EXISTS(SELECT 1 FROM task_override WHERE task=? AND state IS NOT NULL)',(state,row[0],row[0]))
        db.execute('UPDATE source_state SET status=? WHERE source=? AND key=?',(outcome,source,key))
        db.execute('INSERT INTO source_event(source,key,task,outcome,at) VALUES(?,?,?,?,?)',(source,key,row[0],outcome,now))


def verify_github_missing(db, settings, source, now):
    import re
    exe, account = settings
    missing = list(db.execute("SELECT key FROM source_state WHERE source=? AND status='unavailable' LIMIT 20",(source,)))
    for (key,) in missing:
        match = re.fullmatch(r'https://github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)',key)
        if not match:
            continue
        route = 'repos/{}/{}/issues/{}'.format(*match.groups())
        try:
            detail = json.loads(subprocess.check_output([exe,'api',route],text=True,stderr=subprocess.DEVNULL,timeout=20))
        except subprocess.CalledProcessError:
            continue # Lost visibility is not completion.
        if detail.get('state')=='closed':
            cancelled = detail.get('state_reason')=='not_planned'
            if detail.get('pull_request'):
                pull_route = 'repos/{}/{}/pulls/{}'.format(*match.groups())
                pull = json.loads(subprocess.check_output([exe,'api',pull_route],text=True,stderr=subprocess.DEVNULL,timeout=20))
                cancelled = not pull.get('merged')
            source_outcome(db,source,key,'cancelled' if cancelled else 'completed',now)
        elif source=='github' and account not in [a['login'] for a in detail.get('assignees',[])]:
            source_outcome(db,source,key,'reassigned',now)


def sync(db):
    if not CONFIG.exists():
        return
    config = json.loads(CONFIG.read_text())
    sources = (["github", "github_reviews"] if "github" in config else []) + (
        ["tasks", "calendar", "drive", "gmail"] if config.get("google") else [])
    if config.get("linear"):
        sources.insert(0, "linear")
    sources += list(config.get('connectors',{}))
    sources += [s for s in ('apple_calendar','apple_reminders') if config.get(s)]
    for source in sources:
        def success():
            with db:
                db.execute('UPDATE sync_status SET last_success=?,error=NULL WHERE source=?',(time.time(),source))
        try:
            now = time.time()
            with db:
                db.execute('INSERT INTO sync_status(source,last_attempt) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET last_attempt=excluded.last_attempt',(source,now))
            if source in ('apple_calendar','apple_reminders'):
                from pathlib import Path
                executable=Path(__file__).parent/'build/Paco.app/Contents/MacOS/Paco'
                items=json.loads(subprocess.check_output([str(executable),'--apple','calendar' if source=='apple_calendar' else 'reminders'],text=True,timeout=70))
                if source=='apple_reminders':
                    reconcile(db,source,[(i['account']+'/'+i['id'],i['title'],now) for i in items],now)
                else:
                    reconcile(db,source,[(i['id'],'Prepare for '+i['title'],i['start']-900) for i in items if not i['all_day'] and i['start']>now],now)
                    with db:
                        db.execute("DELETE FROM calendar_busy WHERE provider='apple'")
                        db.executemany("INSERT INTO calendar_busy VALUES('apple',?,?)",[(i['start'],i['end']) for i in items if i['busy'] and not i['all_day']])
                        db.execute("DELETE FROM calendar_event WHERE id LIKE 'apple:%'")
                        db.executemany('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',
                            [('apple:'+i['id'],'apple:'+i['calendar'],i['title'],i['start'],i['end'],i['url'],'',json.dumps([p.get('email','') for p in i.get('attendees',[]) if p.get('email')])) for i in items if not i['all_day']])
                        db.execute("DELETE FROM calendar_people WHERE event LIKE 'apple:%'")
                        db.executemany('INSERT OR REPLACE INTO calendar_people VALUES(?,?,?)',[('apple:'+i['id'],json.dumps(i.get('attendees',[])),now) for i in items if not i['all_day']])
                        db.execute('DELETE FROM busy')
                        db.execute('INSERT INTO busy SELECT start,end FROM calendar_busy')
                success()
                continue
            if source in config.get('connectors',{}):
                if source=='mattermost':
                    import mattermost
                    mattermost.sync(db,config['connectors'][source],config.get('model'),now)
                    success()
                    continue
                import connectors
                import workflows
                connection = config['connectors'][source]
                client = connectors.configured_client(source,connection)
                if source=='outlook_calendar':
                    events = connectors.outlook_events(client,connection['account'],now)
                    reconcile(db,source,[(e['id'],'Prepare for '+e['title'],e['start']-900) for e in events if e['start']>now],now)
                    with db:
                        db.execute("DELETE FROM calendar_busy WHERE provider='outlook'")
                        db.executemany("INSERT INTO calendar_busy VALUES('outlook',?,?)",[(e['start'],e['end']) for e in events if e['busy']])
                        db.execute("DELETE FROM calendar_event WHERE id LIKE 'outlook:%'")
                        db.executemany('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',
                            [('outlook:'+e['id'],'outlook',e['title'],e['start'],e['end'],e['url'],'',json.dumps(e['attendees'])) for e in events])
                        db.execute('DELETE FROM busy')
                        db.execute('INSERT INTO busy SELECT start,end FROM calendar_busy')
                    success()
                    continue
                if source=='slack':
                    messages = connectors.slack_messages(client,connection['account'],now)
                    with db:
                        for message in messages:
                            workflows.remember(db,'slack',connection['account']+'/'+message['url'],message['text'],message['url'],message['person'],at=message['at'])
                else:
                    reconcile(db,source+':'+connection['account'],connectors.snapshot(source,client,connection['account'],now),now)
                success()
                continue
            if source == "linear":
                import keyring
                reconcile(db, source, projects.linear_rows(keyring.get_password("paco.linear", "personal"), now), now)
                success()
                continue
            if source == "drive":
                with google_session() as session:
                    projects.drive(session, db)
                success()
                continue
            if source == "gmail":
                if config.get("model"):
                    with google_session() as session:
                        mail_reasoning.sync(db, session, config["model"])
                else:
                    raise ValueError('Gmail requires a configured model')
                success()
                continue
            intervals, absences, events, people = [], [], [], []
            if source == 'github_reviews':
                rows = github_reviews(config['github'],now)
            elif source == 'github':
                rows = github(config[source],now)
            else:
                rows = google_rows(source,now,intervals,absences,config.get('calendars'),events,people)
            reconcile(db, source, rows, now)
            if source in ('github','github_reviews'):
                verify_github_missing(db,config['github'],source,now)
            if source == "calendar":
                with db:
                    db.execute("DELETE FROM busy")
                    db.execute("DELETE FROM calendar_busy WHERE provider='google'")
                    db.executemany("INSERT INTO calendar_busy VALUES('google',?,?)", intervals)
                    db.execute('INSERT INTO busy SELECT start,end FROM calendar_busy')
                    db.execute("DELETE FROM calendar_event WHERE id NOT LIKE 'apple:%'")
                    db.executemany('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',events)
                    db.execute("DELETE FROM calendar_people WHERE event NOT LIKE 'apple:%'")
                    db.executemany('INSERT OR REPLACE INTO calendar_people VALUES(?,?,?)',people)
                    db.execute("DELETE FROM absence WHERE source='calendar'")
                    db.executemany('INSERT OR REPLACE INTO absence VALUES(?,?,?,?,?)',absences)
        except Exception as exc:
            with db:
                db.execute('UPDATE sync_status SET error=? WHERE source=?',(type(exc).__name__+' — reconnect or retry',source))
            print(f"{source} sync failed ({type(exc).__name__}); retained prior tasks", file=sys.stderr)
        else:
            with db:
                db.execute('UPDATE sync_status SET last_success=?,error=NULL WHERE source=?',(time.time(),source))
