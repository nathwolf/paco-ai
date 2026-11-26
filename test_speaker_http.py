import json
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
import meeting_audio
import meeting_bridge
import meetings
import test_http


class SpeakerHTTP(unittest.TestCase):
    setUp=test_http.HTTP.setUp
    tearDown=test_http.HTTP.tearDown
    request=test_http.HTTP.request
    def test_speaker_pair_is_write_only_and_expires_with_capture(self):
        import paco
        with paco.connect(self.path) as db:ident=meetings.create(db)
        class Session:
            paused=False;closing=False;audio_origin=time.time()-10
            queue=type('Queue',(),{'qsize':lambda _:0})()
        session=Session();session.ident=ident
        try:
            with patch.dict(meeting_audio.SESSIONS,{str(self.path):session}):
                pair=json.load(self.request('/api/action',{'action':'meeting_pair'}))
                headers={'Authorization':'Bearer '+pair['token'],'Origin':'chrome-extension://example','Content-Type':'application/json'}
                data={'url':'https://meet.google.com/abc-defg-hij','status':'ok','participants':[{'id':'j','name':'Juan'}],'active':['j']}
                request=urllib.request.Request(self.base+'/api/speaker-signal',headers=headers,data=json.dumps(data).encode())
                with urllib.request.urlopen(request,timeout=3) as r:
                    self.assertEqual(r.headers['Access-Control-Allow-Origin'],'chrome-extension://example');self.assertTrue(json.load(r)['ok'])
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(self.base+'/api/state',headers=headers),timeout=3)
                self.assertEqual(error.exception.code,401)
                session.closing=True
                with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=3)
                self.assertEqual(error.exception.code,403)
        finally:meeting_bridge.revoke(self.path)
    def test_web_origin_cannot_use_bridge_preflight(self):
        request=urllib.request.Request(self.base+'/api/speaker-signal',method='OPTIONS',headers={'Origin':'https://evil.test'})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,403)
    def test_malformed_signal_returns_controlled_error(self):
        request=urllib.request.Request(self.base+'/api/speaker-signal',headers={'Origin':'chrome-extension://example','Content-Type':'application/json'},data=b'[]')
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=3)
        self.assertEqual(error.exception.code,400)

if __name__=='__main__':unittest.main()
