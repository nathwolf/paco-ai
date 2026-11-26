import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import app
import meeting_audio
import meeting_bridge as bridge
import meeting_identity as identity
import meetings
import paco


class SpeakerIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'tasks.sqlite3';self.db=paco.connect(self.path);app.initialize(self.db);self.now=time.time()
        self.people=[{'name':'Nathalia','email':'me@example.test','self':True},{'name':'Juan','email':'juan@example.test','status':'accepted'}]
        self.event('one',self.people)
        self.ident=meetings.create(self.db)
        identity.bind(self.db,self.ident,'one')
    def tearDown(self):
        bridge.revoke(self.path);self.db.close();self.tmp.cleanup()
    def event(self,ident,people,start=None,end=None,synced=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',(ident,'calendar','Planning',start or self.now-60,end or self.now+1800,'https://meet.google.com/abc-defg-hij','',json.dumps([p.get('email','') for p in people])))
            self.db.execute('INSERT OR REPLACE INTO calendar_people VALUES(?,?,?)',(ident,json.dumps(people),self.now if synced is None else synced))
    def samples(self,names=None,active=None,source='zoom',times=None,status='ok'):
        names=names or [{'id':'self','name':'Nathalia','self':True},{'id':'j','name':'Juan','self':False}]
        identity.samples(self.db,self.ident,[{'seconds':t,'source':source,'status':status,'participants':names,'active':['j'] if active is None else active} for t in (times or [0,.5,1,1.5,2,2.5,3])])
    def test_calendar_one_to_one_is_tentative_not_observed(self):
        value=identity.resolve(self.db,self.ident,'system',0,3)
        self.assertEqual(value['speaker'],'Juan');self.assertEqual(value['source'],'calendar_inferred');self.assertEqual(value['confidence'],'tentative')
        self.assertEqual(identity.resolve(self.db,self.ident,'microphone',0,3)['speaker'],'Nathalia')
    def test_group_invite_does_not_guess_from_calendar(self):
        self.event('group',self.people+[{'name':'Ana','email':'ana@example.test'}]);identity.bind(self.db,self.ident,'group')
        self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_declined_and_resource_invitees_are_not_candidates(self):
        result=identity.normalize_people(self.people+[{'name':'Declined','status':'declined'},{'name':'Room','resource':True}])
        self.assertEqual(len(result),2)
    def test_missing_self_or_stale_calendar_prevents_inferred_identity(self):
        for people,synced in [(self.people[1:],self.now),(self.people,self.now-4000)]:
            self.event('other',people,synced=synced);identity.bind(self.db,self.ident,'other')
            self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_only_one_current_event_is_suggested(self):
        self.assertEqual(identity.suggested_event(identity.candidates(self.db)),'one')
        self.event('two',self.people)
        self.assertIsNone(identity.suggested_event(identity.candidates(self.db)))
    def test_unique_meeting_soon_is_suggested_but_ambiguous_invites_are_not(self):
        events=[{'id':'next','start':self.now+600,'end':self.now+1800}]
        self.assertEqual(identity.suggested_event(events,self.now),'next')
        events.append({'id':'other','start':self.now+700,'end':self.now+1900})
        self.assertIsNone(identity.suggested_event(events,self.now))
        self.assertIsNone(identity.suggested_event([{'id':'later','start':self.now+3600,'end':self.now+7200}],self.now))
    def test_shared_microphone_does_not_name_everyone_as_user(self):
        identity.bind(self.db,self.ident,'one',microphone_only=True)
        self.assertEqual(identity.resolve(self.db,self.ident,'microphone',0,3)['speaker'],'In-room participants')
    def test_covered_turn_uses_active_speaker_and_exact_calendar_identity(self):
        self.samples();result=identity.resolve(self.db,self.ident,'system',0,3)
        self.assertEqual(result['source'],'zoom');self.assertEqual(result['speaker'],'Juan');self.assertEqual(result['participant'],'juan@example.test')
    def test_uninvited_guest_uses_call_display_name_without_fuzzy_matching(self):
        self.samples(names=[{'id':'j','name':'John'}]);result=identity.resolve(self.db,self.ident,'system',0,3)
        self.assertEqual(result['speaker'],'John');self.assertEqual(result['participant'],'zoom:j')
    def test_roster_only_is_not_speaker_evidence(self):
        self.samples(active=[]);self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_duplicate_names_and_overlap_remain_unknown(self):
        names=[{'id':'j','name':'Juan'},{'id':'b','name':'Juan'}]
        self.samples(names=names);self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
        self.samples(names=[{'id':'j','name':'Juan'},{'id':'a','name':'Ana'}],active=['j','a'])
        self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_handoff_within_segment_cannot_be_assigned_to_last_speaker(self):
        people=[{'id':'j','name':'Juan'},{'id':'a','name':'Ana'}]
        self.samples(names=people,times=[0,.5,1]);self.samples(names=people,active=['a'],times=[1.5,2,2.5,3])
        self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_stale_signal_and_lost_roster_never_restore_calendar_guess(self):
        self.samples();self.samples(names=[],active=[],status='unavailable',times=[20])
        self.assertEqual(identity.resolve(self.db,self.ident,'system',20,23)['source'],'unknown')
    def test_signal_gap_leaves_short_turn_unnamed(self):
        self.samples(times=[0]);self.assertEqual(identity.resolve(self.db,self.ident,'system',2,4)['source'],'unknown')
    def test_google_meet_uses_same_attribution_rules(self):
        self.samples(source='google_meet');self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'google_meet')
    def test_cross_app_conflicting_signals_are_not_combined(self):
        self.samples(source='zoom',times=[0,1,2]);self.samples(source='google_meet',names=[{'id':'j','name':'Ana'}],times=[.5,1.5,2.5])
        self.assertEqual(identity.resolve(self.db,self.ident,'system',0,3)['source'],'unknown')
    def test_user_correction_overrides_signal_and_expiry_deletes_timeline(self):
        self.samples();sid=meetings.segment(self.db,self.ident,'Juan',0,'Leave it with me.')
        identity.save_attribution(self.db,sid,self.ident,'system',3,identity.resolve(self.db,self.ident,'system',0,3))
        note=meetings.edit_note(self.db,self.ident,{'segment':sid,'speaker':'Ana'})
        self.assertEqual(note['segments'][0]['identity']['source'],'user');self.assertEqual(note['segments'][0]['speaker'],'Ana')
        meetings.finish(self.db,self.ident);meetings.delete_transcript(self.db,self.ident)
        self.assertEqual(self.db.execute('SELECT count(*) FROM meeting_speaker_sample').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM meeting_segment_identity').fetchone()[0],0)
    def test_tentative_calendar_name_cannot_be_upgraded_by_model(self):
        source={'id':'s','text':'Leave it with me.','seconds':0,'speaker':'Juan','identity':{'source':'calendar_inferred'}}
        item={'kind':'action','title':'Send proposal','owner':'Juan','commitment':'confirmed','confidence':'high','evidence':[{'id':'s','quote':'Leave it with me.'}]}
        result=meetings.validate_items({'items':[item]},{'s':source})[0]
        self.assertEqual(result['confidence'],'low');self.assertEqual(result['commitment'],'unclear')
    def test_word_timing_splits_turns_without_assigning_boundary_words(self):
        from types import SimpleNamespace as S
        people=[{'id':'j','name':'Juan'},{'id':'a','name':'Ana'}]
        self.samples(names=people,times=[0,.5,1,1.5]);self.samples(names=people,active=['a'],times=[2,2.5,3,3.5,4])
        seg=S(start=.4,end=3.5,text='I can. Yes thanks.',words=[S(start=.4,end=.7,word='I'),S(start=.8,end=1.2,word=' can.'),S(start=1.8,end=2.1,word=' Yes'),S(start=3,end=3.5,word=' thanks.')])
        parts=identity.attributed_parts(self.db,self.ident,'system',0,seg)
        self.assertEqual([p['identity']['speaker'] for p in parts],['Juan','Remote participants','Ana'])
        self.assertEqual(''.join(p['text'] for p in parts),'I can. Yes thanks.')
    def test_invalid_sample_is_atomic(self):
        with self.assertRaises(ValueError):self.samples(active=['not-in-roster'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM meeting_speaker_sample').fetchone()[0],0)
    def test_unknown_segment_cannot_create_cross_meeting_identity(self):
        with self.assertRaises(ValueError):meetings.edit_note(self.db,self.ident,{'segment':'foreign','speaker':'Ana'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM meeting_segment_identity').fetchone()[0],0)
    def test_pair_only_accepts_matching_active_meeting_and_extension(self):
        class Session:
            ident=self.ident;paused=False;closing=False;audio_origin=time.time()-10
            queue=type('Queue',(),{'qsize':lambda _:0})()
        with patch.dict(meeting_audio.SESSIONS,{str(self.path):Session()}):
            pair=bridge.create(self.path)
            data={'url':'https://meet.google.com/abc-defg-hij','status':'ok','participants':[{'id':'j','name':'Juan'}],'active':['j']}
            with self.assertRaises(PermissionError):bridge.receive(self.path,paco.connect,pair['token'],'https://evil.test',data)
            with self.assertRaises(PermissionError):bridge.receive(self.path,paco.connect,'wrong','chrome-extension://abc',data)
            self.assertTrue(bridge.receive(self.path,paco.connect,pair['token'],'chrome-extension://abc',data)['ok'])
            with self.assertRaises(PermissionError):bridge.receive(self.path,paco.connect,pair['token'],'chrome-extension://other',data)
            with self.assertRaises(PermissionError):bridge.receive(self.path,paco.connect,pair['token'],'chrome-extension://abc',{**data,'url':'https://meet.google.com/xxx-yyyy-zzz'})
            bridge.revoke(self.path)
            with self.assertRaises(PermissionError):bridge.receive(self.path,paco.connect,pair['token'],'chrome-extension://abc',data)
    def test_calendar_google_sync_preserves_name_self_and_response(self):
        import discovery
        class Response:
            def raise_for_status(self):pass
            def json(self):return {'items':[{'id':'e','summary':'Planning','start':{'dateTime':'2026-11-25T10:00:00Z'},'end':{'dateTime':'2026-11-25T11:00:00Z'},'attendees':[{'email':'me@example.test','displayName':'Nathalia','self':True,'responseStatus':'accepted'},{'email':'juan@example.test','displayName':'Juan'}]}]}
        class Client:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def get(self,*args,**kwargs):return Response()
        events=[];people=[]
        with patch('discovery.google_session',return_value=Client()):list(discovery.google_rows('calendar',0,events_out=events,people_out=people))
        self.assertEqual(json.loads(events[0][-1]),['me@example.test','juan@example.test'])
        rich=json.loads(people[0][1]);self.assertEqual(rich[0]['name'],'Nathalia');self.assertTrue(rich[0]['self']);self.assertEqual(rich[1]['name'],'Juan')

if __name__=='__main__':unittest.main()
