"""Readiness: take-me-there links, projects and focus days, meeting reminders, resting while away,
noticing finished work, and the new sources."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import app
import connectors
import discovery
import flow
import links
import paco
import planning
import presence
import tagging

NOW = datetime(2026, 11, 25, 11, 0).timestamp()      # Wednesday 11:00, inside working hours


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = paco.connect(Path(self.tmp.name) / 'db')
        app.initialize(self.db)
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO preference VALUES(?,?)', [('hours', '9-18'), ('workdays', '0,1,2,3,4'), ('notification_gap', '60')])
            self.db.execute('CREATE TABLE IF NOT EXISTS discovered(source TEXT, key TEXT, task_id INTEGER, scheduled REAL, PRIMARY KEY(source,key))')

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def task(self, title, source=None, key=None, due=NOW - 60, critical=0, deadline=None):
        with self.db:
            ident = self.db.execute("INSERT INTO task(title,priority,state,due) VALUES(?,3,'open',?)", (title, due)).lastrowid
            self.db.execute('INSERT INTO urgency VALUES(?,?)', (ident, critical))
            if deadline:
                self.db.execute("INSERT INTO details VALUES(?,'',30,?)", (ident, deadline))
            if source:
                self.db.execute('INSERT INTO discovered VALUES(?,?,?,?)', (source, key, ident, due))
        return ident


class Links(Base):
    def test_every_source_has_somewhere_to_go(self):
        with self.db:
            self.db.execute("INSERT INTO calendar_event VALUES('primary:ev1','primary','Standup',?,?,'https://meet.google.com/abc-defg-hij','',?)", (NOW + 600, NOW + 1500, '[]'))
            self.db.execute("INSERT INTO calendar_event VALUES('outlook:ev2','outlook','Client call',?,?,'https://teams.microsoft.com/l/meetup-join/x','',?)", (NOW + 600, NOW + 1500, '[]'))
        cases = {
            ('github', 'https://github.com/acme/app/issues/7'): ('https://github.com/acme/app/issues/7', 'Open in GitHub'),
            ('jira:acc', 'https://acme.atlassian.net/browse/ACME-1'): ('https://acme.atlassian.net/browse/ACME-1', 'Open in Jira'),
            ('gitlab:7', 'https://gitlab.com/acme/app/-/issues/3'): ('https://gitlab.com/acme/app/-/issues/3', 'Open in GitLab'),
            ('calendar', 'primary:ev1'): ('https://meet.google.com/abc-defg-hij', 'Join meeting'),
            ('outlook_calendar', 'ev2'): ('https://teams.microsoft.com/l/meetup-join/x', 'Join meeting'),
            ('apple_reminders', 'icloud/1'): ('paco-app:com.apple.reminders', 'Open Reminders'),
            ('tasks', 'https://tasks.googleapis.com/tasks/v1/lists/x/tasks/y'): ('https://tasks.google.com/', 'Open Google Tasks'),
        }
        for (source, key), expected in cases.items():
            ident = self.task('Task from ' + source, source, key)
            link = links.for_task(self.db, ident)
            self.assertEqual((link['url'], link['label']), expected, source)

    def test_email_tasks_open_the_thread_and_nothing_unsafe_is_returned(self):
        import workflows
        ident = self.task('Send the contract')
        workflows.remember(self.db, 'gmail', 'me/t1/m1/q', 'Can you send the contract?', 'https://mail.google.com/mail/u/0/#all/t1', 'ana@client.com', task=ident)
        self.assertEqual(links.for_task(self.db, ident), {'url': 'https://mail.google.com/mail/u/0/#all/t1', 'label': 'Open email'})
        evil = self.task('Bad', 'todoist:1', 'javascript:alert(1)')
        self.assertIsNone(links.for_task(self.db, evil))

    def test_banner_offers_open(self):
        ident = self.task('Fix login', 'github', 'https://github.com/acme/app/issues/9')
        with self.db:
            self.db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(?,?,?,?,?)", (ident, 'Time to start: Fix login', 'friendly', 'x', NOW))
        value = app.banner_payload(self.db, self.db.execute('SELECT * FROM notification').fetchone(), NOW)
        self.assertEqual(value['link']['label'], 'Open in GitHub')
        self.assertEqual(value['labels']['open'], 'Open')


class Projects(Base):
    def test_hints_tag_tasks_and_the_banner_says_which_project(self):
        a = tagging.save_project(self.db, {'name': 'Client A', 'area': 'Consulting', 'hints': '@clienta.com, github.com/clienta/'})
        tagging.save_project(self.db, {'name': 'Paco', 'area': 'Development', 'hints': 'github.com/me/paco'})
        issue = self.task('Fix export', 'github', 'https://github.com/clienta/portal/issues/4')
        mail = self.task('Send invoice')
        with self.db:
            self.db.execute("INSERT INTO ownership VALUES(?,?,?)", (mail, 'me', 'Ana <ana@clienta.com>'))
        loose = self.task('Water the plants')
        tagging.retag(self.db)
        self.assertEqual(tagging.of_task(self.db, issue)['name'], 'Client A')
        self.assertEqual(tagging.of_task(self.db, mail)['id'], a)
        self.assertIsNone(tagging.of_task(self.db, loose))
        with self.db:
            self.db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(?,?,?,?,?)", (issue, 'Time to start: Fix export', 'friendly', 'x', NOW))
        value = app.banner_payload(self.db, self.db.execute('SELECT * FROM notification').fetchone(), NOW)
        self.assertIn({'text': 'Client A', 'tone': 'blue'}, value['badges'])

    def test_model_sorts_the_rest_only_with_permission_and_manual_wins(self):
        tagging.save_project(self.db, {'name': 'Marketing site', 'area': 'Marketing'})
        ident = self.task('Write launch blog post')
        calls = []
        def fake(config, system, data, source):
            calls.append(data)
            return {'assignments': [{'id': ident, 'project': 'Marketing site', 'confidence': 'high', 'reason': 'Launch copy for this site'}]}, {}
        tagging.retag(self.db, {'provider': 'anthropic', 'model': 'm', 'allowed_sources': []}, fake)
        self.assertEqual(calls, [])                                    # no tasks permission: nothing sent
        tagging.retag(self.db, {'provider': 'anthropic', 'model': 'm', 'allowed_sources': ['chat']}, fake)
        self.assertEqual(tagging.of_task(self.db, ident)['name'], 'Marketing site')
        self.assertEqual(tagging.of_task(self.db, ident)['how'], 'model')
        tagging.tag(self.db, ident, None)
        tagging.retag(self.db, {'provider': 'ollama', 'model': 'm'}, fake)
        self.assertIsNone(tagging.of_task(self.db, ident))               # your choice stays

    def test_focus_day_silences_other_projects_but_not_urgent_work(self):
        a = tagging.save_project(self.db, {'name': 'Client A', 'hints': 'clienta'})
        tagging.save_project(self.db, {'name': 'Client B', 'hints': 'clientb'})
        b_task = self.task('clientb: update deck', due=NOW - 600)
        tagging.retag(self.db)
        tagging.set_focus(self.db, a, NOW)
        self.assertIsNone(planning.next_reminder(self.db, NOW))
        urgent = self.task('clientb: server down', due=NOW - 300, critical=1)
        tagging.retag(self.db)
        self.assertEqual(planning.next_reminder(self.db, NOW)['id'], urgent)
        a_task = self.task('clienta: proposal', due=NOW - 900)
        tagging.retag(self.db)
        with self.db:
            self.db.execute('UPDATE urgency SET critical=0 WHERE task=?', (urgent,))
        self.assertEqual(planning.next_reminder(self.db, NOW)['id'], a_task)
        self.assertEqual([p['id'] for p in planning.morning_plan(self.db, NOW)], [a_task])
        self.assertIsNone(tagging.focus(self.db, tagging.end_of_day(NOW) + 1))   # ends with the day
        self.assertNotIn(b_task, [p['id'] for p in planning.morning_plan(self.db, NOW)])


class Meetings(Base):
    def meeting(self, minutes_away=10):
        start = NOW + minutes_away * 60
        with self.db:
            self.db.execute("INSERT INTO calendar_event VALUES('primary:m1','primary','Client call',?,?,'https://meet.google.com/x-y-z','',?)", (start, start + 1800, '[]'))
        return self.task('Prepare for Client call', 'calendar', 'primary:m1', due=start - 900)

    def test_meeting_reminder_gets_through_flow_and_focus_with_a_join_link(self):
        ident = self.meeting()
        flow.configure(self.db, {'enabled': True, 'apps': 'Xcode', 'pause_seconds': 120})
        with self.db:
            flow.observe(self.db, {'app': 'Xcode', 'bundle': 'com.apple.dt.Xcode', 'idle': 1, 'locked': False}, NOW)
            self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Deep work',3,'focus',?)", (NOW + 1500,))
        self.assertEqual(planning.next_reminder(self.db, NOW)['id'], ident)
        with self.db:
            self.db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(?,?,?,?,?)", (ident, 'Time to start: Prepare for Client call', 'friendly', 'x', NOW))
        value = app.banner_payload(self.db, self.db.execute('SELECT * FROM notification').fetchone(), NOW)
        self.assertEqual(value['badges'][0], {'text': 'Starts in 10 min', 'tone': 'blue'})
        self.assertEqual(value['link'], {'url': 'https://meet.google.com/x-y-z', 'label': 'Join meeting'})

    def test_holiday_and_pause_still_win(self):
        self.meeting()
        for mode in ('holiday', 'paused'):
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO preference VALUES('mode',?)", (mode,))
            self.assertIsNone(planning.next_reminder(self.db, NOW), mode)


class Finished(Base):
    def test_gone_from_a_tracker_asks_whether_it_is_done(self):
        discovery.reconcile(self.db, 'todoist:1', [('https://app.todoist.com/app/task/1', 'Pay rent', NOW)], NOW)
        discovery.reconcile(self.db, 'todoist:1', [], NOW + 300)
        task = self.db.execute('SELECT id,state FROM task').fetchone()
        self.assertEqual(task['state'], 'unavailable')                 # reminders stop
        self.assertTrue(self.db.execute("SELECT 1 FROM source_event WHERE task=? AND outcome='suggested_completion'", (task['id'],)).fetchone())
        discovery.reconcile(self.db, 'calendar', [('primary:x', 'Prepare for X', NOW)], NOW)
        discovery.reconcile(self.db, 'calendar', [], NOW + 300)
        self.assertEqual(self.db.execute("SELECT count(*) FROM source_event WHERE outcome='suggested_completion'").fetchone()[0], 1)


class Resting(Base):
    def test_signals(self):
        self.assertEqual(presence.evaluate({'locked': True}), (False, 'Screen locked'))
        self.assertEqual(presence.evaluate({'locked': False, 'on_console': False})[0], False)
        self.assertEqual(presence.evaluate({'locked': False, 'on_console': True, 'displays': 0}), (False, 'Display asleep or lid closed'))
        self.assertEqual(presence.evaluate({'locked': False, 'on_console': True, 'displays': 1}), (True, None))   # lid closed + monitor
        self.assertEqual(presence.check(reader=lambda: (_ for _ in ()).throw(OSError())), (True, None))      # unknown: stay on

    def test_loops_skip_their_work_while_resting(self):
        stop, ran, checks = threading.Event(), [], []
        def gate():
            checks.append(1)
            if len(checks) >= 3:
                stop.set()
            return False
        app.run_loop('reminders', stop, 0, lambda: ran.append(1), gate=gate)
        self.assertEqual(ran, [])

    def test_no_banner_while_resting(self):
        server, token = app.make_server(Path(self.tmp.name) / 'db', paco.connect)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            self.task('Anything')
            with self.db:
                self.db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,'x','friendly','Notification preview',strftime('%s','now'))")
            import urllib.request
            request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/api/banner', headers={'Authorization': 'Bearer ' + token})
            with patch.object(presence, 'active', return_value=False):
                self.assertIsNone(json.load(urllib.request.urlopen(request, timeout=3)))
            with patch.object(presence, 'active', return_value=True):
                self.assertIsNotNone(json.load(urllib.request.urlopen(request, timeout=3)))
        finally:
            server.shutdown(); server.server_close()


class Sources(unittest.TestCase):
    class Client:
        def __init__(self, routes, base='https://x'):
            self.routes, self.base, self.headers, self.seen = routes, base, {}, []
        def get(self, path, **params):
            self.seen.append((path, params))
            value = self.routes[path]
            return value(params) if callable(value) else value
        def post(self, path, data):
            self.seen.append((path, data))
            return self.routes[path](data)

    def test_gitlab_issues_and_review_requests(self):
        client = self.Client({'/user': {'id': 7},
            '/issues': [{'web_url': 'https://gitlab.com/a/b/-/issues/1', 'title': 'Bug'}],
            '/merge_requests': [{'web_url': 'https://gitlab.com/a/b/-/merge_requests/2', 'title': 'Feature'}]})
        rows = connectors.snapshot('gitlab', client, '7', 0)
        self.assertEqual([r[:2] for r in rows], [('https://gitlab.com/a/b/-/issues/1', 'Bug'), ('https://gitlab.com/a/b/-/merge_requests/2', 'Review: Feature')])
        self.assertEqual(client.seen[2][1]['reviewer_id'], '7')
        with self.assertRaises(ValueError):
            connectors.configure('gitlab', 't', 'http://insecure.example')

    def test_linear_and_microsoft_todo(self):
        page = {'data': {'viewer': {'assignedIssues': {'nodes': [
            {'url': 'https://linear.app/a/issue/A-1', 'identifier': 'A-1', 'title': 'Ship', 'state': {'type': 'started'}},
            {'url': 'https://linear.app/a/issue/A-2', 'identifier': 'A-2', 'title': 'Old', 'state': {'type': 'completed'}}],
            'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}
        linear = self.Client({'/graphql': lambda d: {'data': {'viewer': {'id': 'u1'}}} if 'viewer { id }' in d['query'] else page})
        self.assertEqual([r[1] for r in connectors.snapshot('linear', linear, 'u1', 0)], ['A-1 Ship'])
        self.assertEqual(connectors.client_for('linear', 'https://api.linear.app', 'lin_key').headers['Authorization'], 'lin_key')
        todo = self.Client({'/me': {'id': 'me'}, '/me/todo/lists': {'value': [{'id': 'L1'}]}, '/me/todo/lists/L1/tasks': {'value': [{'id': 'T1', 'title': 'Call bank'}]}})
        self.assertEqual(connectors.snapshot('microsoft_todo', todo, 'me', 0), [('https://to-do.office.com/tasks/id/T1/details', 'Call bank', 0)])

    def test_outlook_calendar_events(self):
        events = {'value': [
            {'id': 'e1', 'subject': 'Client call', 'start': {'dateTime': '2026-11-25T10:00:00.0000000'}, 'end': {'dateTime': '2026-11-25T10:30:00.0000000'},
             'showAs': 'busy', 'onlineMeeting': {'joinUrl': 'https://teams.microsoft.com/l/x'}, 'attendees': [{'emailAddress': {'address': 'a@c.com'}}]},
            {'id': 'e2', 'subject': 'Declined', 'start': {'dateTime': '2026-11-25T12:00:00'}, 'end': {'dateTime': '2026-11-25T13:00:00'}, 'responseStatus': {'response': 'declined'}},
            {'id': 'e3', 'subject': 'Holiday', 'isAllDay': True, 'start': {'dateTime': '2026-11-26T00:00:00'}, 'end': {'dateTime': '2026-11-27T00:00:00'}}]}
        client = self.Client({'/me': {'id': 'me'}, '/me/calendarView': events})
        [event] = connectors.outlook_events(client, 'me', NOW)
        self.assertEqual((event['title'], event['url'], event['busy'], event['attendees']), ('Client call', 'https://teams.microsoft.com/l/x', True, ['a@c.com']))
        self.assertEqual(datetime.utcfromtimestamp(event['start']).hour, 10)


if __name__ == '__main__':
    unittest.main()
