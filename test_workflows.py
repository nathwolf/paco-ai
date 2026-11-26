import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import agents
import app
import mcp_server
import models
import paco
import workflows as w


class Workflows(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.db=paco.connect(self.path);app.initialize(self.db)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_meeting_replay_evidence_and_deleted_source(self):
        data={'id':'meeting1','title':'Planning','at':100,'partial':True,'segments':[{'speaker':'Ana','seconds':30,'text':'Maybe we should ship Friday.'}]}
        w.import_meeting(self.db,data);w.import_meeting(self.db,data)
        self.assertEqual(len(w.search(self.db,'Friday',person='Ana')),1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
        e=w.search(self.db,'Friday')[0]
        with self.assertRaises(ValueError):w.accept_assignment(self.db,e['id'],'Ship','Ana','2026-11-27T17:00')
        ident=w.accept_assignment(self.db,e['id'],'Ship','Ana','2026-11-27T17:00+01:00')
        self.assertEqual(w.accept_assignment(self.db,e['id'],'Ship','Ana'),ident)
        w.forget(self.db,'meeting','meeting1:0');w.import_meeting(self.db,data)
        self.assertEqual(w.search(self.db),[])
    def test_correction_undo_detects_intervening_edits(self):
        ident=app.act(self.db,self.path,paco.connect,{'action':'add','title':'Draft'})['id']
        w.correct_task(self.db,ident,title='Corrected')
        w.undo(self.db,1)
        self.assertEqual(self.db.execute('SELECT title FROM task').fetchone()[0],'Draft')
        with self.assertRaises(ValueError):w.undo(self.db,1)
    def test_autoresponse_keeps_timer_and_reply_cancels_draft(self):
        ident=w.wait_for(self.db,'thread','a@example.test','the proposal')
        self.assertEqual(w.wait_for(self.db,'thread','a@example.test','the proposal'),ident)
        w.followup_draft(self.db,ident,'Quick update?')
        w.observe_reply(self.db,'thread','a@example.test','I am on holiday',True)
        self.assertEqual(self.db.execute('SELECT status FROM waiting').fetchone()[0],'waiting')
        w.observe_reply(self.db,'thread','a@example.test','Here it is')
        with self.assertRaises(ValueError):w.followup_draft(self.db,ident)
    def test_three_distinct_days_and_remembered_rejection(self):
        now=1800000000
        for at in [now,now-3600,now-86400,now-2*86400]:w.record_request(self.db,'Review work',at)
        self.assertEqual(w.recurring(self.db,now)[0]['days'],3)
        proposal=w.propose_automation(self.db,'Review work')
        self.assertEqual(len(w.run_automations(self.db,trial=proposal['id'])),1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM automation_run').fetchone()[0],0)
        with self.db:self.db.execute("UPDATE automation SET status='rejected'")
        w.propose_automation(self.db,'Review work')
        self.assertEqual(self.db.execute('SELECT status FROM automation').fetchone()[0],'rejected')
    def test_capture_denied_by_default_exclusions_and_redaction(self):
        self.assertIsNone(w.capture(self.db,'Editor','Work','secret'))
        with self.db:
            self.db.execute("INSERT INTO capture_rule VALUES('Editor',1,0)")
            self.db.execute("INSERT INTO exclusion VALUES('site','bank')")
        self.assertIsNone(w.capture(self.db,'Editor','Work','secret',url='https://bank.test'))
        self.assertIsNone(w.capture(self.db,'Editor','Work','secret',private=True))
        w.capture(self.db,'Editor','Work','api_key=secret123 ordinary work')
        self.assertNotIn('secret123',w.search(self.db)[0]['text'])
    def test_mcp_revocation_and_scoped_listing(self):
        mcp_server.grant(self.db,'client',['tasks.read'])
        listing=mcp_server.dispatch(self.db,'client',{'method':'tools/list'})
        self.assertNotIn('task_create',[x['name'] for x in listing['tools']])
        request={'method':'tools/call','params':{'name':'tasks_list'}}
        mcp_server.dispatch(self.db,'client',request)
        mcp_server.grant(self.db,'client',[])
        with self.assertRaises(PermissionError):mcp_server.dispatch(self.db,'client',request)
        output=io.StringIO()
        mcp_server.serve(self.db,'client',io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\n'),output)
        self.assertEqual(json.loads(output.getvalue())['result'],{})
    def test_cloud_consent_before_any_network_or_key_read(self):
        with patch('models.secret') as secret:
            with self.assertRaises(ValueError):models.complete({'provider':'anthropic','model':'test'},'system',{},'gmail')
            secret.assert_not_called()
    def test_anthropic_request_and_response(self):
        class Response(io.BytesIO):pass
        seen=[]
        def transport(request,timeout):
            seen.append(json.loads(request.data));return Response(b'{"content":[{"type":"text","text":"{\\"answer\\":\\"Ready\\"}"}],"usage":{"input_tokens":10}}')
        with patch('models.secret',return_value='test-key'):
            result,metrics=models.complete({'provider':'anthropic','model':'test','allowed_sources':['chat']},'system',{'hello':'world'},'chat',transport)
        self.assertEqual(result['answer'],'Ready');self.assertEqual(metrics['usage']['input_tokens'],10)
        self.assertEqual(seen[0]['max_tokens'],4096)
    def test_agent_resume_uses_exact_session_without_bypass(self):
        session={'remote_id':'specific-session'}
        for provider in ['claude','codex']:
            args=agents.command({'provider':provider,'executable':provider},session,'follow up')
            self.assertIn('specific-session',args)
            self.assertFalse(any('bypass' in a or 'skip-permissions' in a for a in args))
    def test_restart_does_not_replay_agent_actions(self):
        with self.db:self.db.execute("INSERT INTO agent_session VALUES('a','claude','/repo','/worktree','remote','running','{}','',0)")
        agents.recover(self.db)
        self.assertEqual(self.db.execute('SELECT status FROM agent_session').fetchone()[0],'blocked')
    def test_forget_does_not_retain_raw_quote_in_tombstone(self):
        quote='Private source material'
        with self.db:w.remember(self.db,'gmail','owner/thread/message/'+quote,quote)
        w.forget(self.db,'gmail','owner/thread/message/'+quote)
        self.assertIsNone(w.remember(self.db,'gmail','owner/thread/message/'+quote,quote))
        stored=self.db.execute('SELECT source_key FROM tombstone').fetchone()[0]
        self.assertNotIn(quote,stored)
    def test_followup_keeps_edited_draft_after_reopening(self):
        ident=w.wait_for(self.db,'thread','a@example.test','an update')
        w.followup_draft(self.db,ident,'My edited draft')
        self.assertEqual(w.followup_draft(self.db,ident)['body'],'My edited draft')
