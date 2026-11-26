from datetime import datetime
from pathlib import Path
import tempfile
import unittest

import discovery
import paco
import planning


class Adaptive(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'tasks.db'
        self.db=paco.connect(self.path)
        self.now=datetime(2026,11,25,10).timestamp()
        self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Minor overdue thing',5,'open',0)")
        self.db.execute('INSERT INTO details VALUES(1,NULL,25,?)',(self.now-7*86400,))
        self.db.commit()
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def pref(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO preference VALUES(?,?)',(key,value))
    def test_holiday_does_not_turn_age_or_priority_into_emergency(self):
        self.pref('mode','holiday')
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        with self.db:self.db.execute('INSERT INTO urgency VALUES(1,1)')
        self.assertEqual(planning.next_reminder(self.db,self.now)['id'],1)
        self.pref('mode','paused')
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_holiday_does_not_mask_focus_or_meeting(self):
        self.pref('mode','holiday')
        with self.db:
            self.db.execute('INSERT INTO urgency VALUES(1,1)')
            self.db.execute('INSERT INTO busy VALUES(?,?)',(self.now-100,self.now+100))
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        with self.db:
            self.db.execute('DELETE FROM busy')
            self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Focus',3,'focus',?)",(self.now+100,))
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_scheduled_holiday_and_weekend(self):
        with self.db:self.db.execute("INSERT INTO absence VALUES('holiday',?,?,'Vacation','manual')",(self.now-1,self.now+10))
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        self.assertIsNotNone(planning.next_reminder(self.db,self.now+10))
        self.pref('workdays','0,1')
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_urgent_respects_snooze_and_dependencies(self):
        with self.db:
            self.db.execute('INSERT INTO urgency VALUES(1,1)')
            self.db.execute('UPDATE task SET due=?',(self.now+100,))
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        with self.db:
            self.db.execute('UPDATE task SET due=0')
            self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Prerequisite',3,'unavailable',0)")
        planning.add_dependency(self.db,1,2)
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_snoozes_back_off_and_expression_tracks_real_urgency(self):
        with self.db:
            self.db.executemany("INSERT INTO intervention VALUES(1,'snooze',?)",[(self.now-30,),(self.now-20,),(self.now-10,)])
        task=planning.ranked(self.db,self.now).fetchone()
        self.assertEqual(planning.reminder_delay(self.db,task,self.now),3600)
        self.assertEqual(planning.presentation(task,self.now)[0],'angry')
        with self.db:self.db.execute('UPDATE task SET priority=2')
        task=planning.ranked(self.db,self.now).fetchone()
        self.assertEqual(planning.presentation(task,self.now)[0],'impatient')
    def test_missing_snapshot_never_releases_dependency(self):
        discovery.reconcile(self.db,'github',[('a','External prerequisite',0)],self.now)
        planning.add_dependency(self.db,1,2)
        discovery.reconcile(self.db,'github',[],self.now+10)
        self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=2').fetchone()[0],'unavailable')
        self.assertIsNone(planning.next_reminder(self.db,self.now+10))
        discovery.reconcile(self.db,'github',[('a','External prerequisite',0)],self.now+20)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],2)
    def test_failed_snapshot_does_not_mutate(self):
        def broken():
            yield ('a','Should not exist',0)
            raise RuntimeError('network')
        with self.assertRaises(RuntimeError):discovery.reconcile(self.db,'github',broken(),self.now)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
    def test_plan_fits_meetings_and_end_of_day(self):
        self.pref('hours','9-11')
        with self.db:
            self.db.execute('INSERT INTO busy VALUES(?,?)',(self.now+900,self.now+1800))
            self.db.execute("INSERT INTO task(title,priority,state,due) VALUES('Long',3,'open',0)")
            self.db.execute('INSERT INTO details VALUES(2,NULL,120,NULL)')
        plan=planning.morning_plan(self.db,self.now)
        self.assertEqual(len(plan),1)
        self.assertEqual(plan[0]['start'],self.now+1800)
        self.assertLessEqual(plan[0]['end'],self.now+3600)
