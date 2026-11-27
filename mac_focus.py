"""Local Focus observations, reserved for a reliable native status provider.

No provider is enabled in the locally signed build. In particular, do not poll
Shortcuts: running a shortcut repeatedly displays macOS's activity indicator.
Unknown status must never be presented as proof that Mac Focus is off.
"""
import time

REASON='macOS Focus is on'
TTL=45


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS system_focus(id INTEGER PRIMARY KEY CHECK(id=1),active INTEGER,at REAL)')


def observe(db,active,now=None):
    if active is not None and type(active) is not bool:raise ValueError('Invalid Focus status')
    with db:db.execute('INSERT OR REPLACE INTO system_focus VALUES(1,?,?)',(active,time.time() if now is None else now))


def status(db,now=None):
    now=time.time() if now is None else now
    row=db.execute('SELECT * FROM system_focus WHERE id=1').fetchone()
    fresh=bool(row and 0<=now-row['at']<=TTL)
    value=bool(row['active']) if fresh and row['active'] is not None else None
    message=REASON if value else 'macOS Focus is off' if value is False else 'Automatic Mac Focus detection unavailable in this build. Use a Paco focus session or pause reminders.'
    return {'active':value,'message':message}


def active(db,now=None):return status(db,now)['active'] is True
