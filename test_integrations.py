from pathlib import Path
import subprocess
import shlex
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
import agents
import app
import calendar_planning
import connectors
import discovery
import paco


class Integrations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'db';self.db=paco.connect(self.path);app.initialize(self.db)
    def tearDown(self):
        self.db.close();self.tmp.cleanup()
    def test_todoist_pagination_and_identity(self):
        client=Mock();client.get.side_effect=[{'id':'me'},{'results':[{'id':'1','content':'First'}],'next_cursor':'next'},{'results':[{'id':'2','content':'Second'}]}]
        self.assertEqual(len(connectors.snapshot('todoist',client,'me',100)),2)
        client.get.side_effect=[{'id':'someone else'}]
        with self.assertRaises(ValueError):connectors.snapshot('todoist',client,'me',100)
    def test_asana_jira_and_outlook_adapters(self):
        asana=Mock();asana.get.side_effect=[{'data':{'gid':'me','workspaces':[{'gid':'ws'}]}},{'data':[{'name':'Task','permalink_url':'https://app.asana.com/task','completed':False}]}]
        self.assertEqual(connectors.snapshot('asana',asana,'me',0)[0][1],'Task')
        jira=Mock();jira.base='https://team.atlassian.net/rest/api/3';jira.get.side_effect=[{'accountId':'me'},{'issues':[{'key':'P-1','fields':{'summary':'Do work'}}]}]
        self.assertEqual(connectors.snapshot('jira',jira,'me',0)[0][0],'https://team.atlassian.net/browse/P-1')
        outlook=Mock();outlook.get.side_effect=[{'id':'me'},{'value':[{'webLink':'https://outlook.office.com/message','subject':'Flagged'}]}]
        self.assertEqual(connectors.snapshot('outlook',outlook,'me',0)[0][1],'Flagged')
    def test_outlook_refuses_pagination_to_another_origin(self):
        client=Mock();client.get.side_effect=[{'id':'me'},{'value':[],'@odata.nextLink':'https://evil.test/steal'}]
        with self.assertRaises(ValueError):connectors.snapshot('outlook',client,'me',0)
    def test_slack_deduplicates_dm_and_mention(self):
        client=Mock();client.post.return_value={'ok':True,'team_id':'T','user_id':'U'}
        client.get.return_value={'ok':True,'messages':{'matches':[{'permalink':'https://slack.test/message','text':'Can you review?','user':'A','ts':'100'}],'paging':{'pages':1}}}
        self.assertEqual(len(connectors.slack_messages(client,'T/U',200)),1)
        client.get.return_value={'ok':False,'error':'missing_scope'}
        with self.assertRaises(ValueError):connectors.slack_messages(client,'T/U',200)
    def test_verified_source_outcomes_and_reopen(self):
        discovery.reconcile(self.db,'github',[('issue','Work',0)],0)
        discovery.source_outcome(self.db,'github','issue','cancelled',10)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'cancelled')
        discovery.reconcile(self.db,'github',[('issue','Work',0)],20)
        discovery.source_outcome(self.db,'github','issue','completed',30)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'done')
        discovery.reconcile(self.db,'github',[('issue','Work',0)],40)
        self.assertEqual(self.db.execute('SELECT state FROM task').fetchone()[0],'open')
    def test_calendar_conflicts_and_etag_prevents_stale_write(self):
        with self.db:
            self.db.execute("INSERT INTO calendar_event VALUES('primary:a','primary','A',100,200,'https://calendar.test','v1','[\"a@example.test\"]')")
            self.db.execute("INSERT INTO calendar_event VALUES('apple:b','apple:cal','B',150,250,'','','[]')")
        self.assertEqual(len(calendar_planning.conflicts(self.db)),1)
        proposal=calendar_planning.preview(self.db,'primary:a','2026-11-26T10:00+01:00','2026-11-26T11:00+01:00')
        self.assertEqual(proposal['notify_attendees'],['a@example.test'])
        session=Mock();session.get.return_value.json.return_value={'etag':'v2'}
        with self.assertRaises(ValueError):calendar_planning.apply(self.db,session,proposal['id'])
        session.patch.assert_not_called()
        with self.assertRaises(ValueError):calendar_planning.preview(self.db,'apple:b','2026-11-26T10:00+01:00','2026-11-26T11:00+01:00')
    def test_both_agent_protocols_isolated_work_followup_and_denial(self):
        repo=self.root/'repo';repo.mkdir()
        for cmd in [['git','init',str(repo)],['git','-C',str(repo),'config','user.email','test@example.test'],['git','-C',str(repo),'config','user.name','Paco Test']]:
            subprocess.run(cmd,check=True,capture_output=True)
        (repo/'README').write_text('Original')
        subprocess.run(['git','-C',str(repo),'add','.'],check=True,capture_output=True)
        subprocess.run(['git','-C',str(repo),'commit','-m','initial'],check=True,capture_output=True)
        for provider in ('claude','codex'):
            fake=self.root/provider
            # A kernel shebang cannot contain a Python path with spaces, as in
            # the installed Application Support environment. Quote via a shell.
            fake.write_text("#!/bin/sh\n'''exec' " + shlex.quote(sys.executable) + " \"$0\" \"$@\"\n' '''\n"+'''import sys,json,pathlib
text=sys.stdin.read()
provider=pathlib.Path(sys.argv[0]).name
resume='--resume' in sys.argv or 'resume' in sys.argv
pathlib.Path('result.txt').write_text('followup' if resume else 'first')
if provider=='claude':
 print(json.dumps({'type':'system','subtype':'init','session_id':'session-123','tools':['Read','Edit']}))
 print(json.dumps({'type':'result','result':'followup' if resume else 'completed','permission_denials':[{'tool_name':'Bash','tool_input':{'command':'restricted'}}] if text.strip()=='denied' else []}))
else:
 print(json.dumps({'type':'thread.started','thread_id':'session-123'}))
 print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'followup' if resume else 'completed'}}))
 if text.strip()=='denied': print(json.dumps({'type':'turn.failed'}))
''')
            fake.chmod(0o700)
            with self.db:self.db.execute('INSERT OR REPLACE INTO agent_connection VALUES(?,?,?,1)',(provider,str(fake),str(repo)))
            ident=agents.prepare(self.db,provider,'Write a local test file')
            def wait():
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    row=self.db.execute('SELECT * FROM agent_session WHERE id=?',(ident,)).fetchone()
                    if row['status']!='running' and ident not in agents.RUNNING:return row
                    time.sleep(.02)
                self.fail('Agent fixture timed out')
            agents.execute(self.path,paco.connect,ident);row=wait()
            self.assertEqual(row['status'],'completed')
            self.assertEqual((Path(row['worktree'])/'result.txt').read_text(),'first')
            self.assertFalse((repo/'result.txt').exists())
            agents.execute(self.path,paco.connect,ident,'Continue this exact session');row=wait()
            self.assertEqual(row['status'],'completed')
            self.assertEqual((Path(row['worktree'])/'result.txt').read_text(),'followup')
            agents.execute(self.path,paco.connect,ident,'denied');row=wait()
            self.assertEqual(row['status'],'blocked')
    def test_manual_archive_and_title_survive_source_replay(self):
        discovery.reconcile(self.db,'github',[('issue','Original',0)],0)
        import workflows
        workflows.correct_task(self.db,1,title='My title',state='archived')
        discovery.reconcile(self.db,'github',[],10)
        discovery.reconcile(self.db,'github',[('issue','Remote title',0)],20)
        row=self.db.execute('SELECT title,state FROM task').fetchone()
        self.assertEqual(tuple(row),('My title','archived'))
    def test_legacy_calendar_identity_migrates_without_duplicate(self):
        discovery.reconcile(self.db,'calendar',[('event1','Meeting',100)],0)
        discovery.reconcile(self.db,'calendar',[('primary:event1','Meeting moved',200)],100)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
        self.assertEqual(self.db.execute('SELECT due FROM task').fetchone()[0],200)
