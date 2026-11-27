from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import json
import app
import paco
import planning
import replies


class Replies(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db'
        self.db=paco.connect(self.path);app.initialize(self.db)
        self.now=datetime(2026,11,25,10).timestamp()
        with self.db:
            self.db.execute("INSERT INTO task VALUES(1,'Ship report',3,'open',0,0)")
            self.db.execute("INSERT INTO notification VALUES(1,1,'Ship report','friendly','Ready',?,NULL)",(self.now,))
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def say(self,text,notification=1,request=None,config=None):
        return replies.reply(self.db,{'text':text,'notification':notification,'request':request or uuid.uuid4().hex},config,self.now)
    def task(self):return self.db.execute('SELECT * FROM task WHERE id=1').fetchone()
    def proposed(self,intent,text='Could you take care of that change?'):
        with patch('replies.models.complete',return_value=({'intent':intent,'answer':'Suggested change'},{})):
            return self.say(text,config={'provider':'anthropic'})
    def test_five_hours_away_suppresses_other_urgent_tasks_then_expires(self):
        with self.db:
            self.db.execute("INSERT INTO task VALUES(2,'Other urgent work',5,'open',0,0)")
            self.db.execute('INSERT INTO urgency VALUES(2,1)')
        result=self.say('remember me in 5 hrs I will be out.')
        self.assertIn('all other reminders',result['answer'])
        self.assertEqual(self.task()['due'],self.now+5*3600)
        self.assertIsNone(planning.next_reminder(self.db,self.now+60))
        self.assertIsNotNone(planning.next_reminder(self.db,self.now+5*3600))
    def test_snooze_does_not_silence_other_tasks_without_away(self):
        self.say('remind me in 5 hours')
        with self.db:self.db.execute("INSERT INTO task VALUES(2,'Other work',3,'open',0,0)")
        self.assertEqual(planning.next_reminder(self.db,self.now)['id'],2)
    def test_importance_is_explicit_and_negation_removes_it(self):
        self.say('that is super important')
        self.assertEqual(self.db.execute('SELECT critical FROM urgency WHERE task=1').fetchone()[0],1)
        self.say("that's not urgent")
        self.assertEqual(self.db.execute('SELECT critical FROM urgency WHERE task=1').fetchone()[0],0)
    def test_done_persists_and_invalidates_task_reminders(self):
        result=self.say('that is done')
        self.assertFalse(result['pending'])
        self.assertEqual(self.task()['state'],'done')
        self.assertEqual(self.db.execute('SELECT state FROM task_override').fetchone()[0],'done')
        self.assertIsNone(planning.next_reminder(self.db,self.now))
    def test_ambiguous_attribution_does_not_close_or_reassign(self):
        result=self.say('that is what Juan did')
        self.assertIn('Did they complete',result['answer'])
        self.assertEqual(self.task()['state'],'open')
        self.assertEqual(self.db.execute('SELECT count(*) FROM ownership').fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT person FROM evidence WHERE source='reply'").fetchone()[0],'Juan')
        self.say('Juan completed this')
        self.assertEqual(self.task()['state'],'done')
    def test_negated_conditional_other_task_text_never_executes_locally(self):
        for text in ('not done','I am not done','if Juan finishes then mark done','the other task is done','Juan did a similar task','not super important','remind me in 0 hours','remind me in -5 hours'):
            with self.subTest(text=text):
                if text=='remind me in 0 hours':
                    with self.assertRaises(ValueError):self.say(text)
                else:self.say(text)
                self.assertEqual(self.task()['state'],'open')
                self.assertEqual(self.task()['due'],0)
    def test_retry_is_idempotent_and_cannot_reuse_id_for_different_text(self):
        request=uuid.uuid4().hex
        first=self.say('remind me in 5 hrs',request=request)
        self.now+=60
        second=self.say('remind me in 5 hrs',request=request)
        self.assertEqual(first,second)
        self.assertEqual(self.task()['due'],self.now-60+18000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intervention').fetchone()[0],1)
        with self.assertRaises(ValueError):self.say('that is done',request=request)
    def test_preferences_persist_drive_policy_and_are_resettable(self):
        self.say('bother me less')
        self.db.close();self.db=paco.connect(self.path)
        task=planning.ranked(self.db,self.now).fetchone()
        self.assertEqual(planning.reminder_delay(self.db,task,self.now),3600)
        self.assertEqual(planning.setting(self.db,'notification_gap'),'1800')
        self.assertIn('one-hour',self.say('what have you learned')['answer'])
        self.say('reset my reminder preferences')
        self.assertEqual(planning.reminder_delay(self.db,task,self.now),900)
        self.assertEqual(self.db.execute('SELECT count(*) FROM learned').fetchone()[0],0)
    def test_focus_quiets_all_then_returns_to_checkin(self):
        self.say('help me focus for 45 minutes')
        self.assertEqual(self.task()['state'],'focus')
        self.assertIsNone(planning.next_reminder(self.db,self.now+60))
        self.assertEqual(planning.next_reminder(self.db,self.now+2700)['id'],1)
    def test_global_reply_can_protect_time_but_never_guesses_task(self):
        self.say("I'm out for 2 hours",notification=None)
        self.assertIsNone(planning.next_reminder(self.db,self.now))
        self.say("I'm back",notification=None)
        self.assertIsNotNone(planning.next_reminder(self.db,self.now))
        result=self.say('that is done',notification=None)
        self.assertIn('isn’t attached',result['answer'])
        self.assertEqual(self.task()['state'],'open')
    def legacy_proposal(self,intent):
        ident=self.db.execute("INSERT INTO notification_reply(request,notification,task,text,answer,intent,status,created,result,snapshot) VALUES(?,1,1,'Legacy request','Apply?',?,'pending',?,'{}',?)",
            (uuid.uuid4().hex,json.dumps(intent),self.now,json.dumps(dict(title=self.task()['title'],state=self.task()['state'],priority=self.task()['priority'],assignee='',intake_status='accepted')))).lastrowid
        self.db.commit()
        return {'reply':ident}

    def test_model_executes_without_confirmation_and_cannot_target_other_tasks(self):
        result=self.proposed({'kind':'done'})
        self.assertFalse(result['pending'])
        self.assertTrue(result['close'])
        self.assertEqual(self.task()['state'],'done')
        replies.confirm(self.db,result['reply'],True,self.now+2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM intervention').fetchone()[0],1)
        with self.assertRaises(ValueError):self.proposed({'kind':'done','task':999})

    def test_month_postponement_is_local_and_preserves_task_title_and_deadline(self):
        with self.db:self.db.execute("INSERT INTO details VALUES(1,'',30,2000000000)")
        with patch('replies.models.complete') as model:
            result=self.say('I cannot do this until January.',config={'provider':'codex_cli'})
        model.assert_not_called()
        self.assertEqual(self.task()['due'],datetime(2027,1,1,9).timestamp())
        self.assertEqual(self.task()['title'],'Ship report')
        self.assertEqual(self.db.execute('SELECT deadline FROM details').fetchone()[0],2000000000)
        self.assertTrue(result['close'])

    def test_model_edits_only_requested_fields(self):
        result=self.proposed({'kind':'edit','title':'Request document','remind_at':'2027-01-03T09:00:00+01:00'})
        self.assertTrue(result['close'])
        self.assertEqual(self.task()['title'],'Request document')
        self.assertEqual(self.task()['due'],datetime.fromisoformat('2027-01-03T09:00:00+01:00').timestamp())
        self.assertIsNone(self.db.execute('SELECT deadline FROM details').fetchone())

    def test_concurrent_task_change_is_preserved(self):
        def complete(*args):
            self.db.execute('UPDATE task SET due=123 WHERE id=1')
            self.db.commit()
            return {'intent':{'kind':'done'},'answer':'Done'},{}
        with patch('replies.models.complete',side_effect=complete):
            with self.assertRaisesRegex(ValueError,'task changed'):
                self.say('I have completed the report',config={'provider':'codex_cli'})
        self.assertEqual(self.task()['state'],'open')
        self.assertEqual(self.task()['due'],123)

    def test_model_consent_checked_before_network_or_keychain(self):
        with patch('models.secret') as secret,patch('models.urllib.request.urlopen') as network:
            with self.assertRaisesRegex(ValueError,'not enabled'):
                self.say('Could you help me break this down?',config={'provider':'anthropic','model':'model','allowed_sources':[]})
            secret.assert_not_called();network.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM notification_reply').fetchone()[0],0)
    def test_clear_commands_work_without_cloud_or_consent(self):
        with patch('models.complete') as model:
            self.say('that is done',config={'provider':'anthropic','allowed_sources':[]})
            model.assert_not_called()
    def test_model_receives_bound_conversation_and_feedback(self):
        self.say('bother me less');self.say('that is what Juan did')
        with patch('models.complete',return_value=({'intent':{'kind':'clarify'},'answer':'What remains for you to do?'},{})) as model:
            result=self.say('Help me figure out the next step',config={'provider':'ollama'})
        context=model.call_args.args[2]
        self.assertEqual(context['task']['id'],1)
        self.assertEqual(len(context['conversation']),2)
        self.assertTrue(context['accepted_feedback'])
        self.assertFalse(result['pending']);self.assertEqual(self.task()['state'],'open')
    def test_cancel_expiry_and_superseding_replies(self):
        result=self.legacy_proposal({'kind':'urgent'})
        replies.confirm(self.db,result['reply'],False,self.now+1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM urgency').fetchone()[0],0)
        result=self.legacy_proposal({'kind':'urgent'})
        with self.assertRaisesRegex(ValueError,'no longer current'):replies.confirm(self.db,result['reply'],True,self.now+601)
        result=self.legacy_proposal({'kind':'urgent'})
        self.say('not urgent')
        with self.assertRaisesRegex(ValueError,'no longer current'):replies.confirm(self.db,result['reply'],True,self.now+2)
    def test_model_proposal_rejects_task_changes_and_bad_schema(self):
        result=self.legacy_proposal({'kind':'done'})
        with self.db:self.db.execute("UPDATE task SET title='Changed scope' WHERE id=1")
        with self.assertRaisesRegex(ValueError,'task changed'):replies.confirm(self.db,result['reply'],True,self.now+1)
        for intent in ({'kind':'shell','command':'rm'}, {'kind':'focus','minutes':10080}, {'kind':'snooze','minutes':True}, {'kind':'snooze','minutes':float('inf')}):
            with self.assertRaises(ValueError):self.proposed(intent)
    def test_late_reply_does_not_reopen_completed_task(self):
        self.say('that is done')
        result=self.say('remind me in 5 hours')
        self.assertIn('already done',result['answer'])
        self.assertEqual(self.task()['state'],'done')
    def test_talk_restores_last_answer(self):
        self.say('bother me less')
        result=app.act(self.db,self.path,paco.connect,{'action':'reply_context'})
        self.assertEqual(result['id'],1)
        self.assertIn('30 minutes',result['reply_answer'])
    def test_followup_yes_resolves_attribution_and_model_confirmation(self):
        self.say('that is what Juan did')
        result=self.say('yes he did')
        self.assertIn('Juan',result['answer'])
        self.assertEqual(self.task()['state'],'done')
        with self.db:self.db.execute("UPDATE task SET state='open' WHERE id=1")
        self.proposed({'kind':'urgent'})
        result=self.say('yes please')
        self.assertFalse(result['pending'])
        self.assertEqual(self.db.execute('SELECT critical FROM urgency WHERE task=1').fetchone()[0],1)

    def test_ownership_replies_persist_as_learning_without_completing(self):
        import attention
        self.say('not mine')
        self.assertEqual(attention.info(self.db,1)['status'],'dismissed')
        self.assertFalse(attention.eligible(self.db,1))
        self.say('mine')
        self.assertTrue(attention.eligible(self.db,1))
        self.say('assign this to Juan')
        self.assertEqual(self.task()['state'],'open')
        self.assertFalse(attention.eligible(self.db,1))
        self.assertEqual(attention.corrections(self.db)[0]['assignee'],'Juan')
        self.assertIn('task corrections',self.say('what have you learned')['answer'])
    def test_model_reassignment_applies_directly(self):
        self.proposed({'kind':'assign','person':'Juan'},'Juan should own this action')
        self.assertEqual(self.db.execute('SELECT owner FROM ownership WHERE task=1').fetchone()[0],'Juan')

    def test_not_mine_clears_my_assignment_and_remembers_explicit_rejection(self):
        import attention
        self.say('mine');self.say('not mine')
        self.assertEqual(self.db.execute('SELECT owner FROM ownership WHERE task=1').fetchone()[0],'')
        self.assertEqual(attention.corrections(self.db)[0]['correction'],'not_mine')
