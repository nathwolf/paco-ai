"""Opt-in live evaluation using Paco's configured summary model and synthetic text.

Run .venv/bin/python eval_meetings.py. Does not record audio or touch real tasks.
A passing score is a small regression check, not a guarantee of interpretation quality.
"""
from pathlib import Path
import json
import tempfile
import app
import meetings
import paco

CASES=[
 ('indirect acceptance',[('Ana','Can someone send the revised proposal?'),('Juan','Leave it with me.'),('Ana','Great, thanks.')], 'Juan','confirmed','proposal'),
 ('ability is not commitment',[('Ana','Who can update the proposal?'),('Juan','I could, but I have no time this week. Let us decide later.')],None,None,'proposal'),
 ('conditional offer accepted',[('Ana','The client is waiting for the proposal.'),('Juan','I can send it once finance approves.'),('Ana','Please do.')],'Juan','conditional','proposal'),
 ('later handoff',[('Juan','I will send the proposal.'),('Juan','Actually I cannot. Ana, can you take over?'),('Ana','Yes, leave it with me.')],'Ana','confirmed','proposal'),
 ('usual responsibility is not agreement',[('Ana','Juan normally handles the proposal, but he has not agreed to this one.')],None,None,'proposal'),
 ('unknown speaker',[('Remote participants','Could somebody update the proposal?'),('Remote participants','Sure, I will.')],None,None,'proposal'),
 ('completed work',[('Ana','What about the proposal?'),('Juan','Already sent it yesterday. Nothing left to do.')],None,None,'proposal'),
 ('not every idea is work',[('Ana','We could redesign the dashboard someday. This is not agreed work.')],None,None,'dashboard'),
 ('negation',[('Ana','Do not send the proposal until we decide whether to proceed.'),('Juan','Understood; I will wait.')],None,None,'proposal'),
]

def main():
    config=app.settings().get('meeting_model') or app.settings().get('model')
    if not config:raise SystemExit('Configure a summary model in Paco first. No live-model evaluation has been run.')
    failed=[]
    with tempfile.TemporaryDirectory(prefix='paco-meeting-eval-') as temp:
        db=paco.connect(Path(temp)/'eval.sqlite3')
        try:
            for title,turns,owner,commitment,term in CASES:
                ident=meetings.import_transcript(db,{'title':title,'segments':[{'speaker':s,'seconds':i*10,'text':t} for i,(s,t) in enumerate(turns)]})
                try:
                    result=meetings.analyze(db,ident,config)
                    actions=[i for i in result['items'] if i['kind']=='action' and term in i['title'].lower() and i['commitment'] in ('confirmed','conditional')]
                    ok=any(i['owner']==owner and i['commitment']==commitment for i in actions) if owner else not any(i['owner'] for i in actions)
                    if owner:ok=ok and not any(i['owner'] and i['owner']!=owner for i in actions)
                    print(('PASS' if ok else 'FAIL')+' '+title,flush=True)
                    if not ok:failed.append({'case':title,'actions':actions})
                except Exception as exc:
                    failed.append({'case':title,'error':str(exc)});print('ERROR '+title+': '+str(exc),flush=True)
        finally:db.close()
    print(json.dumps({'passed':len(CASES)-len(failed),'total':len(CASES),'failures':failed},indent=2))
    return bool(failed)

if __name__=='__main__':raise SystemExit(main())
