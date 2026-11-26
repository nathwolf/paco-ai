"""Bounded, volatile PCM queues. Only transcript text reaches SQLite.

The native app sends mono Float32/16kHz chunks over authenticated loopback HTTP.
Local Whisper receives numpy arrays; never file paths or cloud audio requests.
"""
import base64
from contextlib import closing
import importlib.util
import math
import queue
import struct
import threading
import time
import meetings
import meeting_identity

MODEL_NAME='small'
LOCK=threading.RLock()
SESSIONS={}
JOBS={}
MODEL=None
MODEL_STATE='not_loaded'
MODEL_ERROR=''


def model_dir():
    import discovery
    return discovery.ROOT/'models'/'meeting-whisper-small'


def readiness():
    return {'installed':importlib.util.find_spec('faster_whisper') is not None,
            'downloaded':(model_dir()/'model.bin').exists(),'state':MODEL_STATE,'error':MODEL_ERROR,
            'model':MODEL_NAME,'audio_storage':'memory_only'}


def prepare():
    global MODEL_STATE, MODEL_ERROR
    with LOCK:
        if MODEL_STATE in ('loading','ready'):return readiness()
        if importlib.util.find_spec('faster_whisper') is None:raise ValueError('Install meeting dependencies: .venv/bin/python -m pip install -r requirements-meetings.txt')
        MODEL_STATE='loading';MODEL_ERROR=''
    def work():
        global MODEL,MODEL_STATE,MODEL_ERROR
        try:
            from faster_whisper import WhisperModel
            from faster_whisper.utils import download_model
            directory=model_dir(); directory.mkdir(parents=True,exist_ok=True)
            if not (directory/'model.bin').exists():download_model(MODEL_NAME,output_dir=str(directory))
            MODEL=WhisperModel(str(directory),device='cpu',compute_type='int8',cpu_threads=4)
            MODEL_STATE='ready'
        except Exception:
            MODEL_STATE='error';MODEL_ERROR='Could not prepare local speech recognition. Check available disk space and the model download connection, then retry.'
    threading.Thread(target=work,daemon=True).start()
    return readiness()


def load_cached():
    global MODEL,MODEL_STATE
    if MODEL is not None:return MODEL
    if not readiness()['downloaded']:raise ValueError('Prepare local speech recognition in Meeting notes first')
    from faster_whisper import WhisperModel
    MODEL=WhisperModel(str(model_dir()),device='cpu',compute_type='int8',cpu_threads=4,local_files_only=True)
    MODEL_STATE='ready'
    return MODEL


class Session:
    def __init__(self,path,connect,ident,language,model,config,microphone_speaker=None):
        self.path=path;self.connect=connect;self.ident=ident;self.language=language;self.model=model;self.config=config;self.microphone_speaker=microphone_speaker
        self.queue=queue.Queue(maxsize=12) # <=120 seconds / ~7.7MB of PCM; never spills to disk.
        self.audio_origin=None;self.received=set();self.speech_channels=set();self.finished=threading.Event();self.paused=False;self.closing=False;self.last=time.time();self.sequences={};self.lock=threading.Lock()
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def push(self,channel,sequence,seconds,pcm):
        with self.lock:
            if self.closing:raise ValueError('Capture is finished')
            if sequence<=self.sequences.get(channel,-1):return # idempotent transport retry
            self.last=time.time()
            with closing(self.connect(self.path)) as db:
                if channel in self.sequences and sequence!=self.sequences[channel]+1:meetings.gap(db,self.ident,seconds,'Audio transport gap; this interval may be incomplete.')
                self.sequences[channel]=sequence
                try:self.queue.put_nowait((channel,sequence,seconds,pcm))
                except queue.Full:
                    meetings.gap(db,self.ident,seconds,'Speech recognition fell behind; this audio interval was discarded.')
                    raise ValueError('Transcription is behind; audio was discarded, not saved')

    def run(self):
        try:
            while not self.closing or not self.queue.empty():
                try:channel,sequence,seconds,pcm=self.queue.get(timeout=.5)
                except queue.Empty:
                    if time.time()-self.last>90:
                        with closing(self.connect(self.path)) as db:meetings.gap(db,self.ident,0,'Capture connection stopped; unprocessed audio was not saved.')
                        self.closing=True
                    continue
                try:
                    import numpy as np
                    self.received.add(channel)
                    audio=np.frombuffer(pcm,dtype='<f4').copy(); pcm=None
                    if np.max(np.abs(audio))<.002:continue
                    segments,_=self.model.transcribe(audio,language=None if self.language=='auto' else self.language,
                        vad_filter=True,beam_size=3,condition_on_previous_text=False,word_timestamps=True)
                    with closing(self.connect(self.path)) as db:
                        for i,s in enumerate(segments):
                            if s.no_speech_prob>.8 or not s.text.strip():continue
                            self.speech_channels.add(channel)
                            for part_index,part in enumerate(meeting_identity.attributed_parts(db,self.ident,channel,seconds,s)):
                                attribution=part['identity'];speaker=attribution['speaker']
                                duplicate=db.execute('SELECT 1 FROM meeting_segment WHERE meeting=? AND ABS(seconds-?)<8 AND lower(text)=lower(?)',
                                    (self.ident,part['start'],part['text'].strip())).fetchone()
                                if not duplicate and part['text'].strip():
                                    sid=meetings.segment(db,self.ident,speaker,part['start'],part['text'],f'{channel}:{sequence}:{i}:{part_index}')
                                    meeting_identity.save_attribution(db,sid,self.ident,channel,part['end'],attribution)
                except Exception:
                    with closing(self.connect(self.path)) as db:meetings.gap(db,self.ident,seconds,'A speech segment could not be transcribed; its audio was discarded.')
                finally:
                    pcm=None;audio=None;self.queue.task_done()
            with closing(self.connect(self.path)) as db:
                expected={'microphone'} if self.microphone_speaker else {'microphone','system'}
                for channel in expected-self.received:
                    meetings.gap(db,self.ident,0,'No audio arrived from '+channel+'. This channel may be missing.')
                for channel in (expected & self.received)-self.speech_channels:
                    meetings.gap(db,self.ident,0,'No speech was recognized from '+channel+'. Check that the expected speakers were captured.')
                meetings.finish(db,self.ident)
            if self.config:
                analyze_async(self.path,self.connect,self.ident,self.config)
            else:
                with closing(self.connect(self.path)) as db:
                    with db:db.execute("UPDATE meeting_note SET error='Transcript ready. Choose a summary model in Meeting preferences to interpret it.' WHERE id=?",(self.ident,))
        finally:
            self.finished.set()
            with LOCK:SESSIONS.pop(str(self.path),None)


