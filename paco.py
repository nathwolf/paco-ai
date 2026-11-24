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


def connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS task (
        id INTEGER PRIMARY KEY, title TEXT NOT NULL, priority INTEGER NOT NULL,
        state TEXT NOT NULL, due REAL NOT NULL, nudges INTEGER NOT NULL DEFAULT 0
    )""")
    planning.initialize(db)
    return db


def tick(db, now, deliver):
    # Serialize workers and user actions so a committed completion suppresses delivery.
    with db:
        db.execute("BEGIN IMMEDIATE")
        if planning.reason_to_wait(db, now):
            return
        task = planning.ranked(db, now).fetchone()
        if task is None:
            return
        prompt = planning.prompt(db, task, now)
        deliver(f"{prompt}: {task['title']} (#{task['id']})")
        db.execute("INSERT INTO intervention VALUES(?,?,?)", (task["id"], "notify", now))
        db.execute("""UPDATE task SET state='open', nudges=nudges+1, due=?
                      WHERE id=?""", (now + 900, task["id"]))


def notify(message):
    script = ('on run argv\n display notification (item 1 of argv) '
              'with title "Paco"\nend run')
    subprocess.run(["/usr/bin/osascript", "-e", script, "--", message],
                   check=True, timeout=10)


def install():
    if sys.platform != "darwin":
        raise SystemExit("Login service installation requires macOS.")
    import shutil
    ROOT.mkdir(parents=True, exist_ok=True)
    target = ROOT / "paco.py"
    if Path(__file__).resolve() != target:
        shutil.copyfile(__file__, target)
        shutil.copyfile(discovery.projects.__file__, ROOT / "projects.py")
        shutil.copyfile(Path(__file__).with_name("desktop.py"), ROOT / "desktop.py")
        shutil.copyfile(discovery.mail_reasoning.history_sync.__file__, ROOT / "history_sync.py")
        shutil.copyfile(actions.__file__, ROOT / "actions.py")
        shutil.copyfile(planning.__file__, ROOT / "planning.py")
        shutil.copyfile(discovery.__file__, ROOT / "discovery.py")
        shutil.copyfile(discovery.mail_reasoning.__file__, ROOT / "mail_reasoning.py")
    plist = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    plist.parent.mkdir(parents=True, exist_ok=True)
    config = dict(Label=LABEL, ProgramArguments=[sys.executable, str(target), "run"],
                  RunAtLoad=True, KeepAlive=True, StandardErrorPath=str(ROOT / "service.log"))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    plist.write_bytes(plistlib.dumps(config))
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
    for name in ("plan", "review", "activity", "desktop"):
        commands.add_parser(name)
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
        import desktop
        return desktop.open_window(args.db,connect,planning)
    with closing(connect(args.db)) as db:
        now = time.time()
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


if __name__ == "__main__":
    main()
