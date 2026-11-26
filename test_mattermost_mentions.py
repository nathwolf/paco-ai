import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import app,mattermost_mentions as mentions,mattermost_bot,paco,workspace,workflows
from test_mattermost_bot import CONFIG,MODEL,NOW

CFG=copy.deepcopy(CONFIG)
CFG['bot'].update(username='paco',mentions_enabled=True,mentions_started_at=NOW-100)

def post(ident='a',text='@paco hola',sender='me',channel='group',root='',at=NOW):
    return dict(id=ident,message=text,user_id=sender,channel_id=channel,root_id=root,create_at=at*1000,update_at=at*1000,props={})

class Client:
    def __init__(self,posts):self.posts=copy.deepcopy(posts);self.sent=[];self.fail=False;self.channels=['group','other'];self.bots=set();self.change_on_refresh=False;self.reads=0
    def discover(self):return [dict(id=c,type='P',last_post_at=(NOW+100)*1000) for c in self.channels]
    def messages(self,channel,cutoff):return copy.deepcopy([p for p in self.posts if p['channel_id']==channel and p['create_at']>=cutoff*1000])
    def post(self,channel,ident):
        self.reads+=1
        p=copy.deepcopy(next(p for p in self.posts if p['id']==ident and p['channel_id']==channel))
        if self.change_on_refresh and self.reads>1:p['update_at']+=1;p['message']='Never mind'
        return p
    def thread(self,channel,p):
        root=p.get('root_id') or p['id']
        return copy.deepcopy([t for t in self.posts if t['channel_id']==channel and (t.get('root_id') or t['id'])==root])
    def human(self,ident):return ident not in self.bots
    def send(self,channel,p,text,marker):
        self.sent.append((channel,'',text))
        response=post('reply'+str(len(self.sent)),text,'bot',channel,'',NOW+1)
        response['props']['paco_receipt']=marker;self.posts.append(response)
        if self.fail:raise TimeoutError('Ambiguous send')
        return response

