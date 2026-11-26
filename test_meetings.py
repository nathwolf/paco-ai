import base64
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import app
import meetings as m
import meeting_audio as audio
import models
import paco
import planning


class Meetings(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'tasks.sqlite3';self.db=paco.connect(self.path);app.initialize(self.db)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def imported(self):
        return m.import_transcript(self.db,{'title':'Launch','segments':[
            {'speaker':'Ana','seconds':0,'text':'The client still needs the revised proposal. Can someone pick it up?'},
            {'speaker':'Juan','seconds':8,'text':'Leave it with me, once finance approves the figures.'},
            {'speaker':'Ana','seconds':13,'text':'Great, thanks. Nathalia, could you chase that approval?'},
            {'speaker':'Nathalia','seconds':20,'text':'Sure, I’ll ask finance this afternoon.'},
            {'speaker':'Juan','seconds':33,'text':'Actually I am away. Ana, can you send the proposal instead?'},
            {'speaker':'Ana','seconds':40,'text':'Yes, once the numbers are approved.'}]})
    def candidate(self,ident):
        segs=m.detail(self.db,ident)['segments']
        return {'kind':'action','title':'Send the revised proposal','owner':'Ana','commitment':'conditional','confidence':'high','condition':'Finance approves the figures','deadline':'','reason':'Ana accepted the handoff after Juan withdrew; approval is still required.',
                'evidence':[{'id':s['id'],'quote':s['text']} for s in segs[-2:]]}
    def fake(self,ident,items=None,hook=None):
        calls=[];item=self.candidate(ident)
        def complete(config,prompt,data,source):
            calls.append((prompt,data))
            if 'summary:string' in prompt:
                if hook:hook()
                return {'summary':'Ana will send the proposal after finance approves.'},{}
            return {'items':copy.deepcopy(items if items is not None else [item])},{}
        return complete,calls
    def test_context_review_is_required_before_summary_and_no_implicit_tasks(self):
        ident=self.imported();complete,calls=self.fake(ident);result=m.analyze(self.db,ident,{},complete)
        self.assertEqual(len(calls),3);self.assertIn('later rejection',calls[1][0]);self.assertEqual(len(calls[1][1]['segments']),6)
        self.assertEqual(result['items'][0]['owner'],'Ana');self.assertEqual(result['items'][0]['commitment'],'conditional')
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],0)
        self.assertNotIn('quote',json.loads(self.db.execute('SELECT payload FROM meeting_item').fetchone()[0])['evidence'][0])
    def test_expiry_keeps_notes_and_actions_but_removes_source(self):
        ident=self.imported();complete,_=self.fake(ident);m.analyze(self.db,ident,{},complete)
        expires=m.get(self.db,ident)['expires'];self.assertAlmostEqual(expires-m.get(self.db,ident)['ended'],14*86400)
        m.purge(self.db,expires+1)
        result=m.detail(self.db,ident);self.assertEqual(result['segments'],[]);self.assertTrue(result['transcript_deleted']);self.assertTrue(result['summary']);self.assertTrue(result['items'])
        with self.assertRaises(ValueError):m.analyze(self.db,ident,{},complete)
    def test_model_cannot_cite_fake_or_cross_meeting_evidence(self):
        ident=self.imported();other=self.imported();item=self.candidate(other);complete,_=self.fake(ident,[item])
        with self.assertRaises(ValueError):m.analyze(self.db,ident,{},complete)
        self.assertEqual(m.detail(self.db,ident)['items'],[])
        item=self.candidate(ident);item['evidence'][0]['quote']='invented acceptance';complete,_=self.fake(ident,[item])
        with self.assertRaises(ValueError):m.analyze(self.db,ident,{},complete)
    def test_deletion_during_analysis_cannot_resurrect_content(self):
        ident=self.imported();complete,_=self.fake(ident,hook=lambda:m.delete_transcript(self.db,ident))
        with self.assertRaises(ValueError):m.analyze(self.db,ident,{},complete)
        result=m.detail(self.db,ident);self.assertEqual(result['segments'],[]);self.assertEqual(result['summary'],'');self.assertEqual(result['items'],[])
    def test_review_requires_personal_confirmation_and_blocks_conditional_task(self):
        ident=self.imported();complete,_=self.fake(ident);result=m.analyze(self.db,ident,{},complete);iid=result['items'][0]['id']
        with self.assertRaises(ValueError):m.review_item(self.db,iid,{'status':'accepted'})
        result=m.review_item(self.db,iid,{'status':'accepted','mine':True,'owner':'Nathalia'})
        task=result['task'];self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'blocked')
        self.assertEqual(m.review_item(self.db,iid,{'status':'accepted','mine':True})['task'],task)
        self.assertEqual(self.db.execute('SELECT count(*) FROM task').fetchone()[0],1)
    def test_regeneration_preserves_corrections_and_manual_summary(self):
        ident=self.imported();complete,_=self.fake(ident);result=m.analyze(self.db,ident,{},complete);iid=result['items'][0]['id']
        m.review_item(self.db,iid,{'status':'reviewed','owner':'Nathalia'})
        m.edit_note(self.db,ident,{'summary':'My edited summary'})
        item=self.candidate(ident);item['existing_id']=iid;item['title']='Deliver the updated proposal'
        complete,calls=self.fake(ident,[item]);result=m.analyze(self.db,ident,{},complete)
        self.assertEqual(len(result['items']),1);self.assertEqual(result['items'][0]['owner'],'Nathalia');self.assertEqual(result['summary'],'My edited summary')
        self.assertEqual(calls[-1][1]['items'][0]['owner'],'Nathalia')
    def test_shortening_retention_purges_and_extending_does_not_restore(self):
        ident=self.imported()
        with self.db:self.db.execute('UPDATE meeting_note SET ended=?,expires=? WHERE id=?',(time.time()-3*86400,time.time()+11*86400,ident))
        m.configure(self.db,{'retention_days':2});self.assertTrue(m.detail(self.db,ident)['transcript_deleted'])
        m.configure(self.db,{'retention_days':30});self.assertEqual(m.detail(self.db,ident)['segments'],[])
    def test_capture_protects_focus_and_recovery_marks_partial(self):
        ident=m.create(self.db);self.assertEqual(planning.reason_to_wait(self.db,time.time()),'Meeting in progress')
        m.recover(self.db);result=m.detail(self.db,ident);self.assertTrue(result['partial']);self.assertEqual(result['state'],'transcribed');self.assertIsNotNone(result['expires'])
    def test_bad_import_is_atomic_and_import_replay_does_not_resurrect(self):
        with self.assertRaises(ValueError):m.import_transcript(self.db,{'segments':[{'speaker':'Ana','text':'Fine'},{'speaker':'Juan','text':'bad','seconds':-1}]})
        self.assertEqual(m.list_notes(self.db),[])
        data={'id':'example','segments':[{'speaker':'Ana','text':'Fine'}]};ident=m.import_transcript(self.db,data);m.delete_transcript(self.db,ident)
        self.assertEqual(m.import_transcript(self.db,data),ident);self.assertEqual(m.detail(self.db,ident)['segments'],[])
    def test_remote_identity_cannot_be_treated_as_a_person(self):
        ident=self.imported();item=self.candidate(ident);item['owner']='Remote participants';complete,_=self.fake(ident,[item]);result=m.analyze(self.db,ident,{},complete)
        self.assertEqual(result['items'][0]['owner'],'');self.assertEqual(result['items'][0]['commitment'],'unclear')
    def test_delete_meeting_keeps_explicitly_accepted_task(self):
        ident=self.imported();complete,_=self.fake(ident);item=m.analyze(self.db,ident,{},complete)['items'][0]
        task=m.review_item(self.db,item['id'],{'status':'accepted','mine':True})['task'];m.delete_meeting(self.db,ident)
        self.assertTrue(self.db.execute('SELECT 1 FROM task WHERE id=?',(task,)).fetchone());self.assertEqual(m.list_notes(self.db),[])
    def test_private_model_requires_consent_before_key_or_network(self):
        config={'provider':'private','model':'test','endpoint':'https://example.test/v1'}
        with patch('models.secret') as key:
            with self.assertRaises(ValueError):models.complete(config,'test',{},'meeting')
            key.assert_not_called()
        for url in ['http://remote.test/v1','https://user:secret@example.test','file:///tmp/model','https://example.test/?key=secret']:
            with self.assertRaises(ValueError):models.validate_endpoint(url)
    def test_audio_queue_discards_when_full_and_records_gap(self):
        import queue,threading
        ident=m.create(self.db);s=audio.Session.__new__(audio.Session)
        s.path=self.path;s.connect=paco.connect;s.ident=ident;s.lock=threading.Lock();s.closing=False;s.paused=False;s.sequences={};s.queue=queue.Queue(maxsize=1)
        s.push('microphone',0,0,b'1234')
        with self.assertRaises(ValueError):s.push('microphone',1,8,b'1234')
        self.assertEqual(s.queue.qsize(),1);self.assertTrue(m.detail(self.db,ident)['partial'])
    def test_audio_validates_session_size_and_finite_samples(self):
        class Sink:
            ident='test'
            def push(self,*args):raise AssertionError('invalid audio reached queue')
        with patch.dict(audio.SESSIONS,{str(self.path):Sink()}):
            for data in [b'abc',b'\x00\x00\xc0\x7f',b'\0'*(16000*4*11)]:
                with self.assertRaises(ValueError):audio.audio(self.path,{'id':'test','channel':'microphone','sequence':0,'seconds':0,'pcm':base64.b64encode(data).decode()})


