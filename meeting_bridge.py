"""Short-lived, write-only Google Meet speaker pairing. No task/model/API access."""
import hashlib
import secrets
import threading
import time
from urllib.parse import urlsplit
from contextlib import closing
import meeting_audio
import meeting_identity

LOCK=threading.Lock()
PAIRS={}


def create(path):
    active=meeting_audio.active(path)
    if not active or active['finishing']:raise ValueError('Start meeting capture before connecting Google Meet')
    token=secrets.token_urlsafe(32)
    with LOCK:
        PAIRS[str(path)]={'digest':hashlib.sha256(token.encode()).hexdigest(),'meeting':active['id'],
                          'expires':time.monotonic()+4*3600,'last':0,'origin':None,'url':None}
    return {'token':token,'meeting':active['id']}


def revoke(path):
    with LOCK:PAIRS.pop(str(path),None)


def receive(path,connect,token,origin,data):
    if not isinstance(data,dict):raise ValueError('Invalid speaker signal')
    parsed=urlsplit(origin or '')
    if parsed.scheme!='chrome-extension' or not parsed.hostname or parsed.path not in ('','/'):
        raise PermissionError('Only the paired browser extension can send speaker signals')
    with LOCK:
        pair=PAIRS.get(str(path));active=meeting_audio.active(path)
        if not pair or not secrets.compare_digest(pair['digest'],hashlib.sha256(token.encode()).hexdigest()) or time.monotonic()>pair['expires'] or not active or active['id']!=pair['meeting'] or active['finishing']:
            raise PermissionError('Pairing has expired. Connect this meeting again from Paco.')
        if pair['origin'] and pair['origin']!=origin:raise PermissionError('This code is already paired to another extension')
        url=urlsplit(str(data.get('url','')))
        if url.scheme!='https' or url.hostname!='meet.google.com' or url.query or url.fragment or not url.path.strip('/'):
            raise ValueError('Invalid Google Meet call URL')
        call='https://meet.google.com'+url.path
        if pair['url'] and pair['url']!=call:raise PermissionError('This pairing belongs to a different call')
        if time.monotonic()-pair['last']<.2:raise ValueError('Speaker signals arrived too quickly')
        with meeting_audio.LOCK:session=meeting_audio.SESSIONS.get(str(path))
        if not session or session.paused:return {'ok':True,'status':'paused'}
        if getattr(session,'audio_origin',None) is None:return {'ok':True,'status':'waiting_for_audio'}
        with closing(connect(path)) as db:
            ctx=meeting_identity.context(db,pair['meeting']);expected=urlsplit((ctx.get('event') or {}).get('url',''))
            if expected.hostname=='meet.google.com' and expected.path!=url.path:raise PermissionError('This call does not match the linked calendar event')
            sample={'seconds':max(0,time.monotonic()-session.monotonic_origin if hasattr(session,'monotonic_origin') else time.time()-session.audio_origin),'source':'google_meet',
                    'status':data.get('status'),'participants':data.get('participants',[]),'active':data.get('active',[])}
            meeting_identity.samples(db,pair['meeting'],[sample])
        pair.update(origin=origin,url=call,last=time.monotonic())
        return {'ok':True,'status':sample['status']}
