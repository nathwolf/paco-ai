from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
import paco
import planning
import scheduled_checks as checks
import task_relationships as relationships
import workflows
import workspace


class ReminderSessions(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db=paco.connect(Path(folder.name)/'tasks')
        self.addCleanup(self.db.close)
        app.initialize(self.db)
        relationships.initialize(self.db)
        self.now=datetime(2026,11,27,12).timestamp()
        with self.db:
            for key,value in [('hours','0-24'),('workdays','0,1,2,3,4,5,6')]:
                self.db.execute('INSERT OR REPLACE INTO preference VALUES(?,?)',(key,value))
        self.config={'provider':'codex_cli','allowed_sources':['chat']}

    def task(self,title):
        i=workspace.edit_task(self.db,{'changes':{'title':title}})['id']
        with self.db:self.db.execute('UPDATE task SET due=? WHERE id=?',(self.now-5,i))
        return i

    def test_due_group_waits_for_focus_and_stays_independently_completable(self):
        a=self.task('Check the application portal')
        b=self.task('Check the funding deadline')
        with self.db:
            for i in (a,b):checks.schedule(self.db,i,self.now,'Application checks',self.now-40)
        checks.queue(self.db,self.now-1)
        with patch('mac_focus.active',return_value=True):checks.queue(self.db,self.now)
        self.assertIsNone(self.db.execute('SELECT id FROM notification').fetchone())
        checks.queue(self.db,self.now+1)
        checks.queue(self.db,self.now+20)
        note,=self.db.execute('SELECT * FROM notification').fetchall()
        self.assertEqual(app.banner_payload(self.db,note,self.now+1)['title'],'Application checks')
        self.assertEqual(checks.current(self.db,note['id'],self.now+1),[a,b])
        workflows.correct_task(self.db,a,state='done')
        self.assertEqual(checks.current(self.db,note['id'],self.now+21),[b])
        app.act(self.db,None,None,{'action':'ack','id':note['id']})
        self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(b,)).fetchone()[0],'open')
        checks.queue(self.db,self.now+360)
        self.assertEqual(self.db.execute('SELECT count(*) FROM notification').fetchone()[0],1)

    def test_only_new_grounded_incoming_booking_releases_waiting_task(self):
        i=self.task('Arrive for booked interview')
        with self.db:
            self.db.execute('INSERT INTO reminder_condition VALUES(?,?,?,?,?,?,?,?)',(i,'gmail','inbox','booking@example.test','','Confirmed booking',1800,self.now))
            self.db.execute("UPDATE task SET state='blocked' WHERE id=?",(i,))
        self.assertFalse(checks.conditions(self.db,'gmail','another'))
        watches=checks.conditions(self.db,'gmail','inbox')
        date=datetime.fromtimestamp(self.now+86400).astimezone()
        msg=dict(id='m',sent=False,date=str(int((self.now+2)*1000)),text='Appointment confirmed '+date.strftime('%Y-%m-%d at %H:%M'),sender='booking@example.test')
        signal=dict(task=i,message='m',quote=msg['text'],event_time=date.isoformat())
        for bad in [dict(msg,sent=True),dict(msg,sender='other@example.test'),dict(msg,date='10'),dict(msg,text='Unrelated')]:
            checks.release(self.db,watches,[signal],[bad],self.now+5)
            self.assertTrue(checks.conditions(self.db,'gmail','inbox'))
        with self.db:
            checks.release(self.db,watches,[signal],[msg],self.now+5)
            checks.release(self.db,watches,[signal],[msg],self.now+10)
        row=self.db.execute('SELECT state,due FROM task WHERE id=?',(i,)).fetchone()
        self.assertEqual(tuple(row),('open',date.timestamp()-1800))
        self.assertEqual(self.db.execute("SELECT count(*) FROM intervention WHERE action='snooze'").fetchone()[0],1)

    def test_acknowledging_fallback_waits_for_evidence_and_respects_later_completion(self):
        i=self.task('Check the workshop decision')
        with self.db:
            self.db.execute('INSERT INTO reminder_condition VALUES(?,?,?,?,?,?,?,?)',(i,'mattermost','account/channel','','workshop','Organizer approves',0,self.now-1))
            checks.schedule(self.db,i,self.now,'Check workshop decision',self.now-20)
        checks.queue(self.db,self.now)
        note=self.db.execute('SELECT id FROM notification').fetchone()[0]
        with self.db:checks.acknowledge(self.db,note,self.now)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'blocked')
        watches=checks.conditions(self.db,'mattermost','account/channel')
        workflows.correct_task(self.db,i,state='done')
        checks.release(self.db,watches,[dict(task=i,message='m',quote='Workshop approved')],[dict(id='m',text='Workshop approved',mine=False,at=self.now+5)],self.now+5)
        self.assertFalse(self.db.execute('SELECT 1 FROM scheduled_check').fetchone())

    def test_learning_applies_to_new_work_once_preserving_explicit_schedules(self):
        a=self.task('Check the original funding portal')
        with self.db:checks.remember(self.db,'Check portal','One-time application review',[a],self.now+3600)
        b=self.task('Check the next funding portal')
        c=self.task('Check another funding portal')
        d=self.task('Check a portal with an explicit snooze')
        with self.db:checks.schedule(self.db,d,self.now+240,'My explicit slot',self.now-1)
        def proposal(ids):
            return dict(tasks=ids,example=1,confidence='high',label='Check portals',
                        quotes=[dict(task=i,quote='portal') for i in ids])
        model=Mock(return_value=({'merges':[],'checks':[proposal([a]),proposal([d]),proposal([b,c])],
                     'groups':[proposal([b,c])]},{}))
        with patch('task_relationships.time.time',return_value=self.now):relationships.reconcile(self.db,self.config,model)
        pairs=dict(self.db.execute('SELECT task,at FROM scheduled_check'))
        self.assertEqual(pairs,{b:self.now+3600,c:self.now+3600,d:self.now+240})
        self.assertFalse(self.db.execute('SELECT 1 FROM reminder_member').fetchone())
        self.assertEqual(model.call_args.args[2]['new_after'],a)

    def test_step_learning_remains_after_child_completion_and_refuses_cycles(self):
        a=self.task('Implement a backend')
        b=self.task('Research the backend options')
        with self.db:
            project=self.db.execute("INSERT INTO project(name) VALUES('Compute')").lastrowid
            for i in [a,b]:self.db.execute('INSERT INTO task_project VALUES(?,?,"manual")',(i,project))
            self.assertTrue(relationships.link_step(self.db,a,b))
            self.assertFalse(relationships.link_step(self.db,b,a))
            self.db.execute('INSERT INTO step_example VALUES(?,?)',(a,b))
            checks.remember(self.db,'Research','Research before implementation',[b],self.now)
        c=self.task('Implement another GPU backend')
        d=self.task('Evaluate GPU backend compatibility')
        with self.db:
            for i in [c,d]:self.db.execute('INSERT INTO task_project VALUES(?,?,"manual")',(i,project))
        model=Mock(return_value=({'merges':[],'steps':[dict(parent=c,child=d,confidence='high',
                     quotes=[dict(task=c,quote='Implement'),dict(task=d,quote='Evaluate')])]},{}))
        relationships.reconcile(self.db,self.config,model)
        self.assertEqual(self.db.execute('SELECT parent FROM task_extra WHERE task=?',(d,)).fetchone()[0],c)
        self.assertNotIn(c,[r['id'] for r in planning.ranked(self.db,self.now)])
        workflows.correct_task(self.db,d,state='done')
        self.assertIn(c,[r['id'] for r in planning.ranked(self.db,self.now)])
        self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(c,)).fetchone()[0],'open')
