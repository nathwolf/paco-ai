"""Durable Gmail history cursor with bounded bootstrap and replayable work."""
import time
from urllib.parse import quote


def update(db, get, owner, profile_version):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS gmail_cursor(owner TEXT PRIMARY KEY,version TEXT);
        CREATE TABLE IF NOT EXISTS gmail_work(owner TEXT,thread TEXT,
            PRIMARY KEY(owner,thread));
    """)
    cursor = db.execute("SELECT version FROM gmail_cursor WHERE owner=?", (owner,)).fetchone()
    if cursor and cursor[0] == profile_version:
        return
    found = set()
    page = None
    if cursor:
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
            page = result.get("nextPageToken")
            if not page:
                break
    if not cursor:
        page = None
        while True:
            result = get("threads",q="newer_than:7d -in:spam -in:trash -in:drafts",pageToken=page)
            found.update(t["id"] for t in result.get("threads", []))
            page = result.get("nextPageToken")
            if not page:
                break
    with db:
        db.executemany("INSERT OR IGNORE INTO gmail_work VALUES(?,?)", ((owner,t) for t in sorted(found)))
        db.execute("INSERT OR REPLACE INTO gmail_cursor VALUES(?,?)", (owner,profile_version))
