"""Shared policy for recommendations, reminders and weekly review."""
from datetime import datetime
import time


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS preference(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intervention(task INTEGER, action TEXT, at REAL);
        CREATE INDEX IF NOT EXISTS intervention_time ON intervention(at);
        CREATE TABLE IF NOT EXISTS outgoing(id TEXT PRIMARY KEY,target TEXT,body TEXT,status TEXT,receipt TEXT);
        CREATE TABLE IF NOT EXISTS repository(path TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS drive_context(id TEXT PRIMARY KEY,title TEXT,url TEXT,modified TEXT);
        CREATE TABLE IF NOT EXISTS busy(start REAL,end REAL);
        CREATE TABLE IF NOT EXISTS details(task INTEGER PRIMARY KEY, goal TEXT, minutes INTEGER, deadline REAL);
    """)


def setting(db, key, default=""):
    row = db.execute("SELECT value FROM preference WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def reason_to_wait(db, now):
    hour = datetime.fromtimestamp(now).hour
    start, end = map(int, setting(db, "hours", "0-24").split("-"))
    if not start <= hour < end:
        return "Outside working hours"
    if db.execute("SELECT 1 FROM busy WHERE start<=? AND end>?", (now, now)).fetchone():
        return "Meeting in progress"
    if db.execute("SELECT 1 FROM task WHERE state='focus' AND due>?", (now,)).fetchone():
        return "Focus session in progress"


def ranked(db, now):
    until = db.execute("SELECT MIN(start) FROM busy WHERE start>?", (now,)).fetchone()[0]
    goal = setting(db, "goal")
    return db.execute("""SELECT t.*,d.goal,d.minutes,d.deadline,
        CASE WHEN t.state='focus' THEN 1 ELSE 0 END AS checkin,
        CASE WHEN d.deadline<=? THEN 1 ELSE 0 END AS urgent,
        CASE WHEN d.goal=? AND d.goal!='' THEN 1 ELSE 0 END AS aligned
        FROM task t LEFT JOIN details d ON d.task=t.id
        WHERE t.state IN ('open','focus') AND t.due<=?
        AND (t.state='focus' OR ? IS NULL OR d.minutes IS NULL OR d.minutes*60<=?-?)
        ORDER BY checkin DESC, urgent DESC, aligned DESC, t.priority DESC, t.due, t.id""",
                      (now+86400, goal, now, until, until, now))


def review(db, now):
    rows = db.execute("""SELECT t.id,t.title,h.action,count(*) AS n FROM intervention h
        JOIN task t ON h.task=t.id WHERE h.at>=? GROUP BY t.id,h.action
        ORDER BY t.id,h.action""", (now-7*86400,))
    return [dict(r) for r in rows]


def prompt(db, task, now):
    spanish = setting(db, "language", "en") == "es"
    if task["state"] == "focus":
        return "¿Cómo vas?" if spanish else "Focus check-in"
    snoozes = db.execute("""SELECT count(*) FROM intervention
        WHERE task=? AND action='snooze' AND at>=?""", (task["id"], now-7*86400)).fetchone()[0]
    if snoozes >= 2:
        return "Empieza por un paso de cinco minutos" if spanish else "Try a five-minute first step"
    choices = (("Hora de empezar", "Sigo esperando", "Vamos. Da el primer paso") if spanish else
               ("Time to start", "Still waiting on you", "Come on. Take the first step"))
    return choices[min(task["nudges"], len(choices)-1)]
