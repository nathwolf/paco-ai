"""Shared policy for recommendations, reminders and weekly review."""
from datetime import datetime
import flow


def initialize(db):
    import mac_focus
    mac_focus.initialize(db)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS preference(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS intervention(task INTEGER, action TEXT, at REAL);
        CREATE INDEX IF NOT EXISTS intervention_time ON intervention(at);
        CREATE TABLE IF NOT EXISTS outgoing(id TEXT PRIMARY KEY,target TEXT,body TEXT,status TEXT,receipt TEXT);
        CREATE TABLE IF NOT EXISTS repository(path TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS drive_context(id TEXT PRIMARY KEY,title TEXT,url TEXT,modified TEXT);
        CREATE TABLE IF NOT EXISTS dependency(task INTEGER, prerequisite INTEGER, PRIMARY KEY(task,prerequisite));
        CREATE TABLE IF NOT EXISTS busy(start REAL,end REAL);
        CREATE TABLE IF NOT EXISTS details(task INTEGER PRIMARY KEY, goal TEXT, minutes INTEGER, deadline REAL);
        CREATE TABLE IF NOT EXISTS absence(id TEXT PRIMARY KEY,start REAL,end REAL,label TEXT,source TEXT);
        CREATE TABLE IF NOT EXISTS urgency(task INTEGER PRIMARY KEY,critical INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS source_event(id INTEGER PRIMARY KEY,source TEXT,key TEXT,task INTEGER,outcome TEXT,at REAL);
        CREATE TABLE IF NOT EXISTS source_state(source TEXT,key TEXT,status TEXT,previous_state TEXT,PRIMARY KEY(source,key));
        CREATE TABLE IF NOT EXISTS sync_status(source TEXT PRIMARY KEY,last_success REAL,last_attempt REAL,error TEXT);
        CREATE TABLE IF NOT EXISTS notification(id INTEGER PRIMARY KEY,task INTEGER,message TEXT,mood TEXT,reason TEXT,created REAL,shown REAL);
        CREATE TABLE IF NOT EXISTS task_override(task INTEGER PRIMARY KEY,title TEXT,state TEXT);
        CREATE TABLE IF NOT EXISTS calendar_busy(provider TEXT,start REAL,end REAL);
    """)
    flow.initialize(db)


def update_estimate(db, task, minutes, changes):
    """An estimate-only edit must preserve both the goal and the deadline."""
    db.execute("""INSERT INTO details(task,goal,minutes,deadline) VALUES(?,?,?,?)
        ON CONFLICT(task) DO UPDATE SET minutes=excluded.minutes,
        goal=CASE WHEN ? THEN excluded.goal ELSE details.goal END,
        deadline=CASE WHEN ? THEN excluded.deadline ELSE details.deadline END""",
        (task,changes.get('goal',''),minutes,changes.get('deadline'),'goal' in changes,'deadline' in changes))


def setting(db, key, default=""):
    row = db.execute("SELECT value FROM preference WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def reason_to_wait(db, now):
    import mac_focus
    if mac_focus.active(db,now):return mac_focus.REASON
    import workspace
    if workspace.active(db,now):return 'Focus session in progress'
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='meeting_note'").fetchone() and db.execute("SELECT 1 FROM meeting_note WHERE state IN ('recording','paused','finishing')").fetchone():
        return 'Meeting in progress'
    if setting(db, "mode", "work") == "paused":
        return "Notifications paused"
    if float(setting(db, 'quiet_until', '0')) > now:
        return 'Temporarily away'
    flow_reason=flow.reason(db,now)
    if flow_reason:return flow_reason
    if setting(db, "mode", "work") == "holiday" or db.execute(
            "SELECT 1 FROM absence WHERE start<=? AND end>?", (now, now)).fetchone():
        return "On holiday — urgent tasks only"
    days = setting(db, "workdays", "0,1,2,3,4,5,6")
    if str(datetime.fromtimestamp(now).weekday()) not in days.split(","):
        return "Day off — urgent tasks only"
    hour = datetime.fromtimestamp(now).hour
    start, end = map(int, setting(db, "hours", "0-24").split("-"))
    if not start <= hour < end:
        return "Outside working hours"
    if db.execute("SELECT 1 FROM busy WHERE start<=? AND end>?", (now, now)).fetchone():
        return "Meeting in progress"
    if db.execute("SELECT 1 FROM task WHERE state='focus' AND due>?", (now,)).fetchone():
        return "Focus session in progress"


class EligibleRows:
    """Preserve the cursor interface while filtering responsibility-aware rows."""
    def __init__(self,rows):self.rows=iter(rows)
    def __iter__(self):return self
    def __next__(self):return next(self.rows)
    def fetchone(self):return next(self.rows,None)
    def fetchall(self):return list(self.rows)


def ranked(db, now, fit_before_meeting=True):
    until = db.execute("SELECT MIN(start) FROM busy WHERE start>?", (now,)).fetchone()[0] if fit_before_meeting else None
    goal = setting(db, "goal")
    rows = db.execute("""SELECT t.*,d.goal,d.minutes,d.deadline,COALESCE(u.critical,0) AS critical,
        CASE WHEN t.state='focus' THEN 1 ELSE 0 END AS checkin,
        CASE WHEN d.deadline<=? THEN 1 ELSE 0 END AS urgent,
        CASE WHEN d.goal=? AND d.goal!='' THEN 1 ELSE 0 END AS aligned
        FROM task t LEFT JOIN details d ON d.task=t.id LEFT JOIN urgency u ON u.task=t.id
        WHERE t.state IN ('open','focus') AND t.due<=?
        AND NOT EXISTS (SELECT 1 FROM dependency e JOIN task p ON p.id=e.prerequisite
            WHERE e.task=t.id AND p.state!='done')
        AND (t.state='focus' OR ? IS NULL OR d.minutes IS NULL OR d.minutes*60<=?-?)
        ORDER BY critical DESC, checkin DESC, urgent DESC, aligned DESC, t.priority DESC, t.due, t.id""",
                      (now+86400, goal, now, until, until, now)).fetchall()
    import attention
    return EligibleRows(r for r in rows if attention.eligible(db,r["id"]))


MEETING_SOURCES = ('calendar', 'apple_calendar', 'outlook_calendar')


def meeting_start(db, task_id):
    """Start time of the meeting a "Prepare for" task belongs to, or None."""
    if not task_id or not db.execute("SELECT 1 FROM sqlite_master WHERE name='discovered'").fetchone():
        return None
    row = db.execute('SELECT source,key FROM discovered WHERE task_id=? AND source IN (?,?,?)', (task_id, *MEETING_SOURCES)).fetchone()
    if not row:
        return None
    event = {'calendar': '', 'apple_calendar': 'apple:', 'outlook_calendar': 'outlook:'}[row[0]] + row[1]
    found = db.execute('SELECT start FROM calendar_event WHERE id=?', (event,)).fetchone()
    return found[0] if found else None


def time_off(db, now):
    """Holiday, a day off, or outside working hours, regardless of what else is going on."""
    if setting(db, 'mode', 'work') == 'holiday' or db.execute('SELECT 1 FROM absence WHERE start<=? AND end>?', (now, now)).fetchone():
        return True
    if str(datetime.fromtimestamp(now).weekday()) not in setting(db, 'workdays', '0,1,2,3,4,5,6').split(','):
        return True
    start, end = map(int, setting(db, 'hours', '0-24').split('-'))
    return not start <= datetime.fromtimestamp(now).hour < end


def meeting_due(db, now):
    """A meeting starting within 15 minutes you haven't been reminded of. Meetings are time-bound, so this
    may come through flow protection and focus sessions; pause, time off and an ongoing meeting still win."""
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='discovered'").fetchone():
        return None
    rows = db.execute("""SELECT t.*,d.goal,d.minutes,d.deadline,COALESCE(u.critical,0) AS critical FROM task t
        JOIN discovered dc ON dc.task_id=t.id LEFT JOIN details d ON d.task=t.id LEFT JOIN urgency u ON u.task=t.id
        WHERE dc.source IN (?,?,?) AND t.state='open' AND t.due<=? AND t.due>?
          AND NOT EXISTS(SELECT 1 FROM intervention i WHERE i.task=t.id AND i.action IN ('notify','snooze','done','start'))
        ORDER BY t.due""", (*MEETING_SOURCES, now, now - 900)).fetchall()
    for row in rows:
        start = meeting_start(db, row['id'])
        import attention
        if start and now < start and attention.eligible(db,row['id']):
            return row
    return None


def next_reminder(db, now):
    """Explicit critical flags may interrupt time off, never pause, focus or snooze."""
    import workspace
    if workspace.active(db,now):return None
    wait = reason_to_wait(db, now)
    if wait in ("Notifications paused", "Temporarily away", "Meeting in progress", "macOS Focus is on"):
        return None
    meeting = meeting_due(db, now)
    if meeting and not time_off(db, now):
        return meeting
    if wait == "Focus session in progress":
        return None
    if flow.reason(db,now,critical=True):return None
    # Holiday must not mask a concurrent meeting or focus session.
    if db.execute("SELECT 1 FROM busy WHERE start<=? AND end>?", (now, now)).fetchone():
        return None
    if db.execute("SELECT 1 FROM task WHERE state='focus' AND due>?", (now,)).fetchone():
        return None
    import tagging
    rows = [r for r in ranked(db, now) if tagging.allowed(db, now, r)]   # a focus day silences other projects
    if wait:
        rows = [r for r in rows if r["critical"]]
    last = db.execute("SELECT MAX(at) FROM intervention WHERE action='notify'").fetchone()[0]
    gap = int(setting(db, "notification_gap", "60"))
    if last is not None and now-last < gap:
        return None
    midnight = datetime.fromtimestamp(now).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    # A morning burst must not silence the rest of the day. Use a rolling
    # allowance; due-today commitments retain their own per-task budget.
    recent=db.execute("SELECT count(*) FROM intervention WHERE action='notify' AND at>?",(now-3*3600,)).fetchone()[0]
    if recent>=4:
        rows=[r for r in rows if r['critical'] or r['deadline'] and r['deadline']<=now+86400]
    budget = 2 if wait else 8
    rows = [r for r in rows if db.execute("SELECT count(*) FROM intervention WHERE task=? AND action='notify' AND at>=?",(r['id'],midnight)).fetchone()[0] < budget]
    return rows[0] if rows else None


def delivery_status(db,now):
    if next_reminder(db,now):return None
    reason=reason_to_wait(db,now)
    if reason:return reason
    if not ranked(db,now).fetchone():return 'No reminders due yet'
    last=db.execute("SELECT MAX(at) FROM intervention WHERE action='notify'").fetchone()[0]
    if last and now-last<int(setting(db,'notification_gap','60')):return 'Spacing out reminders'
    recent=db.execute("SELECT count(*) FROM intervention WHERE action='notify' AND at>?",(now-3*3600,)).fetchone()[0]
    if recent>=4:return 'Spacing out routine reminders — up to four per three hours'
    return 'Waiting for the next eligible reminder'


def presentation(task, now, spanish=False):
    """Delay increases expression only for work already judged important."""
    overdue = max(0, now-(task["deadline"] or now))
    if task["critical"]:
        mood = "rage" if overdue >= 3*86400 else ("furious" if overdue >= 86400 else "angry")
    elif task["deadline"] and overdue > 0:
        mood = "angry" if task["priority"] >= 4 and overdue >= 86400 else "impatient"
    else:
        mood = "impatient" if task["nudges"] >= 2 else "friendly"
    return mood, headline(task, now, spanish)


def _span(seconds, spanish):
    hours = seconds/3600
    if hours < 1:
        return f"{max(1, round(seconds/60))} min"
    if hours < 36:
        return f"{round(hours)} h"
    days = round(hours/24)
    return f"{days} {'días' if spanish else 'days'}" if days != 1 else ("1 día" if spanish else "1 day")


def badges(task, now, spanish=False):
    """Banner status chips, strongest first: [(text, tone)]. Tones: red, orange, green, blue, gray."""
    chips = []
    deadline = task["deadline"]
    if task["state"] == "focus":
        chips.append(("Sesión de enfoque" if spanish else "Focus check-in", "blue"))
    elif task["critical"]:
        chips.append(("Urgente" if spanish else "Urgent", "red"))
    if deadline and deadline < now:
        chips.append((f"{_span(now-deadline, spanish)} tarde" if spanish else f"{_span(now-deadline, spanish)} late", "red"))
    elif deadline and deadline-now < 7*86400:
        soon = deadline-now < 86400
        chips.append((f"Vence en {_span(deadline-now, spanish)}" if spanish else f"Due in {_span(deadline-now, spanish)}", "orange" if soon else "green"))
    if not chips:
        chips.append(("Lo siguiente" if spanish else "Next up", "green"))
    minutes = task["minutes"] if "minutes" in task.keys() else None
    if minutes:
        chips.append((f"~{minutes} min", "gray"))
    return chips[:3]


def headline(task, now, spanish=False):
    """Short banner heading (about 26 characters fit): why now, how late or soon, how long."""
    parts = []
    if task["state"] == "focus":
        parts.append("Sesión de enfoque" if spanish else "Focus check-in")
    elif task["critical"]:
        parts.append("Urgente" if spanish else "Urgent")
    deadline = task["deadline"]
    if deadline and deadline < now:
        parts.append(f"{_span(now-deadline, spanish)} tarde" if spanish else f"{_span(now-deadline, spanish)} late")
    elif deadline and deadline-now < 7*86400:
        parts.append(f"vence en {_span(deadline-now, spanish)}" if spanish else f"due in {_span(deadline-now, spanish)}")
    if not parts:
        parts.append("Lo siguiente" if spanish else "Next up")
    minutes = task["minutes"] if "minutes" in task.keys() else None
    if minutes and len(parts) < 2:
        parts.append(f"~{minutes} min")
    text = " · ".join(parts[:2])
    return text[0].upper()+text[1:]


def reminder_delay(db, task, now):
    snoozes = db.execute("SELECT count(*) FROM intervention WHERE task=? AND action='snooze' AND at>?",
                         (task["id"], now-7*86400)).fetchone()[0]
    if task['critical'] and reason_to_wait(db,now):
        return 21600 # At most two holiday interruptions per task, six hours apart.
    base = int(setting(db, 'reminder_base_seconds', '900'))
    return min(14400, base * 2 ** min(max(snoozes-1, task['nudges']//2, 0), 4))


def morning_plan(db, now):
    """Build nonoverlapping slots around meetings, bounded by the workday."""
    if reason_to_wait(db, now):
        return []
    day = datetime.fromtimestamp(now)
    end_hour = int(setting(db, "hours", "0-24").split("-")[1])
    end = day.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + end_hour*3600
    cursor, result = now, []
    busy = list(db.execute("SELECT start,end FROM busy WHERE end>? ORDER BY start", (now,)))
    import tagging
    for task in ranked(db, now, fit_before_meeting=False):
        if not tagging.allowed(db, now, task):
            continue
        duration = (task["minutes"] or 25)*60
        for start, finish in busy:
            if cursor < finish and cursor+duration > start:
                cursor = finish
        if cursor+duration > end:
            continue
        result.append(dict(id=task["id"], title=task["title"], start=cursor, end=cursor+duration))
        cursor += duration+300
    return result


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

def add_dependency(db, task, prerequisite):
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT count(*) FROM task WHERE id IN (?,?)",(task,prerequisite)).fetchone()[0] != 2:
            raise ValueError("choose two different existing tasks")
        cycle = db.execute("""WITH RECURSIVE parents(id) AS (
            SELECT ? UNION SELECT e.prerequisite FROM dependency e JOIN parents ON e.task=parents.id
            ) SELECT 1 FROM parents WHERE id=?""",(prerequisite,task)).fetchone()
        if cycle:
            raise ValueError("dependency would form a cycle")
        db.execute("INSERT OR IGNORE INTO dependency VALUES(?,?)",(task,prerequisite))
