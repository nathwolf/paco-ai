"""Opt-in Accessibility capture, with exclusions checked before requesting text."""
import json
from pathlib import Path
import subprocess
import workflows

BANNED = ('terminal','iterm','claude','chatgpt','codex','safari','chrome','firefox','edge','password','keychain','1password')


def sample(db):
    executable=Path(__file__).parent/'build/Paco.app/Contents/MacOS/Paco'
    def read(mode,*args):
        return json.loads(subprocess.check_output([str(executable),'--capture',mode,*args],text=True,stderr=subprocess.DEVNULL,timeout=5))
    meta=read('metadata')
    app,title,bundle=meta.get('app',''),meta.get('title',''),meta.get('bundle','')
    if not title or not bundle or any(word in (app+' '+bundle).lower() for word in BANNED):
        return {'stored':False,'reason':'Excluded or unknown context'}
    rule=db.execute('SELECT enabled FROM capture_rule WHERE app=?',(app,)).fetchone()
    if not rule or not rule[0]:
        return {'stored':False,'reason':'This app has not been enabled'}
    if any(value.lower() in (app if kind=='app' else title).lower() for kind,value in db.execute('SELECT kind,value FROM exclusion')):
        return {'stored':False,'reason':'Excluded window'}
    data=read('text',bundle)
    if data.get('app')!=app or data.get('title')!=title:
        return {'stored':False,'reason':'Foreground context changed'}
    text=data.get('text','')
    if not text:
        return {'stored':False,'reason':'No readable text'}
    ident=workflows.capture(db,app,title,text)
    return {'stored':bool(ident),'id':ident}
