"""Read-only websocket wake-ups; REST remains authoritative for every reply.

No event text is persisted or sent to a model here. An event only wakes the
existing serialized, receipt-protected Mattermost worker.
"""
import json
import logging
import time

import keyring
import websocket

import mattermost
from mattermost_mentions import mentioned


def enabled(config):
    bot=(config or {}).get('bot',{})
    return bool(bot.get('enabled') and bot.get('user_id') and bot.get('channel_id')
                and config.get('account') and config.get('user_id'))


def relevant(event,config):
    if not enabled(config) or not isinstance(event,dict) or event.get('event') not in ('posted','post_edited'):
        return False
    try:
        data=event['data'];post=json.loads(data['post'])
        if not isinstance(post,dict):return False
        bot=config['bot'];sender=post.get('user_id');channel=post.get('channel_id')
        if not sender or not channel or sender==bot['user_id'] or post.get('delete_at') or post.get('type'):
            return False
        text=post.get('message')
        if not isinstance(text,str) or not text.strip():return False
        if channel==bot['channel_id']:return sender==config['user_id']
        # Some edit events omit channel_type. REST will recheck membership/type;
        # this hint never grants permission to read, act, or send a reply.
        return bool(bot.get('mentions_enabled') and data.get('channel_type')!='D'
                    and mentioned(text,bot.get('username','paco')))
    except (KeyError,TypeError,ValueError):
        return False


def stream(config,stop,wake,current,gate,ready,connector=None,clock=time.monotonic):
    token=keyring.get_password('paco.mattermost.bot',config['account'])
    if not token:raise ValueError('Reconnect the Paco Mattermost bot')
    url='wss://'+mattermost.origin(config['base']).removeprefix('https://')+'/api/v4/websocket'
    # Never forward the bearer credential to a redirected host.
    ws=(connector or websocket.create_connection)(url,header={'Authorization':'Bearer '+token},
        timeout=5,redirect_limit=0,suppress_origin=True)
    try:
        ws.settimeout(1)
        authenticated=False;hello_deadline=clock()+10;next_ping=clock()+20;pong_deadline=None
        while not stop.is_set() and gate() and current()==config:
            now=clock()
            if not authenticated and now>=hello_deadline:raise TimeoutError('Websocket authentication timed out')
            if pong_deadline is not None and now>=pong_deadline:raise TimeoutError('Websocket heartbeat timed out')
            if authenticated and now>=next_ping:
                ws.ping('paco');pong_deadline=now+10;next_ping=now+20
            try:opcode,raw=ws.recv_data(control_frame=True)
            except websocket.WebSocketTimeoutException:continue
            if opcode==websocket.ABNF.OPCODE_CLOSE:raise ConnectionError('Websocket closed')
            if opcode==websocket.ABNF.OPCODE_PONG:pong_deadline=None;continue
            if opcode!=websocket.ABNF.OPCODE_TEXT:continue
            try:event=json.loads(raw)
            except (ValueError,TypeError):continue
            if not isinstance(event,dict):continue
            if event.get('event')=='hello' and not authenticated:
                authenticated=True;ready();wake.set()  # Recover messages missed while disconnected.
            elif authenticated and relevant(event,config):wake.set()
    finally:
        ws.close(timeout=1)


def listen(stop,wake,current,gate,report):
    delay=1
    while not stop.is_set():
        try:
            config=current()
            if not enabled(config) or not gate():
                stop.wait(1)
                continue
            def ready():
                nonlocal delay
                delay=1
                logging.getLogger('paco').info('Mattermost live events connected')
                report('Mattermost events',None)
            stream(config,stop,wake,current,gate,ready)
        except Exception:
            # No raw server errors, tokens, payloads or message text in diagnostics.
            report('Mattermost events','Live connection unavailable; periodic checks continue')
            if stop.wait(delay):break
            delay=min(delay*2,60)
