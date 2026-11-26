"""Reproducible offline week; reports policy outcomes separately from model quality."""
from datetime import datetime
from pathlib import Path
import json
import tempfile
import time
import discovery
import paco
import planning


def evaluate():
    start=time.monotonic()
    delivered=[]
    with tempfile.TemporaryDirectory() as tmp:
        db=paco.connect(Path(tmp)/'week.db')
        monday=datetime(2026,11,23,9).timestamp()
        with db:
            db.executemany('INSERT INTO preference VALUES(?,?)',[('hours','9-18'),('workdays','0,1,2,3,4'),('notification_gap','300')])
            db.execute("INSERT INTO absence VALUES('trip',?,?,'Holiday','manual')",(monday+2*86400,monday+4*86400))
            db.execute("INSERT INTO task VALUES(1,'Ordinary obligation',3,'open',?,0)",(monday,))
            db.execute("INSERT INTO task VALUES(2,'Critical obligation',5,'open',?,0)",(monday,))
            db.execute('INSERT INTO urgency VALUES(2,1)')
            db.execute('INSERT INTO details VALUES(1,NULL,25,?)',(monday+86400,))
            db.execute('INSERT INTO details VALUES(2,NULL,25,?)',(monday+86400,))
            for day in range(7):db.execute('INSERT INTO busy VALUES(?,?)',(monday+day*86400+3600,monday+day*86400+7200))
        for step in range(7*24*4):
            now=monday+step*900
            def deliver(message):
                task=planning.next_reminder(db,now)
                delivered.append({'task':task['id'],'at':now,'holiday':monday+2*86400<=now<monday+4*86400,
                                  'working_hours':9<=datetime.fromtimestamp(now).hour<18,
                                  'meeting':datetime.fromtimestamp(now).hour==10})
            paco.tick(db,now,deliver)
        discovery.reconcile(db,'github',[('issue','Reassigned task',monday)],monday)
        discovery.reconcile(db,'github',[],monday+100)
        false_closures=db.execute("SELECT count(*) FROM task WHERE title='Reassigned task' AND state='done'").fetchone()[0]
        db.close()
    return {'mode':'offline deterministic replay','days':7,'delivered':len(delivered),
            'nonurgent_holiday_interruptions':sum(x['holiday'] and x['task']==1 for x in delivered),
            'nonurgent_out_of_hours_interruptions':sum(not x['working_hours'] and x['task']==1 for x in delivered),
            'meeting_interruptions':sum(x['meeting'] for x in delivered),
            'false_closures_on_reassignment':false_closures,
            'model_quality':'not measured — needs a configured model',
            'provider_cost':'not measured — no paid calls made',
            'elapsed_seconds':round(time.monotonic()-start,3)}

if __name__=='__main__':
    result=evaluate();print(json.dumps(result,indent=2))
    raise SystemExit(any(result[k] for k in ('nonurgent_holiday_interruptions','nonurgent_out_of_hours_interruptions','meeting_interruptions','false_closures_on_reassignment')))
