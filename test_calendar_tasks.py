import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
import app,attention,calendar_tasks,discovery,paco,tagging,workspace

class CalendarActions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=paco.connect(Path(self.tmp.name)/'db');self.addCleanup(self.db.close);app.initialize(self.db)
        with self.db:attention.add_identities(self.db,['nathalia@example.test'])
        self.config={'provider':'codex_cli','allowed_sources':['calendar','chat']}
    def event(self,title='Print visa documents',description='',ident='e',version='1'):
        event=dict(id=ident,title=title,description=description,start=1000,end=2000,url='https://calendar.google.com/event',version=version)
        with self.db:calendar_tasks.replace_context(self.db,[event])
        return event
    def action(self,**extra):
        return dict(event='e',owner='nathalia@example.test',title='Print visa documents',quote='Print visa documents',timing='on_event',**extra)
    def run_model(self,actions):
        model=Mock(return_value=({'actions':actions},{}));n=calendar_tasks.sync(self.db,self.config,model,now=100);return n,model
    def test_personal_calendar_action_has_evidence_and_is_only_a_suggestion(self):
        self.event();count,model=self.run_model([self.action()]);self.assertEqual(count,1)
        task=self.db.execute('SELECT id FROM task').fetchone()[0]
        self.assertFalse(attention.eligible(self.db,task))
        self.assertEqual(attention.info(self.db,task)['status'],'suggested')
        self.assertEqual(self.db.execute('SELECT deadline FROM details').fetchone()[0],1000)
        self.assertEqual(self.db.execute('SELECT text FROM evidence').fetchone()[0],'Print visa documents')
        attention.decision(self.db,task,'accept');self.assertTrue(attention.eligible(self.db,task))
        self.assertEqual(calendar_tasks.sync(self.db,self.config,model,now=100),0)
        self.assertEqual(model.call_count,1)
    def test_blocks_and_missing_consent_never_call_model(self):
        model=Mock(side_effect=AssertionError('Must not call'))
        self.event('x');self.assertEqual(calendar_tasks.sync(self.db,self.config,model,100),0)
        self.event();self.assertEqual(calendar_tasks.sync(self.db,{'provider':'codex_cli','allowed_sources':['chat']},model,100),0)
    def test_foreign_actions_and_invented_attendance_are_rejected(self):
        self.event('Team standup','Juan will write the report. Nathalia will approve the budget.')
        actions=[dict(event='e',owner='juan@example.test',title='Write the report',quote='Juan will write the report.'),dict(event='e',owner='nathalia@example.test',title='Prepare for team standup',quote='Team standup'),dict(event='e',owner='nathalia@example.test',title='Approve the budget',quote='Nathalia will approve the budget.',responsibility='decide')]
        n,_=self.run_model(actions);self.assertEqual(n,1)
        self.assertEqual(self.db.execute('SELECT title FROM task').fetchone()[0],'Approve the budget')
    def test_ungrounded_batch_is_atomic(self):
        self.event()
        bad=self.action();bad['quote']='Invented text'
        with self.assertRaises(ValueError):self.run_model([self.action(),bad])
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
    def test_changed_event_discards_stale_model_result(self):
        self.event()
        def model(*args):self.event('Cancelled plan',version='2');return {'actions':[self.action()]},{}
        self.assertEqual(calendar_tasks.sync(self.db,self.config,model,100),0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
    def test_dismissal_survives_event_changes_and_rephrasing(self):
        self.event();self.run_model([self.action()]);task=self.db.execute('SELECT id FROM task').fetchone()[0]
        attention.decision(self.db,task,'dismiss');self.event(description='Updated location',version='2')
        action=self.action();action['title']='Print the visa documents'
        self.assertEqual(self.run_model([action])[0],0)
        self.assertEqual(attention.info(self.db,task)['status'],'dismissed')
    def test_explicit_feedback_is_passed_without_raw_message_text(self):
        task=workspace.edit_task(self.db,{'changes':{'title':'Prepare the project budget'}})['id']
        attention.decision(self.db,task,'dismiss')
        workspace.edit_task(self.db,{'id':task,'changes':{'assignee':'Juan'}})
        self.event();_,model=self.run_model([])
        feedback=model.call_args.args[2]['responsibility_corrections']
        self.assertEqual(feedback[0]['assignee'],'Juan');self.assertEqual(feedback[0]['correction'],'reassign')
        self.assertNotIn('text',feedback[0]);self.assertEqual(attention.corrections(self.db,{'provider':'codex_cli','allowed_sources':['calendar']}),[])
    def test_feedback_records_only_real_changes_and_latest_choice(self):
        task=workspace.edit_task(self.db,{'changes':{'title':'Prepare the report'}})['id']
        attention.decision(self.db,task,'dismiss');attention.decision(self.db,task,'accept')
        workspace.edit_task(self.db,{'id':task,'changes':{'assignee':'','responsibility':'execute'}})
        values=attention.corrections(self.db,self.config)
        self.assertEqual(len(values),1);self.assertEqual(values[0]['correction'],'accept')

    def test_calendar_evidence_links_to_existing_email_task_without_reopening(self):
        task=workspace.edit_task(self.db,{'changes':{'title':'Gather all visa documents'}})['id']
        attention.decision(self.db,task,'dismiss')
        self.event();action=self.action();action['existing_task']=task
        self.assertEqual(self.run_model([action])[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertEqual(attention.info(self.db,task)['status'],'dismissed')
        self.assertEqual(self.db.execute('SELECT task FROM evidence').fetchone()[0],task)
    def test_existing_task_id_must_be_in_supplied_context(self):
        self.event();action=self.action();action['existing_task']=999
        with self.assertRaises(ValueError):self.run_model([action])
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)

    def test_all_day_action_uses_calendar_timezone_and_end_of_day(self):
        from unittest.mock import patch
        from datetime import datetime
        from zoneinfo import ZoneInfo
        payload={'timeZone':'America/New_York','items':[{'id':'date','summary':'Print visa documents','start':{'date':'2026-11-27'},'end':{'date':'2026-11-28'}}]}
        response=Mock();response.json.return_value=payload;session=Mock();session.get.return_value=response
        contexts=[]
        with patch('discovery.google_session') as connection:
            connection.return_value.__enter__.return_value=session
            list(discovery.google_rows('calendar',100,context_out=contexts))
        self.assertEqual(contexts[0]['start'],datetime(2026,11,27,tzinfo=ZoneInfo('America/New_York')).timestamp())
        with self.db:calendar_tasks.replace_context(self.db,contexts)
        action=self.action();action['event']='primary:date';self.run_model([action])
        self.assertEqual(self.db.execute('SELECT deadline FROM details').fetchone()[0],contexts[0]['end']-1)

    def test_calendar_only_consent_does_not_send_unrelated_tasks(self):
        workspace.edit_task(self.db,{'changes':{'title':'Private email commitment'}})
        self.config['allowed_sources']=['calendar'];self.event();_,model=self.run_model([])
        self.assertEqual(model.call_args.args[2]['existing_tasks'],[])
        self.assertEqual(model.call_args.args[2]['responsibility_corrections'],[])
