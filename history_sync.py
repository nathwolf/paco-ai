"""Durable Gmail history cursor with bounded bootstrap and replayable work."""
import time


def update(db, get, owner, profile_version):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS gmail_priority(owner TEXT,thread TEXT,priority INTEGER,PRIMARY KEY(owner,thread));
        CREATE TABLE IF NOT EXISTS gmail_scan(owner TEXT PRIMARY KEY,days INTEGER,at REAL);
        CREATE TABLE IF NOT EXISTS gmail_cursor(owner TEXT PRIMARY KEY,version TEXT);
        CREATE TABLE IF NOT EXISTS gmail_work(owner TEXT,thread TEXT,
            PRIMARY KEY(owner,thread));
    """)
    cursor = db.execute("SELECT version FROM gmail_cursor WHERE owner=?", (owner,)).fetchone()
    scanned = db.execute('SELECT days FROM gmail_scan WHERE owner=?',(owner,)).fetchone()
    backfill = not scanned or scanned[0] < 30
    if cursor and cursor[0] == profile_version and not backfill:
        return
    found = set()
    changed = set()
    page = None
    if cursor and cursor[0] != profile_version:
        while True:
            try:
                result = get("history",startHistoryId=cursor[0],pageToken=page)
            except Exception as exc:
                if getattr(getattr(exc,"response",None),"status_code",None) != 404:
                    raise
                cursor = None
                break
            for record in result.get("history", []):
                for message in record.get("messages", []):
                    found.add(message["threadId"])
                    changed.add(message["threadId"])
            page = result.get("nextPageToken")
            if not page:
                break
    if not cursor or backfill:
        page = None
        while True:
            result = get("threads",q="newer_than:30d -in:spam -in:trash -in:drafts",pageToken=page)
            found.update(t["id"] for t in result.get("threads", []))
            page = result.get("nextPageToken")
            if not page:
                break
    with db:
        db.executemany("INSERT OR IGNORE INTO gmail_work VALUES(?,?)", ((owner,t) for t in sorted(found,reverse=True)))
        db.executemany("INSERT INTO gmail_priority VALUES(?,?,?) ON CONFLICT(owner,thread) DO UPDATE SET priority=MAX(priority,excluded.priority)",
                       [(owner,t,int(t in changed)) for t in found])
        db.execute("INSERT OR REPLACE INTO gmail_cursor VALUES(?,?)", (owner,profile_version))
        if not cursor or backfill:db.execute('INSERT OR REPLACE INTO gmail_scan VALUES(?,30,?)',(owner,time.time()))
