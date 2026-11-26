import copy
import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock,patch

import mattermost
import mattermost_bot as bot
import mattermost_tasks as tasks
import paco
import workspace
import workflows
from test_mattermost import CFG,NOW,MODEL,row

CONFIG=dict(CFG,bot=dict(enabled=True,user_id='bot',channel_id='dm',started_at=NOW-100))

def message(ident,text,sender='me',at=NOW):
    return dict(id=ident,message=text,user_id=sender,create_at=at*1000,root_id='',props={})

class FakeClient:
    def __init__(self,messages):self.posts=messages;self.sent=[];self.fail=False
    def messages(self,cutoff):return copy.deepcopy(self.posts)
    def send(self,text,marker,root=''):
        self.sent.append((text,marker))
        post=message('reply'+str(len(self.sent)),text,'bot');post['props']['paco_receipt']=marker;self.posts.append(post)
        if self.fail:raise TimeoutError('Ambiguous response')
        return post

class BotTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=paco.connect(Path(self.temp.name)/'db');self.addCleanup(self.db.close)
        bot.initialize(self.db)
    def create(self,title='Draft proposal'):
        return workspace.edit_task(self.db,dict(changes={'title':title}))['id']
    def test_add_then_update_snooze_and_replay(self):
        client=FakeClient([message('a','Add a task: Review the proposal')])
        predict=Mock(return_value={'answer':'','actions':[dict(kind='add',changes={'title':'Review the proposal'},message='a',quote='Review the proposal')]})
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        self.assertEqual(len(client.sent),1)
        ident=self.db.execute('SELECT id FROM task').fetchone()[0]
        client.posts.append(message('b',f'Remind me about #{ident} in 5 hours',at=NOW+1))
        predict.return_value={'actions':[dict(kind='update',task=ident,changes={'remind_at':NOW+18000},message='b',quote='in 5 hours')]}
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW+2)
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW+3)
        self.assertEqual(len(client.sent),2)
        self.assertEqual(self.db.execute('SELECT due FROM task').fetchone()[0],NOW+18000)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertIn('Updated #',client.sent[-1][0])
        self.assertEqual(len(predict.call_args.args[0]['history']),2)
    def test_other_users_and_bot_messages_cannot_execute(self):
        client=FakeClient([message('a','Mark everything done','stranger'),message('b','Mark everything done','bot')])
        predict=Mock();bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        predict.assert_not_called();self.assertEqual(client.sent,[])
    def test_uncertain_send_reconciles_without_duplicate_change_or_reply(self):
        client=FakeClient([message('a','Add test')]);client.fail=True
        predict=Mock(return_value={'actions':[dict(kind='add',changes={'title':'Test'},message='a',quote='test')]})
        with self.assertRaises(ValueError):bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW+1)
        self.assertEqual(len(client.sent),1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        predict.assert_called_once()
    def test_unconfirmed_delivery_is_never_blindly_retried(self):
        client=FakeClient([message('a','Hello')]);client.fail=True
        predict=Mock(return_value={'answer':'Hello!','actions':[]})
        with self.assertRaises(ValueError):bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        client.posts=client.posts[:1]
        with self.assertRaises(ValueError):bot.poll(self.db,CONFIG,MODEL,client,predict,NOW+1)
        self.assertEqual(len(client.sent),1)
    def test_grounding_and_batch_rollback(self):
        ident=self.create()
        client=FakeClient([message('a','Mark the draft done')])
        predict=Mock(return_value={'actions':[dict(kind='update',task=ident,changes={'status':'done'},message='a',quote='draft done'),dict(kind='add',changes={'title':'Invented'},message='a',quote='absent')]})
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'open')
        self.assertIn('No changes',client.sent[0][0])
    def test_concurrent_edit_does_not_get_overwritten(self):
        ident=self.create();context=[tasks.task(self.db,ident)]
        msg=dict(id='a',sender='me',mine=True,text='Done',at=NOW)
        prepared=tasks.prepare(self.db,dict(kind='update',task=ident,changes={'status':'done'},message='a',quote='Done'),context,[msg],CFG['account'],True,'a')
        workspace.edit_task(self.db,dict(id=ident,changes={'title':'Revised proposal'}))
        with self.assertRaises(ValueError),self.db:tasks.apply(self.db,prepared,CFG['base'],CFG['account'])
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'open')
    def test_clarification_and_missing_consent_make_no_changes(self):
        client=FakeClient([message('a','Move it')]);predict=Mock(return_value={'answer':'Which task do you mean?','actions':[]})
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        self.assertEqual(client.sent[0][0],'Which task do you mean?')
        client.posts.append(message('b','Add a task',at=NOW+1));predict.reset_mock()
        bot.poll(self.db,CONFIG,dict(provider='codex_cli',allowed_sources=[]),client,predict,NOW+2)
        predict.assert_not_called();self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
    def test_forgetting_dm_removes_local_history_and_prevents_replay(self):
        client=FakeClient([message('a','Add a private task')])
        predict=Mock(return_value={'actions':[dict(kind='add',changes={'title':'Private task'},message='a',quote='private task')]})
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW)
        key=self.db.execute("SELECT source_key FROM evidence WHERE source='mattermost'").fetchone()[0]
        workflows.forget(self.db,'mattermost',key)
        self.assertEqual(tuple(self.db.execute('SELECT text,answer,state FROM mattermost_dm').fetchone()),('','','forgotten'))
        bot.poll(self.db,CONFIG,MODEL,client,predict,NOW+1)
        predict.assert_called_once()
        self.assertEqual(len(client.sent),1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM evidence').fetchone()[0],0)

    def test_client_rejects_any_other_destination(self):
        c=bot.Client(CONFIG)
        with patch('keyring.get_password') as secret:
            with self.assertRaises(ValueError):c.request('POST','/posts',{'channel_id':'public','message':'x'})
            with self.assertRaises(ValueError):c.request('GET','/users/stranger')
            secret.assert_not_called()
    def test_passive_owner_update_other_person_proposal_and_approval(self):
        original=row();original['messages'][0]['version']=NOW*1000
        add=Mock(return_value={'actions':[dict(title='Review draft',message='a',quote='review the draft')]})
        with patch('mattermost.conversations',return_value=[original]):mattermost.sync(self.db,CFG,MODEL,NOW,predict=add)
        ident=self.db.execute('SELECT id FROM task').fetchone()[0]
        updated=copy.deepcopy(original);updated['messages'].append(dict(id='b',sender='juan',mine=False,text='I finished the draft',at=NOW+1,version=(NOW+1)*1000))
        change=Mock(return_value={'actions':[dict(kind='update',task=ident,changes={'status':'done'},message='b',quote='finished the draft')]})
        with patch('mattermost.conversations',return_value=[updated]):mattermost.sync(self.db,CFG,MODEL,NOW+2,predict=change)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'open')
        proposal=self.db.execute('SELECT id FROM mattermost_proposal').fetchone()[0]
        client=FakeClient([message('c','Yes approve that proposal',at=NOW+3)])
        approve=Mock(return_value={'actions':[dict(kind='approve',proposal=proposal,message='c',quote='approve that proposal')]})
        bot.poll(self.db,CONFIG,MODEL,client,approve,NOW+4)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'done')
        updated['messages'].append(dict(id='d',sender='me',mine=True,text='Juan will handle this',at=NOW+5,version=(NOW+5)*1000))
        change.return_value={'actions':[dict(kind='update',task=ident,changes={'assignee':'Juan'},message='d',quote='Juan will handle this')]}
        with patch('mattermost.conversations',return_value=[updated]):mattermost.sync(self.db,CFG,MODEL,NOW+6,predict=change)
        self.assertEqual(self.db.execute('SELECT owner FROM ownership').fetchone()[0],'Juan')
    def test_old_message_cannot_reapply_over_manual_changes(self):
        original=row();original['messages'][0]['version']=NOW*1000
        add=Mock(return_value={'actions':[dict(title='Review draft',message='a',quote='review the draft')]})
        with patch('mattermost.conversations',return_value=[original]):mattermost.sync(self.db,CFG,MODEL,NOW,predict=add)
        ident=self.db.execute('SELECT id FROM task').fetchone()[0]
        original['messages'].append(dict(id='new',sender='me',mine=True,text='FYI',at=NOW+1,version=(NOW+1)*1000))
        add.return_value={'actions':[dict(kind='update',task=ident,changes={'status':'done'},message='a',quote='review the draft')]}
        with patch('mattermost.conversations',return_value=[original]),self.assertRaises(ValueError):mattermost.sync(self.db,CFG,MODEL,NOW+2,predict=add)

if __name__=='__main__':unittest.main()