class Mentions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=paco.connect(Path(self.tmp.name)/'db');self.addCleanup(self.db.close);app.initialize(self.db);mentions.initialize(self.db)
    def poll(self,client,predict):return mentions.poll(self.db,CFG,MODEL,client,predict,NOW+2)
    def test_whole_username_only_and_no_quoted_or_code_invocations(self):
        for s in ['@paco hola','Hi @Paco, help','please\n@paco']:
            self.assertTrue(mentions.mentioned(s))
        for s in ['@pacote','x@paco','https://example/@paco','`@paco hello`','> @paco hello','```\n@paco hi\n```','hi there']:
            self.assertFalse(mentions.mentioned(s),s)
    def test_thread_mentions_reply_in_channel_and_deduplicate_polling(self):
        client=Client([post('root','Planning'),post('a','@paco summarize','juan',root='root')])
        predict=Mock(return_value={'answer':'Here is the plan.','actions':[]})
        self.poll(client,predict);self.poll(client,predict)
        self.assertEqual(client.sent,[('group','','Here is the plan.')]);predict.assert_called_once()
    def test_new_top_level_mention_gets_a_normal_chat_message(self):
        client=Client([post()]);self.poll(client,lambda p:{'answer':'Hola!'})
        self.assertEqual(client.sent[0][:2],('group',''))
    def test_model_cannot_see_private_tasks_dm_history_or_other_threads(self):
        workspace.edit_task(self.db,{'changes':{'title':'PRIVATE_TASK_SENTINEL','description':'PRIVATE_DESCRIPTION'}})
        mattermost_bot.initialize(self.db)
        with self.db:self.db.execute("INSERT INTO mattermost_dm VALUES('a','b',1,'PRIVATE_DM','r','PRIVATE_ANSWER','sent','receipt')")
        client=Client([post('root','Visible plan'),post('a','@paco summarize','juan',root='root'),post('hidden','OTHER_THREAD'),post('elsewhere','OTHER_CHANNEL',channel='other')])
        predict=Mock(return_value={'answer':'A plan.'});self.poll(client,predict)
        payload=predict.call_args.args[0]
        self.assertEqual(set(payload),{'current_message','thread','can_add_personal_task','local_time'})
        self.assertEqual([p['text'] for p in payload['thread']],['Visible plan'])
        self.assertFalse(payload['can_add_personal_task']);self.assertNotIn('PRIVATE',str(payload));self.assertNotIn('OTHER',str(payload))
    def test_nonmentions_and_bot_authors_are_ignored(self):
        client=Client([post('a','hi'),post('b','@paco loop','otherbot'),post('c','@paco loop','bot')]);client.bots.add('otherbot')
        predict=Mock();self.poll(client,predict);predict.assert_not_called();self.assertEqual(client.sent,[])
    def test_owner_can_add_only_their_explicit_new_task(self):
        client=Client([post(text='@paco add a task: Review proposal')])
        predict=Mock(return_value={'actions':[dict(kind='add',changes={'title':'Review proposal'},message='a',quote='Review proposal')]})
        self.poll(client,predict);self.poll(client,predict)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertEqual(client.sent[0][2],'Added to your Paco:\n• Review proposal')
    def test_other_people_and_private_updates_cannot_mutate_tasks(self):
        task=workspace.edit_task(self.db,{'changes':{'title':'Secret task'}})['id']
        for sender,action in [('juan',dict(kind='add',changes={'title':'Unauthorized'})),('me',dict(kind='update',task=task,changes={'status':'done'}))]:
            p=post(sender,'@paco do it',sender=sender)
            answer,prepared=None,None
            with self.assertRaises(ValueError):mentions.prepare(self.db,CFG,MODEL,p,[p],lambda _:dict(actions=[dict(action,message=sender,quote='do it')]))
        self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'open')
    def test_ambiguous_send_reconciles_without_repeating_side_effects(self):
        client=Client([post()]);client.fail=True;predict=Mock(return_value={'answer':'Hola'})
        with self.assertRaises(ValueError):self.poll(client,predict)
        self.poll(client,predict);self.assertEqual(len(client.sent),1);predict.assert_called_once()
    def test_missing_receipt_never_blindly_resends(self):
        client=Client([post()]);client.fail=True;predict=Mock(return_value={'answer':'Hola'})
        with self.assertRaises(ValueError):self.poll(client,predict)
        client.posts=client.posts[:1]
        with self.assertRaises(ValueError):self.poll(client,predict)
        self.assertEqual(len(client.sent),1)
    def test_changed_request_before_commit_does_not_create_task_or_send(self):
        client=Client([post(text='@paco add task')]);client.change_on_refresh=True
        self.poll(client,lambda _:dict(actions=[dict(kind='add',changes={'title':'Task'},message='a',quote='add task')]))
        self.assertEqual(client.sent,[]);self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
    def test_forgetting_and_disabled_setting_prevent_reply(self):
        client=Client([post()]);predict=Mock(return_value={'answer':'Hola'})
        workflows.forget(self.db,'mattermost',CFG['account']+'/a')
        self.poll(client,predict);predict.assert_not_called()
        mentions.poll(self.db,dict(CFG,bot=dict(CFG['bot'],mentions_enabled=False)),MODEL,client,predict,NOW)
        predict.assert_not_called()
    def test_model_cannot_trigger_broadcast_mentions(self):
        client=Client([post()]);self.poll(client,lambda _:{'answer':'@channel @here @all'})
        self.assertNotIn('@channel',client.sent[0][2]);self.assertIn('@\u200bchannel',client.sent[0][2])
    def test_passive_intake_does_not_reinterpret_bot_commands(self):
        import mattermost
        row=dict(id='a',channel='Group',messages=[dict(id='a',sender='me',mine=True,text='@paco add a task: Review proposal',at=NOW,version=NOW*1000)])
        predict=Mock()
        with patch('mattermost.conversations',return_value=[row]):mattermost.sync(self.db,CFG,MODEL,NOW,predict=predict)
        predict.assert_not_called()
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)

    def test_real_client_rejects_unverified_channel_and_cross_channel_thread(self):
        client=mentions.Client(CFG)
        with patch.object(client,'_request') as request:
            with self.assertRaises(ValueError):client.messages('private',0)
            request.assert_not_called()
            client.channels={'group':dict(id='group')}
            request.return_value={'posts':{'a':post(channel='other')},'order':['a']}
            with self.assertRaises(ValueError):client.thread('group',post())
    def test_deleted_post_is_skipped_without_blocking_the_next_mention(self):
        client=mentions.Client(CFG);client.channels={'group':dict(id='group')}
        with patch.object(client,'_request',return_value=None):
            removed=client.post('group','deleted')
        self.assertFalse(mentions.eligible(removed,CFG))
        fake=Client([dict(removed,message='@paco old',delete_at=0,create_at=NOW*1000),post('next')])
        original=fake.post
        fake.post=lambda c,i:removed if i=='deleted' else original(c,i)
        self.poll(fake,lambda _:{'answer':'Hello'})
        self.assertEqual(len(fake.sent),1);self.assertEqual(fake.sent[0][2],'Hello')

    def test_real_send_rechecks_membership_and_target_before_post(self):
        client=mentions.Client(CFG);client.channels={'group':dict(id='group')}
        with patch.object(client,'discover',return_value=[]),patch.object(client,'_request') as request:
            with self.assertRaises(ValueError):client.send('group',post(),'hello','key')
            request.assert_not_called()
        for root in ('','existing-thread'):
            incoming=post(root=root)
            with patch.object(client,'discover',return_value=[dict(id='group')]),patch.object(client,'post',return_value=incoming),patch.object(client,'_request',return_value={'id':'reply'}) as request:
                client.send('group',incoming,'hello','key')
                self.assertEqual(request.call_args.args[2]['channel_id'],'group');self.assertEqual(request.call_args.args[2]['root_id'],'')

if __name__=='__main__':unittest.main()
