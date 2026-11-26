from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import json
import app
import flow
import paco
import planning


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        self.db=paco.connect(self.path);app.initialize(self.db);self.now=1000000
        with self.db:
            self.db.execute("INSERT INTO task VALUES(1,'Routine work',3,'open',0,0)")
            self.db.execute("INSERT INTO task VALUES(2,'Urgent work',5,'open',0,0)")
            self.db.execute('INSERT INTO urgency VALUES(2,1)')
        self.configure()
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def configure(self,**values):
        flow.configure(self.db,{**dict(enabled=True,apps='Code, Figma',pause_seconds=120,urgent_interrupts=False),**values})
    def observe(self,now=None,**values):
        meta={**dict(app='Code',bundle='com.example.Code',idle=2,locked=False),**values}
        with self.db:flow.observe(self.db,meta,self.now if now is None else now)
    def test_active_work_blocks_all_reminders_and_daily_plan(self):
        self.observe()
        self.assertEqual(planning.reason_to_wait(self.db,self.now),flow.FLOW_REASON)
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        self.assertEqual(planning.morning_plan(self.db,self.now),[])
        delivered=[];paco.tick(self.db,self.now,delivered.append)
        self.assertEqual(delivered,[])
        self.assertEqual(self.db.execute('SELECT count(*) FROM intervention').fetchone()[0],0)
    def test_codex_bundle_is_protected_when_macos_calls_it_chatgpt(self):
        self.configure(apps='Codex')
        self.observe(app='ChatGPT',bundle='com.openai.codex')
        self.assertEqual(flow.reason(self.db,self.now),flow.FLOW_REASON)
        import slacking
        self.assertTrue(slacking.is_work(self.db,{'app':'ChatGPT','bundle':'com.openai.codex'}))
    def test_sustained_work_then_natural_pause(self):
        for seconds in range(0,601,15):
            self.observe(self.now+seconds,idle=5)
            self.assertIsNone(planning.next_reminder(self.db,self.now+seconds))
        self.observe(self.now+615,idle=121)
        self.assertIsNotNone(planning.next_reminder(self.db,self.now+615))
    def test_work_app_switch_and_brief_other_app_switch(self):
        self.observe();self.observe(self.now+15,app='Figma')
        self.assertEqual(flow.reason(self.db,self.now+15),flow.FLOW_REASON)
        self.observe(self.now+30,app='Browser')
        self.assertEqual(flow.reason(self.db,self.now+30),flow.FLOW_REASON)
        self.observe(self.now+45,app='Browser')
        self.assertEqual(flow.reason(self.db,self.now+45),flow.FLOW_REASON)
        self.observe(self.now+61,app='Browser')
        self.assertIsNone(flow.reason(self.db,self.now+61))
    def test_explicit_urgent_override_never_bypasses_manual_focus(self):
        self.configure(urgent_interrupts=True);self.observe()
        self.assertEqual(planning.next_reminder(self.db,self.now)['id'],2)
        with self.db:self.db.execute("UPDATE task SET state='focus',due=? WHERE id=1",(self.now+600,))
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_flow_still_protects_during_holiday(self):
        with self.db:self.db.execute("INSERT INTO preference VALUES('mode','holiday')")
        self.observe();self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_idle_and_locked_suppress_even_urgent_override(self):
        self.configure(urgent_interrupts=True)
        for meta in ({'idle':700},{'locked':True,'idle':0}):
            self.observe(**meta)
            self.assertEqual(flow.reason(self.db,self.now,critical=True),flow.AWAY_REASON)
            self.assertIsNone(planning.next_reminder(self.db,self.now))
        self.observe(self.now+15,idle=0,locked=False)
        self.assertEqual(flow.reason(self.db,self.now+15),flow.FLOW_REASON)
    def test_stale_and_future_state_never_hold_forever(self):
        self.observe()
        self.assertIsNone(flow.reason(self.db,self.now+46))
        self.assertIsNone(flow.reason(self.db,self.now-1))
    def test_disable_clears_metadata_and_does_not_read_activity(self):
        self.observe();self.configure(enabled=False)
        with self.db:self.db.execute("INSERT OR REPLACE INTO preference VALUES('callout','off')")
        read=Mock();flow.sample(self.db,self.now+15,reader=read)
        read.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM flow_state').fetchone()[0],0)
        self.assertIsNotNone(planning.next_reminder(self.db,self.now))
    def test_debounce_failures_and_disable_during_sampling(self):
        read=Mock(return_value=dict(app='Code',bundle='com.example.Code',idle=0,locked=False))
        flow.sample(self.db,self.now,reader=read);flow.sample(self.db,self.now+5,reader=read)
        self.assertEqual(read.call_count,1)
        flow.sample(self.db,self.now+15,reader=Mock(side_effect=OSError('unavailable')))
        self.assertIsNone(flow.reason(self.db,self.now+15))
        self.assertIn('unavailable',flow.status(self.db,self.now+15)['message'])
        def revoke():
            self.configure(enabled=False)
            return dict(app='Code',bundle='com.example.Code',idle=0,locked=False)
        flow.sample(self.db,self.now+30,reader=revoke)
        self.assertEqual(self.db.execute('SELECT count(*) FROM flow_state').fetchone()[0],0)
    def test_only_latest_minimal_snapshot_is_retained(self):
        self.observe(title='private title',text='private text',keys='private keys')
        self.observe(self.now+15,app='Figma')
        rows=[dict(r) for r in self.db.execute('SELECT * FROM flow_state')]
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['app'],'Figma')
        self.assertNotIn('private',json.dumps(rows))
        self.assertEqual(self.db.execute('SELECT count(*) FROM evidence').fetchone()[0],0)
    def test_new_install_is_off_and_validation_rejects_bad_preferences(self):
        with self.db:self.db.execute("DELETE FROM preference WHERE key='flow_protection'")
        # Call-outs are on by default, so the activity check still runs; flow protection itself stays off.
        read=Mock(return_value=dict(app='Code',bundle='com.example.Code',idle=0,locked=False))
        flow.sample(self.db,self.now,reader=read);read.assert_called_once()
        self.assertIsNone(flow.reason(self.db,self.now))
        with self.db:self.db.execute("INSERT OR REPLACE INTO preference VALUES('callout','off')")
        read=Mock();flow.sample(self.db,self.now+20,reader=read);read.assert_not_called()
        for values in ({'apps':''},{'pause_seconds':-1},{'enabled':'yes'},{'urgent_interrupts':'yes'}):
            with self.assertRaises(ValueError):self.configure(**values)
    def test_bad_native_signal_is_not_interpreted_as_focus(self):
        for idle in (-1, float('nan'), '0', True):
            flow.sample(self.db,self.now,reader=lambda:dict(app='Code',bundle='com.example.Code',idle=idle,locked=False))
            self.assertIsNone(flow.reason(self.db,self.now));self.now+=15
