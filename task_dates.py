"""Translate explicit source dates into the deadline used by planning and sync."""
from datetime import date, datetime, time


def timestamp(value):
    """Date-only commitments run through the named local day."""
    if value is None or value == '':
        return None
    if len(value) == 10:
        return datetime.combine(date.fromisoformat(value), time(23, 59)).timestamp()
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Include a timezone for deadlines with a time')
    return parsed.timestamp()


def fill(db, task, deadline):
    if deadline is not None:
        db.execute("""INSERT INTO details(task,goal,minutes,deadline) VALUES(?,'',30,?)
            ON CONFLICT(task) DO UPDATE SET deadline=excluded.deadline
            WHERE details.deadline IS NULL""", (task, deadline))


def source_row(key, title, now, deadline):
    """The optional fourth column carries the source deadline separately from the reminder clock."""
    return (key, title, now, timestamp(deadline)) if deadline else (key, title, now)
