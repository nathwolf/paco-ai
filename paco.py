"""Paco's offline reminder service. Run python3 paco.py --help."""
import discovery
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
    return db


def tick(db, now, deliver):
    # Serialize workers and user actions so a committed completion suppresses delivery.
    with db:
        db.execute("BEGIN IMMEDIATE")
        task = db.execute("""SELECT * FROM task WHERE state IN ('open','focus')
            AND due <= ? ORDER BY priority DESC, due, id LIMIT 1""", (now,)).fetchone()
        if task is None:
            return
        prompts = ("Time to start", "Still waiting on you", "Come on. Take the first step")
        prompt = ("Focus check-in" if task["state"] == "focus"
                  else prompts[min(task["nudges"], len(prompts) - 1)])
        deliver(f"{prompt}: {task['title']} (#{task['id']})")
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
    args = parser.parse_args(argv)
    if args.cmd == "install":
        if args.db != ROOT / "tasks.sqlite3":
            parser.error("install uses the default database")
        return install()
    with closing(connect(args.db)) as db:
        now = time.time()
        if args.cmd == "sync":
            return discovery.sync(db)
        if args.cmd == "run":
            threading.Thread(target=sync_loop, args=(args.db,), daemon=True).start()
            while True:
                try:
                    tick(db, time.time(), notify)
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
                if not changed.rowcount:
                    parser.error("no unfinished task with that ID")


if __name__ == "__main__":
    main()
