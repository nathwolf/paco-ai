"""Where to go to deal with a task: the issue, the email thread, the meeting's join link, the notes.

A link is {'url', 'label'}. Only three kinds are ever returned:
- http(s) web addresses from the source itself,
- 'paco-app:<bundle id>' to open a Mac app (Reminders, Calendar),
- '/meetings' or '/advanced', Paco's own pages.
"""
from urllib.parse import urlsplit

HOSTS = [('github.com', 'Open in GitHub'), ('gitlab', 'Open in GitLab'), ('atlassian.net', 'Open in Jira'),
         ('linear.app', 'Open in Linear'), ('app.asana.com', 'Open in Asana'), ('todoist.com', 'Open in Todoist'),
         ('to-do.office.com', 'Open in To Do'), ('to-do.live.com', 'Open in To Do'), ('outlook.', 'Open email'),
         ('mail.google.com', 'Open email'), ('slack.com', 'Open in Slack'), ('docs.google.com', 'Open document'),
         ('drive.google.com', 'Open in Drive'), ('meet.google.com', 'Join meeting'), ('zoom.us', 'Join meeting'),
         ('teams.microsoft.com', 'Join meeting'), ('teams.live.com', 'Join meeting'), ('calendar.google.com', 'Open in Calendar')]
JOIN = ('meet.google.com', 'zoom.us', 'teams.microsoft.com', 'teams.live.com', 'webex.com', 'whereby.com')


def web(url, label=None):
    """A safe web link with a label from its host, or None."""
    parts = urlsplit(str(url or ''))
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return None
    host = parts.hostname.lower()
    for fragment, name in HOSTS:
        if fragment in host:
            return {'url': url, 'label': label or name}
    return {'url': url, 'label': label or 'Open'}


def meeting(db, event_id):
    row = db.execute('SELECT url FROM calendar_event WHERE id=?', (event_id,)).fetchone()
    if row and row['url']:
        host = (urlsplit(row['url']).hostname or '').lower()
        return web(row['url'], 'Join meeting' if any(j in host for j in JOIN) else 'Open in Calendar')
    return None


def _has(db, table):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def for_task(db, task_id):
    if not task_id:
        return None
    if _has(db, 'discovered'):
        row = db.execute('SELECT source,key FROM discovered WHERE task_id=?', (task_id,)).fetchone()
        if row:
            source, key = row['source'].split(':')[0], row['key']
            if source == 'calendar':
                return meeting(db, key) or {'url': 'https://calendar.google.com/', 'label': 'Open in Calendar'}
            if source == 'apple_calendar':
                return meeting(db, 'apple:' + key) or {'url': 'paco-app:com.apple.iCal', 'label': 'Open Calendar'}
            if source == 'apple_reminders':
                return {'url': 'paco-app:com.apple.reminders', 'label': 'Open Reminders'}
            if source == 'tasks':                     # the key is an API address, not a page
                return {'url': 'https://tasks.google.com/', 'label': 'Open Google Tasks'}
            if source == 'outlook_calendar':
                return meeting(db, 'outlook:' + key) or {'url': 'https://outlook.office.com/calendar/', 'label': 'Open in Calendar'}
            link = web(key)
            if link:
                return link
    if _has(db, 'evidence'):
        row = db.execute("""SELECT url,source FROM evidence WHERE task=? AND deleted=0 AND url LIKE 'http%'
                            ORDER BY at DESC LIMIT 1""", (task_id,)).fetchone()
        if row:
            return web(row['url'], {'gmail': 'Open email', 'slack': 'Open in Slack', 'mattermost': 'Open in Mattermost'}.get(row['source']))
    if _has(db, 'meeting_item') and db.execute('SELECT 1 FROM meeting_item WHERE task=?', (task_id,)).fetchone():
        return {'url': '/meetings', 'label': 'Open meeting notes'}
    if _has(db, 'company_task_fields'):
        row = db.execute('SELECT source_url FROM company_task_fields WHERE task=?', (task_id,)).fetchone()
        if row:
            return web(row[0])
    return None


SOURCE_LABELS = {'github':'GitHub', 'mattermost':'Mattermost', 'chatgpt':'ChatGPT',
                 'calendar':'Calendar', 'gmail':'Gmail', 'drive':'Google Drive',
                 'tasks':'Tasks', 'slack':'Slack', 'meeting':'Meeting notes',
                 'mail':'Email', 'paco':'Paco', 'cloud':'Connected task'}


def source_for_task(db, task_id):
    """Recognizable origin, without exposing repository names or guessing an MCP client."""
    def result(source):
        return {'id': source, 'label': SOURCE_LABELS[source]}
    if not task_id:
        return result('paco')
    aliases = {'apple_calendar':'calendar', 'outlook_calendar':'calendar',
               'apple_reminders':'tasks', 'google_tasks':'tasks', 'google_drive':'drive',
               'outlook':'mail', 'chat':'paco'}
    if _has(db, 'discovered'):
        row = db.execute('SELECT source FROM discovered WHERE task_id=?', (task_id,)).fetchone()
        if row:
            source = row[0].split(':')[0]
            source = aliases.get(source, source)
            if source in SOURCE_LABELS:
                return result(source)
    if _has(db, 'evidence'):
        row = db.execute("SELECT source FROM evidence WHERE task=? AND deleted=0 ORDER BY at ASC LIMIT 1", (task_id,)).fetchone()
        if row:
            source = aliases.get(row[0], row[0])
            if source in SOURCE_LABELS:
                return result(source)
    if _has(db, 'meeting_item') and db.execute('SELECT 1 FROM meeting_item WHERE task=?', (task_id,)).fetchone():
        return result('meeting')
    link = for_task(db, task_id)
    host = (urlsplit(link['url']).hostname or '').lower() if link else ''
    for domain, source in [('github.com','github'), ('chatgpt.com','chatgpt'), ('chat.openai.com','chatgpt'),
                           ('mail.google.com','gmail'), ('drive.google.com','drive'), ('docs.google.com','drive'),
                           ('calendar.google.com','calendar'), ('tasks.google.com','tasks')]:
        if host == domain or host.endswith('.' + domain):
            return result(source)
    if _has(db, 'company_link') and db.execute("SELECT 1 FROM company_link WHERE kind='task' AND local=?", (task_id,)).fetchone():
        return result('cloud')
    return result('paco')
