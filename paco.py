"""Paco's offline reminder service. Run python3 paco.py --help."""
import actions
import discovery
import planning
import argparse
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing

ROOT = Path.home() / "Library/Application Support/Paco"
LABEL = "com.paco.reminders"


_READY = set()
_READY_LOCK = threading.Lock()


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    path.chmod(0o600)
    db.row_factory = sqlite3.Row
    # Per-connection settings: applied every time.
    db.execute("PRAGMA secure_delete=ON")
    if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
        try:
            # Persistent. Readers no longer block the scheduler, sync, capture and HTTP writers.
            db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # Another process holds the database; a later connection switches it.
    # Schema setup and expiry purge: once per database file per process, not on every connection.
    stat = path.stat()
    key = (str(path.resolve()), stat.st_dev, stat.st_ino)
    try:
        with _READY_LOCK:
            if key not in _READY:
                initialize(db)
                _READY.add(key)
    except BaseException:
        db.close()
        raise
    return db


def initialize(db):
    db.execute("""CREATE TABLE IF NOT EXISTS task (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, priority INTEGER NOT NULL,
        state TEXT NOT NULL, due REAL NOT NULL, nudges INTEGER NOT NULL DEFAULT 0
    )""")
    planning.initialize(db)
    import workflows
    workflows.initialize(db)
    import meetings
    meetings.initialize(db)
    meetings.purge(db)
    import calendar_planning
    calendar_planning.initialize(db)
    import slacking
    slacking.initialize(db)
    import tagging
    tagging.initialize(db)
    import intake, company_sync
    intake.initialize(db)
    company_sync.initialize(db)


def tick(db, now, deliver):
    # Serialize workers and user actions so a committed completion suppresses delivery.
    with db:
        db.execute("BEGIN IMMEDIATE")
        task = planning.next_reminder(db, now)
        if task is None:
            return
        prompt = planning.prompt(db, task, now)
        deliver(f"{prompt}: {task['title']} (#{task['id']})")
        db.execute("INSERT INTO intervention VALUES(?,?,?)", (task["id"], "notify", now))
        db.execute("""UPDATE task SET state='open', nudges=nudges+1, due=?
                      WHERE id=?""", (now + planning.reminder_delay(db, task, now), task["id"]))


def notify(message):
    script = ('on run argv\n display notification (item 1 of argv) '
              'with title "Paco"\nend run')
    subprocess.run(["/usr/bin/osascript", "-e", script, "--", message],
                   check=True, timeout=10)


