import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

import mattermost as mm
import paco
import workflows

CFG = dict(base='https://chat.example', account='server/me', user_id='me', username='nathalia')
NOW = 1800000000
MODEL = dict(provider='codex_cli', allowed_sources=['mattermost'])

def post(ident, text, root='', age=0):
    return dict(id=ident, message=text, root_id=root, create_at=(NOW-age)*1000, user_id='juan')

def page(posts):
    return dict(order=[p['id'] for p in posts], posts={p['id']:p for p in posts})

def row():
    return dict(id='a', channel='DM', messages=[dict(id='a', sender='juan', mine=False,
        text='Please review the draft and confirm the budget.', at=NOW, version=1)])

class MattermostTest(unittest.TestCase):
    def test_personal_mentions_dm_and_full_thread(self):
        client = Mock()
        client.get.side_effect = [dict(id='me',username='nathalia'),
            [dict(id='general',type='O',name='general',last_post_at=NOW*1000),
             dict(id='dm',type='D',name='dm',last_post_at=NOW*1000)],
            page([post('a','@nathalia please review',root='root'),post('b','@nathalia-other FYI')]),
            page([post('root','Earlier question'),post('a','@nathalia please review',root='root'),post('c','Already handled',root='root')]),
            page([post('d','Can you check?'),post('old','Ignore',age=15*86400)])]
        result=mm.conversations(client,CFG,NOW)
        self.assertEqual([r['id'] for r in result],['root','d'])
        self.assertIn('Already handled',[m['text'] for m in result[0]['messages']])

    def test_pagination_and_account_guard(self):
        client=Mock()
        client.get.side_effect=[dict(id='other',username='nathalia')]
        with self.assertRaises(ValueError): mm.conversations(client,CFG,NOW)
        batch=[post('p'+str(i),'FYI') for i in range(100)]
        client.get.side_effect=[dict(id='me',username='nathalia'),[dict(id='c',type='O',name='c',last_post_at=NOW*1000)],page(batch),page([post('a','@nathalia review')])]
        self.assertEqual(len(mm.conversations(client,CFG,NOW)),1)
        self.assertEqual(client.get.call_args.kwargs['before'],'p99')

    def test_refresh_and_read_endpoint_restriction(self):
        saved=dict(base=CFG['base'],access_token='old',refresh_token='refresh',client_id='client',client_secret='secret',expires_at=0)
        with patch('keyring.get_password',return_value=json.dumps(saved)), patch('keyring.set_password') as save, patch('mattermost.token_request',return_value=dict(access_token='new',refresh_token='rotated',expires_in=3600)), patch('mattermost.requests.get') as get:
            get.return_value=Mock(status_code=200);get.return_value.json.return_value={'id':'me'}
            client=mm.Client(CFG);self.assertEqual(client.get('/users/me'),{'id':'me'})
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(json.loads(save.call_args.args[2])['refresh_token'],'rotated')
            with self.assertRaises(ValueError): client.get('/users/me/tokens')
            with self.assertRaises(ValueError): client.get('https://other.example/users/me')
            get.assert_called_once()

    def test_consent_grounding_idempotence_and_forgetting(self):
        with tempfile.TemporaryDirectory() as folder, closing(paco.connect(Path(folder)/'db')) as db, patch('mattermost.conversations',return_value=[row()]):
            predict=Mock(return_value={'actions':[dict(title='Review draft',message='a',quote='review the draft'),dict(title='Confirm budget',message='a',quote='confirm the budget')]})
            mm.sync(db,CFG,dict(provider='codex_cli',allowed_sources=[]),NOW,predict=predict)
            predict.assert_not_called()
            mm.sync(db,CFG,MODEL,NOW,predict=predict)
            mm.sync(db,CFG,MODEL,NOW,predict=predict)
            self.assertEqual(predict.call_count,1)
            self.assertEqual(db.execute('SELECT count(*) FROM task').fetchone()[0],2)
            self.assertEqual(db.execute('SELECT count(DISTINCT task) FROM evidence').fetchone()[0],2)
            key=db.execute('SELECT source_key FROM evidence WHERE task IS NOT NULL LIMIT 1').fetchone()[0]
            workflows.forget(db,'mattermost',key)
            self.assertEqual(db.execute('SELECT count(*) FROM evidence').fetchone()[0],0)
            db.execute('DELETE FROM mattermost_revision');db.commit()
            mm.sync(db,CFG,MODEL,NOW,predict=predict)
            self.assertEqual(predict.call_count,1)
            self.assertEqual(db.execute('SELECT count(*) FROM evidence').fetchone()[0],0)

    def test_invalid_extraction_is_atomic(self):
        with tempfile.TemporaryDirectory() as folder, closing(paco.connect(Path(folder)/'db')) as db, patch('mattermost.conversations',return_value=[row()]):
            predict=Mock(return_value={'actions':[dict(title='Review draft',message='a',quote='review the draft'),dict(title='Invented',message='a',quote='not in message')]})
            with self.assertRaises(ValueError): mm.sync(db,CFG,MODEL,NOW,predict=predict)
            self.assertEqual(db.execute('SELECT count(*) FROM task').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT count(*) FROM mattermost_revision').fetchone()[0],0)

if __name__ == '__main__': unittest.main()
