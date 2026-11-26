import tempfile
import unittest
from pathlib import Path
import json
import app
import paco
import planning
import workspace

class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'db';self.db=paco.connect(self.path);self.addCleanup(self.db.close)
        app.initialize(self.db)
        with self.db:
            self.db.execute("INSERT INTO task VALUES(1,'Original',3,'open',0,0)")
            self.db.execute("INSERT INTO project VALUES(1,'Launch','Company','')")
    def test_focus_protects_urgent_work_and_expires_without_changing_mode(self):
        now=1800000000
        with self.db:self.db.execute('INSERT INTO urgency VALUES(1,1)')
        result=workspace.start(self.db,{'intention':'Write proposal','minutes':25,'task':1},now)
        self.assertEqual(planning.reason_to_wait(self.db,now+1),'Focus session in progress')
        self.assertIsNone(planning.next_reminder(self.db,now+1))
        self.assertIsNone(workspace.active(self.db,now+1500))
        self.assertEqual(planning.setting(self.db,'mode','work'),'work')
        self.assertEqual(self.db.execute('SELECT task FROM focus_session WHERE id=?',(result['id'],)).fetchone()[0],1)
    def test_focus_rejects_duplicate_and_invalid_sessions(self):
        for minutes in (0,241,True):
            with self.assertRaises(ValueError):workspace.start(self.db,{'intention':'Work','minutes':minutes},1)
        workspace.start(self.db,{'intention':'Work','minutes':25},1)
        with self.assertRaises(ValueError):workspace.start(self.db,{'intention':'Other work','minutes':25},2)
    def test_task_edit_roundtrips_catalog_and_preserves_relationships(self):
        with self.db:self.db.execute("INSERT INTO task_extra VALUES(1,'Before',12,'[]')")
        workspace.edit_task(self.db,{'id':1,'changes':{'title':'New title','description':'A useful note','tags':['launch','client'],'assignee':'Nathalia','project':1,'deadline':1800000000,'estimate_minutes':45,'urgent':True}})
        t=app.state(self.db)['tasks'][0]
        self.assertEqual((t['title'],t['description'],t['tags'],t['assignee'],t['project']['name'],t['parent']),('New title','A useful note',['launch','client'],'Nathalia','Launch',12))
        workspace.edit_task(self.db,{'id':1,'changes':{'deadline':None}})
        self.assertIsNone(app.state(self.db)['tasks'][0]['deadline'])
    def test_invalid_edit_is_atomic(self):
        for changes in ({'title':'Changed','tags':['']},{'title':'Changed','project':999},{'title':'Changed','deadline':float('nan')}):
            with self.assertRaises(ValueError):workspace.edit_task(self.db,{'id':1,'changes':changes})
            self.assertEqual(self.db.execute('SELECT title FROM task WHERE id=1').fetchone()[0],'Original')
    def test_new_task_is_created_in_one_validated_operation(self):
        with self.assertRaises(ValueError):workspace.edit_task(self.db,{'changes':{'title':'Invalid','tags':['']}})
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM task').fetchone()[0],1)
        result=workspace.edit_task(self.db,{'changes':{'title':'A complete task','tags':['client'],'deadline':1800000000}})
        row=self.db.execute('SELECT tags FROM task_extra WHERE task=?',(result['id'],)).fetchone()
        self.assertEqual(json.loads(row[0]),['client'])
    def test_pause_preserves_remaining_time_across_restart_and_resume(self):
        now=1800000000
        ident=workspace.start(self.db,{'intention':'Write','minutes':25},now)['id']
        workspace.change_focus(self.db,ident,'pause',now+300,5)
        self.assertEqual(workspace.active(self.db,now+400)['phase'],'break')
        self.assertEqual(workspace.active(self.db,now+400)['remaining'],1200)
        self.assertEqual(workspace.active(self.db,now+900)['phase'],'paused')
        self.assertEqual(planning.reason_to_wait(self.db,now+900),'Focus session in progress')
        workspace.initialize(self.db)
        workspace.change_focus(self.db,ident,'resume',now+900)
        self.assertEqual(workspace.active(self.db,now+901)['ends'],now+2100)
        self.assertEqual(workspace.stats(self.db,now+2000)['completed'],0)
        self.assertEqual(workspace.stats(self.db,now+2100),{'completed':1,'minutes':25,'days':7})
        self.assertIsNone(workspace.active(self.db,now+2100))
    def test_pomodoro_break_earns_exactly_one_parrot_and_never_starts_work_unattended(self):
        now=1800000000
        ident=workspace.start(self.db,{'intention':'Read','minutes':25,'break_minutes':5},now)['id']
        self.assertEqual(workspace.active(self.db,now+1500)['phase'],'break')
        self.assertTrue(workspace.active(self.db,now+1500)['successful'])
        for moment in [now+1500,now+1600,now+1800,now+86400]:self.assertEqual(workspace.stats(self.db,moment)['completed'],1)
        with self.assertRaises(ValueError):workspace.change_focus(self.db,ident,'resume',now+1600)
        self.assertIsNone(workspace.active(self.db,now+1800))
        self.assertEqual(workspace.stats(self.db,now+1501+7*86400)['completed'],0)
    def test_ending_early_during_a_pause_does_not_earn_a_parrot(self):
        now=1800000000
        ident=workspace.start(self.db,{'intention':'Work','minutes':25},now)['id']
        workspace.change_focus(self.db,ident,'pause',now+120)
        workspace.change_focus(self.db,ident,'stop',now+180)
        workspace.change_focus(self.db,ident,'stop',now+181)
        self.assertEqual(workspace.stats(self.db,now+86400)['completed'],0)
        self.assertEqual(workspace.history(self.db,now+86400)[0]['focused_seconds'],120)
        self.assertIsNone(workspace.active(self.db,now+181))
    def test_ending_after_goal_keeps_success_and_invalid_breaks_do_not_change_session(self):
        now=1800000000
        for pause in [-1,31,True]:
            with self.assertRaises(ValueError):workspace.start(self.db,{'intention':'Work','break_minutes':pause},now)
        ident=workspace.start(self.db,{'intention':'Work','minutes':1,'break_minutes':5},now)['id']
        with self.assertRaises(ValueError):workspace.change_focus(self.db,ident,'pause',now+10,0)
        self.assertEqual(workspace.active(self.db,now+10)['phase'],'focus')
        workspace.change_focus(self.db,ident,'stop',now+61)
        self.assertEqual(workspace.stats(self.db,now+100)['completed'],1)
    def test_upcoming_calendar_window_excludes_finished_and_far_events(self):
        import meeting_identity
        now=1800000000
        with self.db:
            for ident,start,end in [('past',now-100,now-1),('current',now-50,now+50),('next',now+86400,now+86500),('far',now+8*86400,now+8*86400+100)]:
                self.db.execute('INSERT INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',(ident,'cal',ident,start,end,'https://example.test/event','v','[]'))
        self.assertEqual([e['id'] for e in meeting_identity.upcoming(self.db,now)],['current','next'])