def start(path,connect,data,config=None):
    with LOCK:
        if str(path) in SESSIONS:raise ValueError('A meeting is already being captured')
        if MODEL_STATE=='loading':raise ValueError('Local speech recognition is still being prepared')
        model=load_cached()
        with closing(connect(path)) as db:
            if data.get('calendar_event') and not any(e['id']==data['calendar_event'] for e in meeting_identity.candidates(db)):raise ValueError('Calendar event is no longer available; select another event')
            ident=meetings.create(db,data.get('title','Meeting'),data.get('kind','general'))
            meeting_identity.bind(db,ident,data.get('calendar_event'),data.get('microphone_only',False))
            language=meetings.preferences(db)['language']
        SESSIONS[str(path)]=Session(path,connect,ident,language,model,config,'In-room participants' if data.get('microphone_only') else None)
    with closing(connect(path)) as db:zoom=meetings.preferences(db).get('zoom_speakers',False)
    return {'id':ident,'zoom_speakers':zoom and data.get('speaker_source')=='zoom' and not data.get('microphone_only',False)}


def audio(path,data):
    with LOCK:s=SESSIONS.get(str(path))
    if not s or data.get('id')!=s.ident:raise ValueError('No matching capture session')
    channel=data.get('channel');seconds=float(data['seconds']);sequence=int(data['sequence'])
    if channel not in ('microphone','system') or not math.isfinite(seconds) or seconds<0 or sequence<0:raise ValueError('Invalid audio metadata')
    pcm=base64.b64decode(data['pcm'],validate=True)
    if not 4<=len(pcm)<=16000*4*10 or len(pcm)%4:raise ValueError('Audio chunks must contain at most 10 seconds of Float32 samples')
    if any(not math.isfinite(value) or abs(value)>2 for (value,) in struct.iter_unpack('<f',pcm)):raise ValueError('Invalid audio samples')
    if 'capture_origin' in data:
        origin=float(data['capture_origin'])
        if not math.isfinite(origin) or not 0<=time.time()-origin<=86400:raise ValueError('Invalid capture clock')
        with s.lock:
            if s.audio_origin is None:
                s.audio_origin=origin;s.monotonic_origin=time.monotonic()-(time.time()-origin)
            elif abs(s.audio_origin-origin)>.01:raise ValueError('Capture clock changed')
    if data.get('speakers'):
        with closing(s.connect(s.path)) as db:meeting_identity.samples(db,s.ident,data['speakers'])
    s.push(channel,sequence,seconds,pcm)
    return {'ok':True}


def control(path,connect,data):
    with LOCK:s=SESSIONS.get(str(path))
    if not s or s.ident!=data['id']:raise ValueError('No matching capture session')
    command=data['command']
    with s.lock:
        with closing(connect(path)) as db:
            if command=='heartbeat':s.last=time.time()
            elif command=='stop':
                s.closing=True
                with db:db.execute("UPDATE meeting_note SET state='finishing' WHERE id=?",(s.ident,))
            elif command in ('pause','resume'):
                s.paused=command=='pause';s.last=time.time()
                with db:db.execute('UPDATE meeting_note SET state=? WHERE id=?',('paused' if s.paused else 'recording',s.ident))
            elif command=='gap':meetings.gap(db,s.ident,float(data.get('seconds',0)),str(data.get('reason','Capture interrupted')))
            else:raise ValueError('Unknown meeting control')
    return {'ok':True}


def active(path):
    with LOCK:s=SESSIONS.get(str(path))
    return {'id':s.ident,'paused':s.paused,'finishing':s.closing,'pending':s.queue.qsize()} if s else None


def analyze_async(path,connect,ident,config):
    if not config:raise ValueError('Choose a summary model and enable meeting text in Settings first')
    key=(str(path),ident)
    with LOCK:
        if key in JOBS:return {'ok':True}
        JOBS[key]=True
    def work():
        try:
            with closing(connect(path)) as db:
                note=meetings.analyze(db,ident,config)
                with db:db.execute("INSERT INTO notification(task,message,mood,reason,created) VALUES(NULL,?,'friendly','Meeting notes ready',?)",('Notes for '+note['title']+' are ready. Review actions from Paco’s Meeting notes menu.',time.time()))
        except Exception as exc:
            with closing(connect(path)) as db:
                with db:db.execute("UPDATE meeting_note SET error=? WHERE id=?",('Analysis needs attention: '+str(exc)[:250],ident))
        finally:
            with LOCK:JOBS.pop(key,None)
    threading.Thread(target=work,daemon=True).start()
    return {'ok':True}


def shutdown(path):
    with LOCK:s=SESSIONS.get(str(path))
    if s:s.closing=True;s.finished.wait(5)