class MeetingLifecycle(unittest.TestCase):
    setUp=Meetings.setUp
    tearDown=Meetings.tearDown
    imported=Meetings.imported
    candidate=Meetings.candidate
    fake=Meetings.fake
    def test_reformat_after_transcript_expiry_uses_only_retained_notes(self):
        ident=self.imported();complete,_=self.fake(ident);m.analyze(self.db,ident,{},complete);m.delete_transcript(self.db,ident)
        seen=[]
        def model(config,prompt,data,source):
            seen.append(data);return {'summary':'A shorter version of the retained notes.'},{}
        result=m.reformat(self.db,ident,{},model)
        self.assertEqual(result['summary'],'A shorter version of the retained notes.');self.assertNotIn('segments',seen[0]);self.assertEqual(result['segments'],[])
    def test_expiry_during_first_model_call_prevents_further_transmission(self):
        ident=self.imported();item=self.candidate(ident);calls=[]
        def model(*args):
            calls.append(args);m.delete_transcript(self.db,ident);return {'items':[item]},{}
        with self.assertRaises(ValueError):m.analyze(self.db,ident,{},model)
        self.assertEqual(len(calls),1)
    def test_reassigned_accepted_action_is_removed_from_personal_plan(self):
        ident=self.imported();complete,_=self.fake(ident);item=m.analyze(self.db,ident,{},complete)['items'][0]
        task=m.review_item(self.db,item['id'],{'status':'accepted','owner':'Nathalia','mine':True})['task']
        m.review_item(self.db,item['id'],{'status':'reviewed','owner':'Juan','mine':False})
        self.assertEqual(self.db.execute('SELECT state FROM task WHERE id=?',(task,)).fetchone()[0],'archived')
        self.assertEqual(m.task_context(self.db,task)[0]['interpretation']['owner'],'Juan')

if __name__=='__main__':unittest.main()
