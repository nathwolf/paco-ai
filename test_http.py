import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import app
import paco


class HTTP(unittest.TestCase):
    def setUp(self):
        self.presence = patch('app.presence.active', return_value=True)
        self.presence.start(); self.addCleanup(self.presence.stop)
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        with paco.connect(self.path) as db:app.initialize(db)
        self.server,self.token=app.make_server(self.path,paco.connect)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path='/api/state',body=None,auth=True,origin=None):
        headers={'Authorization':'Bearer '+self.token} if auth else {}
        if body is not None:headers.update({'X-Paco':'1','Content-Type':'application/json'})
        if origin:headers['Origin']=origin
        request=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        return urllib.request.urlopen(request,timeout=3)
    def test_unauthorized_and_cross_origin_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.request(auth=False)
        self.assertEqual(err.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/api/action',{'action':'add','title':'evil'},origin='https://evil.test')
        self.assertEqual(err.exception.code,403)
        self.assertEqual(json.load(self.request())['tasks'],[])
    def test_create_complete_and_restart(self):
        ident=json.load(self.request('/api/action',{'action':'add','title':'API task'}))['id']
        json.load(self.request('/api/action',{'action':'done','id':ident}))
        self.assertEqual(json.load(self.request())['tasks'][0]['state'],'done')
        with paco.connect(self.path) as db:self.assertEqual(db.execute('SELECT state FROM task').fetchone()[0],'done')
    def test_banner_rechecks_focus_even_during_holiday(self):
        import time
        now=time.time()
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO task VALUES(1,'urgent',5,'open',0,0)")
            db.execute('INSERT INTO urgency VALUES(1,1)')
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(1,'urgent','angry','urgent',?)",(now,))
            db.execute("INSERT INTO preference VALUES('mode','holiday')")
        self.assertEqual(json.load(self.request('/api/banner'))['task'],1)
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO task VALUES(2,'focusing',3,'focus',?,0)",(now+100,))
        self.assertIsNone(json.load(self.request('/api/banner')))
    def test_snooze_invalidates_queued_banner(self):
        import time
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO task VALUES(1,'queued',3,'open',0,0)")
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(1,'hello','friendly','ready',?)",(time.time()-1,))
        json.load(self.request('/api/action',{'action':'snooze','id':1}))
        self.assertIsNone(json.load(self.request('/api/banner')))
    def test_mac_focus_blocks_queued_preview_and_companion_then_resumes(self):
        import time,mac_focus
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,'Focus test','friendly','Notification preview',?)",(time.time(),))
            mac_focus.observe(db,True)
        self.assertTrue(json.load(self.request('/api/companion'))['quiet_focus'])
        self.assertIsNone(json.load(self.request('/api/banner')))
        self.assertEqual(json.load(self.request())['wait'],mac_focus.REASON)
        with paco.connect(self.path) as db:mac_focus.observe(db,False)
        self.assertFalse(json.load(self.request('/api/companion'))['quiet_focus'])
        self.assertEqual(json.load(self.request('/api/banner'))['message'],'Focus test')
    def test_calendar_banner_at_start_survives_own_busy_time_but_not_pause_or_cancellation(self):
        import time,calendar_alerts
        now=time.time()
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO calendar_event VALUES('call','work','Review',?,?,?,'','[]')",(now-1,now+1800,'https://teams.microsoft.com/meet/123456789'))
            db.execute('INSERT INTO busy VALUES(?,?)',(now-1,now+1800));db.commit()
            calendar_alerts.queue(db,now)
        banner=json.load(self.request('/api/banner'))
        self.assertEqual(banner['calendar_event']['provider'],'Teams')
        with paco.connect(self.path) as db:db.execute("INSERT INTO preference VALUES('mode','paused')")
        self.assertIsNone(json.load(self.request('/api/banner')))
        with paco.connect(self.path) as db:
            db.execute("DELETE FROM preference WHERE key='mode'")
            db.execute("DELETE FROM calendar_event WHERE id='call'")
        self.assertIsNone(json.load(self.request('/api/banner')))
    def test_session_suppresses_queued_urgent_alert_and_survives_state_refresh(self):
        import time
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO task VALUES(1,'urgent',5,'open',0,0)")
            db.execute('INSERT INTO urgency VALUES(1,1)')
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(1,'urgent','angry','urgent',?)",(time.time(),))
        session=json.load(self.request('/api/action',{'action':'focus_start','intention':'Write proposal','minutes':25}))
        self.assertEqual(json.load(self.request())['focus_session']['id'],session['id'])
        self.assertTrue(json.load(self.request('/api/companion'))['quiet_focus'])
        self.assertIsNone(json.load(self.request('/api/banner')))
        json.load(self.request('/api/action',{'action':'focus_stop','id':session['id']}))
        self.assertIsNone(json.load(self.request())['focus_session'])
        self.assertEqual(json.load(self.request('/api/banner'))['task'],1)
    def test_static_traversal_denied(self):
        with self.assertRaises(urllib.error.HTTPError) as err:self.request('/assets/../../app.py')
        self.assertEqual(err.exception.code,404)
    def test_companion_status_and_fifth_asset(self):
        status=json.load(self.request('/api/companion'))
        self.assertFalse(status['setup_complete'])
        self.assertEqual(len(status['expressions']),5)
        for expression in status['expressions'].values():
            with self.request('/assets/'+expression['file']) as response:
                self.assertEqual(response.status,200)
                self.assertEqual(response.read()[:8],b'\x89PNG\r\n\x1a\n')
    def test_default_entry_is_tasks_with_four_tabs_and_separate_controls(self):
        with self.request('/') as response:
            html=response.read().decode()
        for tab in ('tasks','meetings','sessions','controls'):
            self.assertIn('data-tab="'+tab+'"',html)
        self.assertIn('id="chat-form"',html)
        with self.request('/controls') as response:
            self.assertIn('Finish and keep Paco running',response.read().decode())
    def test_notification_reply_is_bound_idempotent_and_holds_queued_urgent_alerts(self):
        import time
        import uuid
        now=time.time()
        with paco.connect(self.path) as db:
            db.execute("INSERT INTO task VALUES(1,'First',3,'open',0,0)")
            db.execute("INSERT INTO task VALUES(2,'Urgent',5,'open',0,0)")
            db.execute('INSERT INTO urgency VALUES(2,1)')
            db.execute("INSERT INTO notification VALUES(1,1,'First','friendly','Ready',?,NULL)",(now,))
            db.execute("INSERT INTO notification VALUES(2,2,'Urgent','angry','Ready',?,NULL)",(now,))
        body={'action':'notification_reply','notification':1,'text':'remember me in 5 hrs I will be out','request':uuid.uuid4().hex}
        first=json.load(self.request('/api/action',body))
        self.assertIn('all other reminders',first['answer'])
        self.assertEqual(first,json.load(self.request('/api/action',body)))
        self.assertIsNone(json.load(self.request('/api/banner')))
        with paco.connect(self.path) as db:
            self.assertAlmostEqual(db.execute('SELECT due FROM task WHERE id=1').fetchone()[0],now+18000,delta=2)
            self.assertEqual(db.execute('SELECT due FROM task WHERE id=2').fetchone()[0],0)
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/action',body,auth=False)
    def test_flow_is_rechecked_for_already_queued_alerts(self):
        import time
        import flow
        with paco.connect(self.path) as db:
            flow.configure(db,{'enabled':True,'apps':'Code'})
            db.execute("INSERT INTO task VALUES(1,'Queued urgent task',5,'open',0,0)")
            db.execute('INSERT INTO urgency VALUES(1,1)')
            db.execute("INSERT INTO notification VALUES(1,1,'Queued urgent task','angry','Ready',?,NULL)",(time.time(),))
        def active(db):
            with db:flow.observe(db,dict(app='Code',bundle='editor',idle=0,locked=False),time.time())
        with patch('app.flow.sample',side_effect=active):
            self.assertIsNone(json.load(self.request('/api/banner')))
            json.load(self.request('/api/action',{'action':'flow_config','enabled':True,'apps':'Code','urgent_interrupts':True}))
            self.assertEqual(json.load(self.request('/api/banner'))['task'],1)
            with paco.connect(self.path) as db:db.execute('INSERT INTO busy VALUES(?,?)',(time.time()-10,time.time()+300))
            self.assertIsNone(json.load(self.request('/api/banner')))

    def test_queued_urgent_banner_rechecks_assignee_and_admission(self):
        import time,attention
        with paco.connect(self.path) as db:
            attention.add_identities(db,['nathalia'])
            db.execute("INSERT INTO task VALUES(1,'queued',5,'open',0,0)")
            db.execute('INSERT INTO urgency VALUES(1,1)')
            db.execute("INSERT INTO ownership VALUES(1,'juan','')")
            db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(1,'urgent','angry','urgent',?)",(time.time(),))
        self.assertIsNone(json.load(self.request('/api/banner')))
        with paco.connect(self.path) as db:
            db.execute("UPDATE ownership SET owner='nathalia'")
            attention.record(db,1,'suggested','Needs confirmation','gmail')
        self.assertIsNone(json.load(self.request('/api/banner')))
        with paco.connect(self.path) as db:attention.decision(db,1,'accept')
        self.assertEqual(json.load(self.request('/api/banner'))['task'],1)
