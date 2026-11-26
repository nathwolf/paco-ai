import json
import tempfile
import unittest
from pathlib import Path

import app
import meeting_identity as identity
import paco


class CalendarMeetings(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db';self.db=paco.connect(self.path);self.addCleanup(self.db.close)
        app.initialize(self.db);self.now=1800000000

    def event(self,ident,title,people=None,url='https://calendar.google.com/event',start=None):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO calendar_event VALUES(?,?,?,?,?,?,?,?)',
                (ident,'cal',title,start or self.now,self.now+3600,url,'etag','[]'))
            self.db.execute('INSERT OR REPLACE INTO calendar_people VALUES(?,?,?)',(ident,json.dumps(people or []),self.now))

    def test_clear_blocks_and_errands_are_not_meeting_suggestions(self):
        for n,title in enumerate(['x',' X ','xxx','Busy','Focus time: writing','Deep work','Almuerzo','Vacaciones',
                                  'Print & check documents — US B-1 visa interview preparation',
                                  'Get 2 US visa passport photos']):
            self.event(str(n),title)
        self.event('meeting','Reu semanal marcos')
        ids={e['id'] for e in identity.upcoming(self.db,self.now)}
        self.assertEqual(ids,{'meeting'})
        self.assertEqual({e['id'] for e in identity.candidates(self.db,self.now)},ids)
        self.assertTrue(all(e['reason'] for e in identity.upcoming(self.db,self.now,hidden=True)))

    def test_solo_errand_is_hidden_but_invited_or_call_link_event_is_kept(self):
        self.event('solo','Print & check documents')
        self.event('invite','Buy materials',[{'email':'juan@example.test','name':'Juan'}])
        self.event('call','Deep work','',url='https://meet.google.com/abc-defg-hij')
        self.event('unknown','REBECAI')
        self.event('group','Focus group')
        self.event('placeholder','x',[{'email':'juan@example.test'}])
        self.assertEqual({e['id'] for e in identity.upcoming(self.db,self.now)}, {'invite','call','unknown','group'})

    def test_removal_and_restore_survive_sync_without_touching_calendar_or_busy(self):
        self.event('e','Planning')
        with self.db:self.db.execute('INSERT INTO busy VALUES(?,?)',(self.now,self.now+3600))
        before=tuple(self.db.execute('SELECT * FROM calendar_event WHERE id=?',('e',)).fetchone())
        app.act(self.db,self.path,paco.connect,{'action':'meeting_calendar_visibility','event':'e','visible':False})
        self.assertEqual(identity.upcoming(self.db,self.now),[])
        self.assertEqual(identity.candidates(self.db,self.now),[])
        self.assertEqual(tuple(self.db.execute('SELECT * FROM calendar_event WHERE id=?',('e',)).fetchone()),before)
        self.assertEqual(self.db.execute('SELECT count(*) FROM busy').fetchone()[0],1)
        with self.db:self.db.execute('DELETE FROM calendar_event')
        self.event('e','Planning (updated)')
        self.assertEqual(identity.upcoming(self.db,self.now),[])
        app.act(self.db,self.path,paco.connect,{'action':'meeting_calendar_visibility','event':'e','visible':True})
        self.assertEqual(identity.upcoming(self.db,self.now)[0]['title'],'Planning (updated)')

    def test_show_overrides_automatic_filter_and_keeps_meeting_context_available(self):
        self.event('block','x')
        self.assertEqual(identity.upcoming(self.db,self.now),[])
        identity.calendar_visibility(self.db,'block',True)
        self.assertEqual(identity.suggested_event(identity.candidates(self.db,self.now),self.now),'block')
        self.assertEqual(identity.upcoming(self.db,self.now,hidden=True),[])

    def test_filtering_happens_before_visible_limit(self):
        for n in range(20):self.event('block'+str(n),'x',start=self.now-1)
        self.event('real','Team meeting')
        self.assertEqual([e['id'] for e in identity.upcoming(self.db,self.now)],['real'])

    def test_invalid_visibility_requests_and_self_only_invites(self):
        self.event('e','Focus time',[{'email':'me@example.test','self':True}])
        self.assertEqual(identity.upcoming(self.db,self.now),[])
        for event,visible in [('missing',False),('e','false'),('e',0),(None,True)]:
            with self.assertRaises(ValueError):identity.calendar_visibility(self.db,event,visible)
        self.assertEqual(self.db.execute('SELECT count(*) FROM meeting_calendar_choice').fetchone()[0],0)


if __name__=='__main__':unittest.main()
