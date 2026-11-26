import copy
import json
import threading
import unittest
from unittest.mock import Mock,patch

import websocket
import app
import mattermost_events as events


CONFIG={'base':'https://mattermost.example','account':'owner','user_id':'me',
        'bot':{'enabled':True,'user_id':'bot','channel_id':'dm','username':'paco','mentions_enabled':True}}


def post(message='hello',channel='dm',sender='me',kind='posted',channel_type='D',**extra):
    return {'event':kind,'data':{'channel_type':channel_type,'post':json.dumps(
        dict(id='p',user_id=sender,channel_id=channel,message=message,**extra))}}


class Socket:
    def __init__(self,frames,stop):self.frames=iter(frames);self.stop=stop;self.closed=False;self.pings=[]
    def settimeout(self,value):self.timeout=value
    def recv_data(self,control_frame):
        try:return next(self.frames)
        except StopIteration:
            self.stop.set()
            raise websocket.WebSocketTimeoutException()
    def close(self,timeout):self.closed=True
    def ping(self,value):self.pings.append(value)


def frame(event):return websocket.ABNF.OPCODE_TEXT,json.dumps(event)


class Realtime(unittest.TestCase):
    def test_only_owner_dm_and_explicit_shared_mentions_wake(self):
        self.assertTrue(events.relevant(post(),CONFIG))
        self.assertTrue(events.relevant(post('@paco help','group','coworker',channel_type='G'),CONFIG))
        self.assertTrue(events.relevant(post('@paco help','channel','coworker',kind='post_edited',channel_type='P'),CONFIG))
        for event in [post(sender='bot'),post(sender='stranger'),post('hello','group',channel_type='G'),
                      post('@paco help','other-dm',channel_type='D'),post('@pacote help','group',channel_type='G'),
                      post('> @paco help','group',channel_type='G'),post('hello',delete_at=1),
                      post('hello',type='system_join_channel'),post(kind='typing'),{'event':'posted','data':{'post':'bad'}},
                      {'event':'posted','data':{'post':'[]'}},None]:
            self.assertFalse(events.relevant(event,CONFIG),event)
        disabled=copy.deepcopy(CONFIG);disabled['bot']['enabled']=False
        self.assertFalse(events.relevant(post(),disabled))
        disabled['bot']['enabled']=True;disabled['bot']['mentions_enabled']=False
        self.assertTrue(events.relevant(post(),disabled))
        self.assertFalse(events.relevant(post('@paco help','group',channel_type='G'),disabled))

    def test_authenticated_stream_wakes_and_never_follows_redirects(self):
        stop=threading.Event();wake=Mock();ready=Mock()
        ws=Socket([frame(post()),frame({'event':'hello'}),frame(post()),frame(post(sender='bot')),
                   frame(post('@paco help','group',channel_type='G'))],stop)
        connect=Mock(return_value=ws)
        with patch('mattermost_events.keyring.get_password',return_value='secret'):
            events.stream(CONFIG,stop,wake,lambda:CONFIG,lambda:True,ready,connect)
        self.assertEqual(wake.set.call_count,3)  # reconnect catch-up, owner DM, group mention
        ready.assert_called_once();self.assertTrue(ws.closed)
        self.assertEqual(connect.call_args.args,('wss://mattermost.example/api/v4/websocket',))
        self.assertEqual(connect.call_args.kwargs['redirect_limit'],0)
        self.assertEqual(connect.call_args.kwargs['header'],{'Authorization':'Bearer secret'})
        self.assertEqual(ws.timeout,1)

    def test_lock_or_config_revocation_closes_socket(self):
        for current,gate in [(lambda:None,lambda:True),(lambda:CONFIG,lambda:False)]:
            stop=threading.Event();ws=Socket([],stop);wake=Mock()
            with patch('mattermost_events.keyring.get_password',return_value='secret'):
                events.stream(CONFIG,stop,wake,current,gate,Mock(),lambda *a,**k:ws)
            self.assertTrue(ws.closed);wake.set.assert_not_called()

    def test_heartbeat_and_timeout_close_stale_connections(self):
        stop=threading.Event();ws=Socket([frame({'event':'hello'}),(websocket.ABNF.OPCODE_PONG,b'paco')],stop)
        ticks=iter([0,0,0,21,22])
        with patch('mattermost_events.keyring.get_password',return_value='secret'):
            events.stream(CONFIG,stop,Mock(),lambda:CONFIG,lambda:True,Mock(),lambda *a,**k:ws,lambda:next(ticks))
        self.assertEqual(ws.pings,['paco']);self.assertTrue(ws.closed)
        stop=threading.Event();ws=Socket([frame({'event':'hello'}),frame({'event':'typing'})],stop)
        ticks=iter([0,0,0,21,32])
        with patch('mattermost_events.keyring.get_password',return_value='secret'),self.assertRaises(TimeoutError):
            events.stream(CONFIG,stop,Mock(),lambda:CONFIG,lambda:True,Mock(),lambda *a,**k:ws,lambda:next(ticks))
        self.assertTrue(ws.closed)

    def test_closed_socket_is_reconnected_with_safe_diagnostics(self):
        stop=threading.Event();wake=Mock();reports=[];calls=[]
        def stream(config,stop,wake,current,gate,ready):
            calls.append(1)
            if len(calls)==1:raise ValueError('secret token and private message')
            ready();stop.set()
        with patch('mattermost_events.stream',side_effect=stream),patch.object(stop,'wait',return_value=False):
            events.listen(stop,wake,lambda:CONFIG,lambda:True,lambda *r:reports.append(r))
        self.assertEqual(len(calls),2)
        self.assertIn('periodic checks continue',reports[0][1]);self.assertIsNone(reports[1][1])
        self.assertNotIn('secret',str(reports))

    def test_event_during_reply_triggers_next_pass_without_waiting(self):
        stop=threading.Event();wake=threading.Event();calls=[]
        def step():
            calls.append(1)
            if len(calls)==1:wake.set()
            else:stop.set()
        thread=threading.Thread(target=app.run_loop,args=('chat',stop,30,step,None,None,wake),daemon=True)
        thread.start();thread.join(1);stop.set()
        self.assertFalse(thread.is_alive());self.assertEqual(len(calls),2)

    def test_event_wakes_idle_worker_and_timer_still_recovers(self):
        for use_event in (True,False):
            stop=threading.Event();wake=threading.Event();first=threading.Event();calls=[]
            def step():
                calls.append(1);first.set()
                if len(calls)==2:stop.set()
            thread=threading.Thread(target=app.run_loop,args=('chat',stop,30 if use_event else .02,step,None,None,wake),daemon=True)
            thread.start();self.assertTrue(first.wait(1))
            if use_event:wake.set()
            thread.join(1);stop.set()
            self.assertFalse(thread.is_alive());self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