def install():
    if sys.platform != "darwin":
        raise SystemExit("Login service installation requires macOS.")
    import shutil
    import venv
    ROOT.mkdir(parents=True, exist_ok=True)
    # launchd stops the Python parent, but LaunchServices owns the native shell.
    # Stop both before replacing the bundle, avoiding a stale second menu-bar icon.
    import signal
    import urllib.request
    import urllib.parse
    native_paths={str(ROOT/'build/Paco.app/Contents/MacOS/Paco'),str((ROOT/'build/Paco.app/Contents/MacOS/Paco').resolve()),'/Applications/Paco.app/Contents/MacOS/Paco'}
    native_pids=[]
    for line in subprocess.check_output(['ps','-axo','pid=,args='],text=True).splitlines():
        parts=line.strip().split(None,1)
        if len(parts)!=2:continue
        native=next((p for p in native_paths if parts[1].startswith(p+' ')),None)
        if not native:continue
        native_pids.append(int(parts[0]))
        url=parts[1][len(native)+1:].split(' ',1)[0]
        parsed=urllib.parse.urlsplit(url)
        token=urllib.parse.parse_qs(parsed.query).get('token',[''])[0]
        if parsed.hostname=='127.0.0.1' and token:
            req=urllib.request.Request('http://'+parsed.netloc+'/api/meetings',headers={'Authorization':'Bearer '+token})
            try:
                with urllib.request.urlopen(req,timeout=3) as response:active=json.load(response).get('active')
            except OSError:active=None
            if active:raise SystemExit('Finish the active meeting capture before updating Paco.')
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    for pid in native_pids:
        try:os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:pass
    target = ROOT / "paco.py"
    python = ROOT / '.venv/bin/python'
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(ROOT / '.venv')
    if Path(__file__).resolve() != target:
        for file in Path(__file__).parent.glob('*.py'):
            if not file.name.startswith(('test_', 'eval_')):
                shutil.copyfile(file,ROOT/file.name)
        for folder in ('web','native','assets','extensions','examples'):
            shutil.copytree(Path(__file__).parent/folder,ROOT/folder,dirs_exist_ok=True)
        for name in ('requirements.txt','requirements-meetings.txt','QUICKSTART.md','CONNECT.md','COMPANY.md'):
            shutil.copyfile(Path(__file__).parent/name, ROOT/name)
    subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(ROOT/'requirements.txt'),
                    '-r', str(ROOT/'requirements-meetings.txt')], check=True)
    import build_app
    applications=Path('/Applications') if os.access('/Applications',os.W_OK) else Path.home()/'Applications'
    applications.mkdir(parents=True,exist_ok=True)
    bundle=applications/'Paco.app'
    if bundle.is_symlink():bundle.unlink()
    if bundle.exists():
        info=plistlib.loads((bundle/'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier')!='com.paco.desktop':
            raise SystemExit('Another app already occupies '+str(bundle))
    prebuilt = Path(__file__).resolve().parent/'prebuilt/Paco.app'
    bundle = (build_app.install_prebuilt(prebuilt, ROOT, python, bundle) if prebuilt.exists()
              else build_app.build(root=ROOT, python=python,destination=bundle))
    internal=ROOT/'build/Paco.app'
    if internal.is_symlink():internal.unlink()
    elif internal.exists():shutil.rmtree(internal)
    internal.parent.mkdir(parents=True,exist_ok=True)
    internal.symlink_to(bundle,target_is_directory=True)
    shortcut = Path.home() / 'Applications/Paco.app'
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    if shortcut.is_symlink():shortcut.unlink()
    if shortcut!=bundle and not shortcut.exists():
        shortcut.symlink_to(bundle, target_is_directory=True)
    subprocess.run(['/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister','-f',str(bundle)],check=True)
    plist = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    plist.parent.mkdir(parents=True, exist_ok=True)
    config = dict(Label=LABEL, ProgramArguments=[str(python), str(target), "desktop", "--login"],
                  RunAtLoad=True, KeepAlive={"SuccessfulExit":False}, ThrottleInterval=30,
                  EnvironmentVariables={"PATH":os.environ.get("PATH","/usr/bin:/bin")},
                  StandardErrorPath=str(ROOT / "service.log"))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    plist.write_bytes(plistlib.dumps(config))
    plist.chmod(0o600)
    subprocess.run(["launchctl", "enable", domain + "/" + LABEL], check=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)


def sync_loop(path):
    while True:
        try:
            with closing(connect(path)) as db:
                discovery.sync(db)
        except Exception as exc:
            print(f"Background sync failed ({type(exc).__name__})", file=sys.stderr)
        time.sleep(300)


def main(argv=None):
    os.umask(0o077)
    if sys.platform == 'darwin':
        # Finder supplies a minimal PATH; retain access to the user's installed
        # model CLIs without requiring Paco to start from a terminal.
        paths = [str(Path.home()/'.local/bin'), '/opt/homebrew/bin', '/usr/local/bin']
        os.environ['PATH'] = ':'.join(dict.fromkeys(paths + os.environ.get('PATH', '/usr/bin:/bin').split(':')))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "tasks.sqlite3")
    commands = parser.add_subparsers(dest="cmd", required=True)
    arguments = sys.argv[1:] if argv is None else argv
    if arguments[:1] == ["connect"]:
        return discovery.configure(arguments[1:])
    commands.add_parser("connect", help="connect github or google")
    add = commands.add_parser("add")
    add.add_argument("title")
    add.add_argument("--priority", type=int, choices=range(1, 6), default=3)
    for name in ("start", "snooze", "done", "block", "resume"):
        command = commands.add_parser(name)
        command.add_argument("id", type=int)
        if name in ("start", "snooze"):
            command.add_argument("minutes", type=int)
    for name in ("list", "run", "sync", "install"):
        commands.add_parser(name)
    for name in ("plan", "review", "activity"):
        commands.add_parser(name)
    desktop_command = commands.add_parser("desktop")
    desktop_command.add_argument("--login",action="store_true",help="login service entry point")
    desktop_command.add_argument("--show-settings",action="store_true",help="open settings on an explicit app launch")
    mcp = commands.add_parser('mcp', help='serve scoped local MCP over stdio')
    mcp.add_argument('--client', required=True)
    grant = commands.add_parser('mcp-grant', help='replace client grants; omit scopes to revoke')
    grant.add_argument('client')
    grant.add_argument('scopes',nargs='*')
    commands.add_parser('doctor',help='check local runtime and optional dependencies')
    draft = commands.add_parser("draft-comment")
    draft.add_argument("id", type=int)
    draft.add_argument("body")
    publish = commands.add_parser("publish")
    publish.add_argument("draft")
    evidence = commands.add_parser("evidence")
    evidence.add_argument("id", type=int)
    for name in ("depends","unlink"):
        dependency = commands.add_parser(name)
        dependency.add_argument("task",type=int)
        dependency.add_argument("prerequisite",type=int)
    track = commands.add_parser("track")
    track.add_argument("path")
    prefer = commands.add_parser("set")
    prefer.add_argument("key", choices=["goal", "hours", "language", "voice"])
    prefer.add_argument("value")
    detail = commands.add_parser("estimate")
    detail.add_argument("id", type=int)
    detail.add_argument("minutes", type=int)
    detail.add_argument("--goal")
    detail.add_argument("--deadline", help="ISO date and local time")
    args = parser.parse_args(argv)
    if args.cmd == "install":
        if args.db != ROOT / "tasks.sqlite3":
            parser.error("install uses the default database")
        return install()
    if args.cmd == "desktop":
        if args.login:
            import startup
            if not startup.enabled():
                return
        import app
        return app.open_desktop(args.db,connect,show_settings=args.show_settings)
    if args.cmd == 'doctor':
        import importlib.util
        import shutil
        print(json.dumps({'python':sys.version.split()[0],'compatible':sys.version_info>=(3,11),
            'macos':sys.platform=='darwin','compiler':shutil.which('clang'),
            'claude':shutil.which('claude'),'codex':shutil.which('codex'),
            'optional':{name:importlib.util.find_spec(name) is not None for name in ('keyring','requests','google_auth_oauthlib')}},indent=2))
        return
    with closing(connect(args.db)) as db:
        now = time.time()
        if args.cmd in ('mcp','mcp-grant'):
            import mcp_server
            import agents
            agents.initialize(db)
            mcp_server.initialize(db)
            if args.cmd=='mcp-grant':
                return mcp_server.grant(db,args.client,args.scopes)
            return mcp_server.serve(db,args.client)
        if args.cmd == "draft-comment":
            print(actions.draft(db,args.id,args.body))
            return
        if args.cmd == "publish":
            config = json.loads(discovery.CONFIG.read_text())
            print(actions.publish(db,args.draft,*config["github"]))
            return
        if args.cmd == "evidence":
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "discovered" in tables:
                for source, key in db.execute("SELECT source,key FROM discovered WHERE task_id=?", (args.id,)):
                    print(source, key)
            if "mail_task" in tables:
                for row in db.execute("SELECT thread,message,quote FROM mail_task WHERE task=?", (args.id,)):
                    print(json.dumps(dict(row),ensure_ascii=False))
                for row in db.execute("SELECT message,quote FROM mail_resolution WHERE task=?", (args.id,)):
                    print(json.dumps(dict(row),ensure_ascii=False))
            return
        if args.cmd == "depends":
            try:
                planning.add_dependency(db,args.task,args.prerequisite)
            except ValueError as exc:
                parser.error(str(exc))
            return
        if args.cmd == "unlink":
            with db:
                db.execute("DELETE FROM dependency WHERE task=? AND prerequisite=?",(args.task,args.prerequisite))
            return
        if args.cmd == "track":
            return discovery.projects.track(db, args.path)
        if args.cmd == "activity":
            print(json.dumps(list(discovery.projects.activity(db)), ensure_ascii=False, indent=2))
            return
        if args.cmd == "set":
            if args.key == "voice" and args.value not in ("on","off"):
                parser.error("voice must be on or off")
            if args.key == "language" and args.value not in ("en", "es"):
                parser.error("language must be en or es")
            if args.key == "hours":
                import re
                match = re.fullmatch(r"([0-9]{1,2})-([0-9]{1,2})", args.value)
                if not match or not 0 <= int(match[1]) < int(match[2]) <= 24:
                    parser.error("use local hours such as 9-18")
            with db:
                db.execute("INSERT OR REPLACE INTO preference VALUES(?,?)", (args.key, args.value))
            return
        if args.cmd == "estimate":
            from datetime import datetime
            if args.minutes < 1 or not db.execute("SELECT 1 FROM task WHERE id=?", (args.id,)).fetchone():
                parser.error("supply a valid task id and positive minutes")
            try:
                deadline = datetime.fromisoformat(args.deadline).timestamp() if args.deadline else None
            except ValueError:
                parser.error("use an ISO deadline")
            with db:
                db.execute("INSERT OR REPLACE INTO details VALUES(?,?,?,?)",
                           (args.id,args.goal,args.minutes,deadline))
            return
        if args.cmd == "plan":
            wait = planning.reason_to_wait(db, now)
            if wait:
                print(wait)
            else:
                for row in planning.ranked(db, now):
                    why = "deadline within a day" if row["urgent"] else (row["goal"] if row["aligned"] else "priority " + str(row["priority"]))
                    print(f"#{row['id']} {row['title']} ({why})")
            return
        if args.cmd == "review":
            print(json.dumps(planning.review(db, now), ensure_ascii=False, indent=2))
            return
        if args.cmd == "sync":
            return discovery.sync(db)
        if args.cmd == "run":
            threading.Thread(target=sync_loop, args=(args.db,), daemon=True).start()
            while True:
                try:
                    def deliver(message):
                        notify(message)
                        if planning.setting(db, "voice") == "on":
                            subprocess.Popen(["/usr/bin/say", "--", message])
                    tick(db, time.time(), deliver)
                except (OSError, subprocess.SubprocessError, sqlite3.OperationalError) as exc:
                    print(exc, file=sys.stderr, flush=True)
                time.sleep(60)
        elif args.cmd == "list":
            for row in db.execute("SELECT * FROM task ORDER BY priority DESC, due, id"):
                print(json.dumps(dict(row), ensure_ascii=False))
        elif args.cmd == "add":
            if not args.title.strip():
                parser.error("provide a task title")
            with db:
                row = db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,?,'open',?)",
                                 (args.title.strip(), args.priority, now))
            print(row.lastrowid)
        else:
            minutes = getattr(args, "minutes", 0)
            if args.cmd in ("start", "snooze") and minutes <= 0:
                parser.error("minutes must be positive")
            state = {"done": "done", "block": "blocked", "start": "focus",
                     "snooze": "open", "resume": "open"}[args.cmd]
            with db:
                changed = db.execute("""UPDATE task SET state=?, due=?, nudges=0
                    WHERE id=? AND state!='done'""", (state, now + minutes * 60, args.id))
                db.execute("INSERT INTO intervention VALUES(?,?,?)", (args.id,args.cmd,now))
                if not changed.rowcount:
                    parser.error("no unfinished task with that ID")
                if args.cmd in ('done','block','resume'):
                    db.execute('INSERT INTO task_override(task,state) VALUES(?,?) ON CONFLICT(task) DO UPDATE SET state=excluded.state',(args.id,state))


if __name__ == "__main__":
    main()
