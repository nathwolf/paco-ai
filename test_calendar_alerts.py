import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import app,paco,calendar_alerts as alerts,calendar_sync,meeting_identity


class CalendarAlerts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db';self.db=paco.connect(self.path);app.initialize(self.db);calendar_sync.initialize(self.db);self.addCleanup(self.db.close)
        self.now=time.time()
    def event(self,ident='meeting',title='Project review',start=None,url='https://meet.google.com/abc-defg-hij'):
        start=self.now+300 if start is None else start
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',(ident,'work',title,start,start+1800,url,'','[]'))
        return start
    def last(self):return self.db.execute('SELECT * FROM notification ORDER BY id DESC LIMIT 1').fetchone()
    def test_alerts_do_not_require_tasks_and_only_fire_once_per_stage(self):
        start=self.event()
        self.assertEqual(alerts.queue(self.db,self.now),1)
        self.assertEqual(alerts.queue(self.db,self.now+1),0)
        value=app.banner_payload(self.db,self.last(),self.now)
        self.assertEqual(value['calendar_event']['provider'],'Google Meet')
        self.assertIsNone(value['task'])
        self.assertEqual(alerts.queue(self.db,start),1)
        self.assertEqual(alerts.queue(self.db,start+1),0)
        self.assertEqual(alerts.queue(self.db,start+301),0)
    def test_event_reminders_but_not_placeholder_or_focus_blocks(self):
        for i,title in enumerate(('Print documents','x','Focus time','Lunch')):
            self.event(str(i),title,url='https://calendar.google.com/calendar/event?id='+str(i))
        self.assertEqual(alerts.queue(self.db,self.now),1)
        p=alerts.payload(self.db,self.last()['id'],self.now)
        self.assertEqual(p['title'],'Print documents');self.assertIsNone(p['join_url'])
    def test_focus_pause_hidden_events_and_foreign_calendars(self):
        self.event()
        with self.db:self.db.execute("INSERT OR REPLACE INTO preference VALUES('mode','paused')")
        self.assertEqual(alerts.queue(self.db,self.now),0)
        with self.db:self.db.execute("DELETE FROM preference WHERE key='mode'")
        import mac_focus
        mac_focus.observe(self.db,True,self.now);self.assertEqual(alerts.queue(self.db,self.now),0)
        mac_focus.observe(self.db,False,self.now)
        meeting_identity.calendar_visibility(self.db,'meeting',False)
        self.assertEqual(alerts.queue(self.db,self.now),0)
        meeting_identity.calendar_visibility(self.db,'meeting',True)
        with self.db:self.db.execute('INSERT INTO calendar_task_context VALUES(?,?)',('meeting',json.dumps({'account_email':'me@example.test','creator':{'email':'juan@example.test'}})))
        self.assertEqual(alerts.queue(self.db,self.now),0)
    def test_deleted_rescheduled_and_expired_alerts_cannot_join(self):
        self.event();alerts.queue(self.db,self.now);ident=self.last()['id']
        self.assertIsNone(alerts.payload(self.db,ident,self.now+3601))
        self.event(start=self.now+800)
        self.assertIsNone(alerts.payload(self.db,ident,self.now))
        with self.db:self.db.execute('DELETE FROM calendar_event')
        self.assertIsNone(alerts.payload(self.db,ident,self.now))
    def test_calendar_move_preserves_alert_history(self):
        self.event('primary:one');alerts.queue(self.db,self.now)
        with self.db:
            calendar_sync.rekey(self.db,'primary:one','personal:one',self.now)
            self.db.execute("UPDATE calendar_event SET id='personal:one'")
        self.assertEqual(alerts.queue(self.db,self.now+1),0)
        self.assertEqual(alerts.payload(self.db,self.last()['id'],self.now)['id'],'personal:one')
    def test_join_uses_current_calendar_data_and_requires_explicit_action(self):
        self.event();alerts.queue(self.db,self.now)
        with patch('app.meeting_audio.start',return_value={'id':'capture'}) as capture:
            app.banner_payload(self.db,self.last(),self.now);capture.assert_not_called()
            value=app.act(self.db,self.path,paco.connect,{'action':'calendar_join','notification':self.last()['id']})
            self.assertEqual(value['join_url'],'https://meet.google.com/abc-defg-hij')
            self.assertEqual(capture.call_args.args[2]['calendar_event'],'meeting')
            self.assertFalse(capture.call_args.args[2]['microphone_only'])
        with self.db:self.db.execute('DELETE FROM calendar_event')
        with self.assertRaises(ValueError):app.act(self.db,self.path,paco.connect,{'action':'calendar_join','notification':self.last()['id']})


class JoinLinks(unittest.TestCase):
    def test_structured_and_embedded_links_all_three_providers(self):
        examples=[('https://meet.google.com/abc-defg-hij','Google Meet'),
                  ('https://us02web.zoom.us/j/123456789?pwd=secret','Zoom'),
                  ('https://teams.microsoft.com/l/meetup-join/abc?context=def','Teams'),
                  ('https://teams.microsoft.com/meet/123456789?p=abc','Teams'),
                  ('https://teams.live.com/meet/123456789','Teams'),
                  ('https://teams.cloud.microsoft/meet/123456789','Teams')]
        for url,expected in examples:
            with self.subTest(url=url):
                self.assertEqual(alerts.provider(url),expected)
                self.assertEqual(alerts.join_url({'conferenceData':{'entryPoints':[{'entryPointType':'video','uri':url}]}}),url)
                self.assertEqual(alerts.join_url({'description':'Join: <a href="'+url+'">call</a>'}),url)
    def test_rejects_deceptive_domains_and_non_call_pages(self):
        for url in ('https://zoom.us.evil.test/j/123','https://teams.microsoft.com.evil.test/meet/123',
                    'https://evil.test/meet.google.com/abc-defg-hij','https://user:pass@zoom.us/j/123',
                    'javascript:alert(1)','https://zoom.us/','https://teams.microsoft.com/meetingOptions','http://meet.google.com/abc-defg-hij'):
            with self.subTest(url=url):self.assertIsNone(alerts.provider(url))
