'use strict';
const $=s=>document.querySelector(s), E=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
let state=null,view='list',period=new Date(),limit=30,editing=null,draft=null,chatBusy=false,proposal=null;
document.body.classList.toggle('native-window',!!window.webkit?.messageHandlers?.paco);
const CLOSED=['done','archived','cancelled','incorrect'];
const dayKey=d=>`${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
const shortDate=t=>new Date(t*1000).toLocaleDateString([],{month:'short',day:'numeric'});
const timeDate=t=>new Date(t*1000).toLocaleString([],{dateStyle:'medium',timeStyle:'short'});
function button(text,fn,cls){const b=E('button',text,cls);b.type='button';b.onclick=()=>{const selection=window.getSelection();if(!selection.isCollapsed&&(b.contains(selection.anchorNode)||b.contains(selection.focusNode)))return;return Promise.resolve().then(fn).catch(e=>notice(e.message));};return b;}
function notice(text){$('#notice').textContent=text;$('#notice').hidden=false;clearTimeout(notice.timer);notice.timer=setTimeout(()=>$('#notice').hidden=true,8000);}
async function api(body){const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Paco':'1'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Could not save. Please try again.');return data;}
async function action(body){const result=await api(body);await refresh();if(['focus_start','focus_stop','focus_pause','focus_resume'].includes(body.action))window.webkit?.messageHandlers?.paco?.postMessage('focus-changed');return result;}
// Repository buckets help classification internally; only chosen projects belong in navigation.
function chosenProjects(){return state.projects.filter(p=>p.user_created);}
function taskProjectChoices(task){const choices=chosenProjects();const current=state.projects.find(p=>p.id===task?.project?.id);return current&&!choices.some(p=>p.id===current.id)?[...choices,{...current,name:current.name+' (current source)'}]:choices;}
function selectOptions(select,values,first){const selected=select.value;select.replaceChildren();for(const [value,label] of [['',first],...values]){const o=E('option',label);o.value=value;select.append(o);}select.value=[...select.options].some(o=>o.value===selected)?selected:'';}
function navigate(tab){window.scrollTo(0,0);if(!['tasks','meetings','sessions','controls'].includes(tab))tab='tasks';document.querySelectorAll('.page').forEach(n=>n.hidden=n.id!==tab+'-page');document.querySelectorAll('[data-tab]').forEach(n=>{if(n.dataset.tab===tab)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current');});const f=$('#'+tab+'-frame');if(f&&!f.getAttribute('src'))f.src=f.dataset.src;document.title='Paco · '+tab[0].toUpperCase()+tab.slice(1);if(tab==='tasks'&&location.hash==='#intake'){$('#chat-mode').value='plan';$('#message').focus();}}
document.querySelectorAll('[data-tab]').forEach(b=>b.onclick=()=>location.hash=b.dataset.tab);
window.addEventListener('hashchange',()=>navigate(location.hash.slice(1)));navigate(location.hash.slice(1));
window.addEventListener('message',e=>{if(e.origin!==location.origin)return;if(e.data?.paco==='navigate'&&['tasks','meetings','sessions','controls'].includes(e.data.tab))location.hash=e.data.tab;if(e.data?.paco==='meeting-start'||e.data?.paco==='meeting-stop')window.webkit?.messageHandlers?.paco?.postMessage(e.data.paco);});
async function refresh(){if(!window.getSelection().isCollapsed)return;const r=await fetch('/api/state');if(!r.ok)throw Error('Paco is reconnecting. Reopen the app if this continues.');state=await r.json();if(location.hash.startsWith('#reminder-'))await showReminder();if(!window.getSelection().isCollapsed)return;renderConnection();$('#task-count').textContent=state.tasks.filter(t=>!CLOSED.includes(t.state)&&t.my_responsibility).length+' active tasks';selectOptions($('#project-filter'),chosenProjects().map(p=>[String(p.id),p.name]),'All projects');selectOptions($('#area-filter'),[...new Set(chosenProjects().map(p=>p.area).filter(Boolean))].sort().map(x=>[x,x]),'All areas');selectOptions($('#tag-filter'),[...new Set(state.tasks.flatMap(t=>t.tags||[]))].sort().map(x=>[x,x]),'All tags');selectOptions($('#focus-task'),state.tasks.filter(t=>!CLOSED.includes(t.state)&&t.my_responsibility).map(t=>[String(t.id),t.title]),'No task');renderTasks();renderReview();renderTrackers();renderFocus();if(!chatBusy)renderConversation();}
function renderTrackers(){
 const trackers=(state.project_trackers||[]).filter(p=>p.user_created),box=$('#project-trackers');
 $('#project-watch-count').textContent='· '+trackers.length;
 const labels={empty:'No tasks yet',complete:'Completed',blocked:'Blocked',attention:'Needs attention',active:'In progress'};
 box.replaceChildren(...trackers.map(p=>{
  const card=button('',()=>{$('#project-filter').value=String(p.project);$('#status-filter').value='active';$('#search').value='';$('#area-filter').value='';$('#tag-filter').value='';limit=30;renderTasks();},'project-tracker');
  card.append(E('strong',p.name),E('span',labels[p.status]||p.status,'muted small'));
  card.append(E('span',`${p.my_active??p.active} for me · ${p.active} tracked · ${p.completed} done${p.suggested?' · '+p.suggested+' to review':''}`,'small'));
  if(p.brief?.objective)card.append(E('span',p.brief.objective,'tracker-next small'));
  if(p.brief?.my_roles?.length)card.append(E('span','My role: '+p.brief.my_roles.map(r=>r.mode).join(', '),'small'));
  const risks=[p.blocked?`${p.blocked} blocked`:'',p.overdue?`${p.overdue} overdue`:'',p.upcoming?`${p.upcoming} due within 3 days`:'',p.urgent?`${p.urgent} urgent`:''].filter(Boolean);
  if(risks.length)card.append(E('span',risks.join(' · '),'small'));
  if(p.next_task)card.append(E('span','Next: '+p.next_task.title,'tracker-next small'));
  if(p.blockers?.length)card.append(E('span','Waiting: '+p.blockers[0].title,'tracker-next small'));
  const latest=p.recent_changes?.at(-1);if(latest)card.append(E('span',`${{added:'Added',removed:'No longer tracked',completed:'Completed',updated:'Updated'}[latest.kind]}: ${latest.title}`,'tracker-next muted small'));
  card.title='Checked '+timeDate(p.checked)+' · Click to filter tasks';const wrap=E('div',undefined,'project-card');wrap.append(card,button('Edit project brain',()=>editBrain(p.project),'brain-edit small'));return wrap;
 }));
}
function renderConversation(){const box=$('#conversation'),atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<30;box.replaceChildren(...(state.conversation||[]).slice(-8).map(m=>E('p',m.text,'message '+m.role)));if(atBottom)box.scrollTop=box.scrollHeight;}
function filtered(){const search=$('#search').value.toLowerCase(),project=$('#project-filter').value,area=$('#area-filter').value,tag=$('#tag-filter').value,status=$('#status-filter').value;return state.tasks.filter(t=>t.in_scope!==false&&(status==='active'?(!CLOSED.includes(t.state)&&t.my_responsibility):status==='team'?(!CLOSED.includes(t.state)&&t.attention?.status==='accepted'&&!t.my_responsibility):['suggested','reference','dismissed','duplicate'].includes(status)?t.attention?.status===status:status==='all'?true:t.state===status)&&(!project||String(t.project?.id)===project)&&(!area||t.project?.area===area)&&(!tag||t.tags?.includes(tag))&&(!search||[t.title,t.description,t.assignee,...(t.tags||[])].join(' ').toLowerCase().includes(search))).sort((a,b)=>{switch($('#sort').value){case'priority':return Number(b.critical)-Number(a.critical)||b.priority-a.priority;case'project':return(a.project?.name||'~').localeCompare(b.project?.name||'~')||a.title.localeCompare(b.title);case'title':return a.title.localeCompare(b.title);default:return(a.deadline??Infinity)-(b.deadline??Infinity)||Number(b.critical)-Number(a.critical)||a.id-b.id;}});}
function taskRow(t){const row=E('div',undefined,'task-row'+(t.state==='done'?' is-done':''));const done=button(t.state==='done'?'✓':'',()=>action({action:t.state==='done'?'resume':'done',id:t.id}),'complete'+(t.state==='done'?' done':''));done.setAttribute('aria-label',(t.state==='done'?'Reopen ':'Complete ')+t.title);const main=E('div',undefined,'task-summary');main.setAttribute('role','button');main.tabIndex=0;main.onclick=()=>{if(window.getSelection().isCollapsed)editTask(t);};main.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();editTask(t);}};main.title=t.attention?.reason||'';main.append(E('span',t.title,'task-title'));const meta=E('span',undefined,'metadata');if(t.attention?.status&&t.attention.status!=='accepted')meta.append(E('span',t.attention.status,'chip'));if(t.project)meta.append(E('span',t.project.name,'chip project'));if(t.project?.area)meta.append(E('span',t.project.area));for(const tag of (t.tags||[]).slice(0,3))meta.append(E('span','#'+tag,'chip'));if(t.critical)meta.append(E('span','Urgent','overdue'));if(t.state==='blocked')meta.append(E('span','Blocked'));if(t.assignee)meta.append(E('span',t.assignee));if(meta.children.length)main.append(meta);row.append(done,main);if(t.deadline)row.append(E('span',shortDate(t.deadline),'deadline'+(t.deadline<Date.now()/1000&&!CLOSED.includes(t.state)?' overdue':'')));else if(t.snoozed_until){const reminder=E('span','Reminder '+shortDate(t.snoozed_until),'deadline');reminder.title=timeDate(t.snoozed_until);row.append(reminder);}return row;}
function empty(box,title,help){const n=E('div',undefined,'empty');n.append(E('strong',title),E('p',help));box.append(n);}
function renderTasks(){if(!state)return;const tasks=filtered(),box=$('#task-view');box.replaceChildren();box.className='task-list';$('#undated').replaceChildren();$('#view-help').textContent='';$('#show-more').hidden=true;$('#view-period').hidden=!['calendar','gantt'].includes(view);document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));if(view==='calendar')return calendar(tasks,box);if(view==='gantt')return gantt(tasks,box);if(!tasks.length){empty(box,'A clear space.','Add a task above, or change your filters.');return;}if(view==='board'){box.className='board';for(const [status,title] of [['open','To do'],['focus','In progress'],['blocked','Waiting'],['done','Done']]){const col=E('section',undefined,'board-column'),items=tasks.filter(t=>t.state===status);col.append(E('h2',title+' · '+items.length));items.slice(0,limit).forEach(t=>col.append(taskRow(t)));if(items.length>limit)col.append(E('p',`${items.length-limit} more — use List or narrow your filters`,'muted small'));box.append(col);}const other=tasks.filter(t=>!['open','focus','blocked','done'].includes(t.state));if(other.length){const col=E('section',undefined,'board-column');col.append(E('h2','Archived / other'));other.slice(0,limit).forEach(t=>col.append(taskRow(t)));box.append(col);}return;}box.className='task-list';tasks.slice(0,limit).forEach(t=>box.append(taskRow(t)));$('#show-more').hidden=tasks.length<=limit;}
function undated(tasks){const no=tasks.filter(t=>!t.deadline);if(!no.length)return;const d=E('details');d.append(E('summary',`Without a deadline · ${no.length}`));no.slice(0,30).forEach(t=>d.append(taskRow(t)));if(no.length>30)d.append(E('p','Use List to see all undated tasks.','muted small'));$('#undated').append(d);}
function calendarIcon(task=false){const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('aria-hidden','true');icon.innerHTML=task?'<rect x="4" y="4" width="16" height="16" rx="4"/><path d="m8 12 3 3 5-6"/>':'<rect x="4" y="5" width="16" height="16" rx="3"/><path d="M8 3v4m8-4v4M4 10h16"/>';return icon;}
function calendarEvent(event){
 const name=event.title||'Untitled',normalized=name.trim().toLowerCase();let hash=0;for(const char of normalized)hash=(hash*31+char.codePointAt(0))>>>0;
 const block=/^(x+|busy|blocked|focus|deep work|focus time)$/.test(normalized);
 const row=E('div',undefined,'calendar-event '+(block?'event-block':'event-tone-'+hash%4)),time=E('span',undefined,'calendar-card-time');
 time.append(calendarIcon(),E('span',new Date(event.start*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})));
 row.append(time,E('span',name,'calendar-card-title'));row.title=name+' · '+timeDate(event.start)+' – '+timeDate(event.end);return row;
}
function calendar(tasks,box){
 box.className='calendar';const first=new Date(period.getFullYear(),period.getMonth(),1),start=new Date(first);start.setDate(1-(first.getDay()+6)%7);
 $('#period-label').textContent=first.toLocaleDateString([],{month:'long',year:'numeric'});['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach(x=>box.append(E('div',x,'weekday')));
 for(let i=0;i<42;i++){
  const d=new Date(start);d.setDate(start.getDate()+i);const key=dayKey(d),cell=E('div',undefined,'day'+(d.getMonth()!==first.getMonth()?' outside':'')+(key===dayKey(new Date())?' today':''));cell.append(E('span',String(d.getDate()),'day-number'));const entries=[];
  for(const t of tasks.filter(t=>t.deadline&&dayKey(new Date(t.deadline*1000))===key)){
   const b=button('',()=>editTask(t),'calendar-task'),time=E('span',undefined,'calendar-card-time');time.append(calendarIcon(true),E('span',new Date(t.deadline*1000).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})));b.append(time,E('span',t.title,'calendar-card-title'));b.title=t.title+' · Due '+timeDate(t.deadline);b.setAttribute('aria-label',t.title+' · Due '+timeDate(t.deadline));entries.push({at:t.deadline,node:b});
  }
  for(const e of (state.calendar||[]).filter(e=>dayKey(new Date(e.start*1000))===key))entries.push({at:e.start,node:calendarEvent(e)});entries.sort((a,b)=>a.at-b.at).forEach(e=>cell.append(e.node));box.append(cell);
 }
 undated(tasks);$('#view-help').textContent='Task deadlines and calendar events. Select a task to edit it.';
}
function gantt(tasks,box){box.className='timeline';const start=new Date(period.getFullYear(),period.getMonth(),period.getDate());start.setDate(start.getDate()-(start.getDay()+6)%7);const end=new Date(start);end.setDate(end.getDate()+13);$('#period-label').textContent=shortDate(start.getTime()/1000)+' – '+shortDate(end.getTime()/1000);const head=E('div',undefined,'timeline-head');head.append(E('span','Task'));for(let i=0;i<14;i++){const d=new Date(start);d.setDate(d.getDate()+i);head.append(E('span',d.getDate()+' '+d.toLocaleDateString([],{weekday:'short'})));}box.append(head);const days=Array.from({length:14},(_,i)=>{const d=new Date(start);d.setDate(d.getDate()+i);return d.getTime()/1000;});const stop=new Date(end);stop.setDate(stop.getDate()+1);let count=0;for(const t of tasks){if(!t.deadline)continue;const begin=t.deadline-(t.minutes||30)*60;if(t.deadline<days[0]||begin>=stop.getTime()/1000)continue;count++;const from=Math.max(0,days.findLastIndex(d=>d<=begin)),to=Math.max(0,Math.min(13,days.findLastIndex(d=>d<=t.deadline)));const row=E('div',undefined,'timeline-row'),track=E('div',undefined,'timeline-track'),bar=button((t.minutes||30)+' min · '+shortDate(t.deadline),()=>editTask(t),'timeline-bar');bar.style.gridColumn=`${from+1} / ${to+2}`;bar.title=t.title+' · '+timeDate(t.deadline);track.append(bar);row.append(button(t.title,()=>editTask(t),'timeline-title'),track);box.append(row);}if(!count)empty(box,'No dated work in this fortnight.','Change the period, or add a deadline to a task.');undated(tasks);$('#view-help').textContent='Estimated work windows ending at each deadline, not committed start dates. Dependencies are shown in task details.';}
for(const id of ['search','project-filter','area-filter','tag-filter','status-filter','sort'])$('#'+id).addEventListener(id==='search'?'input':'change',()=>{limit=30;renderTasks();});
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{view=b.dataset.view;renderTasks();});$('#show-more').onclick=()=>{limit+=30;renderTasks();};for(const [id,dir] of [['period-prev',-1],['period-next',1]])$('#'+id).onclick=()=>{if(view==='calendar')period=new Date(period.getFullYear(),period.getMonth()+dir,1);else period.setDate(period.getDate()+14*dir);renderTasks();};$('#period-today').onclick=()=>{period=new Date();renderTasks();};
function editTask(t=null){editing=t;const f=$('#task-form');f.reset();$('#editor-error').textContent='';$('#editor-heading').textContent=t?'Task details':'New task';$('#archive-task').hidden=!t;selectOptions(f.elements.project,taskProjectChoices(t).map(p=>[String(p.id),p.name]),'No project');if(t){for(const k of ['title','description','assignee','priority'])f.elements[k].value=t[k]??'';f.elements.responsibility.value=t.attention?.kind||'execute';f.elements.project.value=t.project?.id||'';f.elements.tags.value=(t.tags||[]).join(', ');f.elements.urgent.checked=!!t.critical;f.elements.estimate_minutes.value=t.minutes||30;if(t.deadline){const d=new Date(t.deadline*1000);f.elements.deadline.value=new Date(d-d.getTimezoneOffset()*60000).toISOString().slice(0,16);}}$('#task-relations').textContent=t?[t.parent?'Part of: '+(state.tasks.find(x=>x.id===t.parent)?.title||t.parent):'',...(t.dependencies||[]).map(id=>'After: '+(state.tasks.find(x=>x.id===id)?.title||id))].filter(Boolean).join(' · '):'';$('#task-dialog').showModal();f.elements.title.focus();}
$('#quick-add').onclick=()=>editTask();$('#close-editor').onclick=()=>$('#task-dialog').close();$('#archive-task').onclick=async()=>{try{await action({action:'archive',id:editing.id});$('#task-dialog').close();}catch(e){$('#editor-error').textContent=e.message;}};
$('#task-form').onsubmit=async e=>{e.preventDefault();const f=e.target,b=$('#save-task');b.disabled=true;try{const changes={title:f.elements.title.value,description:f.elements.description.value,assignee:f.elements.assignee.value,responsibility:f.elements.responsibility.value,tags:f.elements.tags.value.split(',').map(x=>x.trim()).filter(Boolean),project:f.elements.project.value?Number(f.elements.project.value):null,priority:Number(f.elements.priority.value),urgent:f.elements.urgent.checked,deadline:f.elements.deadline.value?new Date(f.elements.deadline.value).getTime()/1000:null,estimate_minutes:Number(f.elements.estimate_minutes.value)};await action({action:'task_edit',id:editing?.id??null,changes});$('#task-dialog').close();}catch(e){$('#editor-error').textContent=e.message;}finally{b.disabled=false;}};
function renderConnection(error=''){
 const c=state?.company,ok=!!(c?.account&&c.last_sync&&Date.now()/1000-c.last_sync<120&&!c.error&&!state.brain_sync_error&&!c.pending&&!c.conflicts?.length&&!error);
 const label=ok?'Synced':error||c?.error||state?.brain_sync_error||(c?.conflicts?.length?'Sync conflict':c?.pending?'Changes waiting to sync':c?.account?'Waiting for sync':'Company account not connected');
 $('#connection').classList.toggle('is-synced',ok);$('#connection').setAttribute('aria-label',label);$('#connection').title=label;
 $('#sync-mark').setAttribute('d',ok?'m8.5 17 2.5 2.5 4.5-5':'m9 15 6 6m0-6-6 6');
}
const perches=[[66,24],[77,24],[88,24],[20,39],[30,39],[40,39],[65,52],[77,52],[88,52],[20,63],[30,63],[40,63],[65,73],[77,73],[87,73]];
let forestCount=-1;
function renderGarden(){
 const stats=state.focus_stats||{completed:0,minutes:0};$('#focus-completed').textContent=stats.completed;$('#focus-total-minutes').textContent=stats.minutes;
 if(forestCount===stats.completed)return;forestCount=stats.completed;const forest=$('#focus-forest');forest.replaceChildren();
 for(let page=0;page<Math.max(1,Math.ceil(stats.completed/perches.length));page++){
  const tree=E('div',undefined,'focus-tree'),base=E('img');base.src='/assets/focus-tree-v1.png';base.alt='';base.draggable=false;tree.append(base);
  const count=Math.min(perches.length,stats.completed-page*perches.length);tree.setAttribute('role','img');tree.setAttribute('aria-label',`${Math.max(0,count)} parrots for completed focus sessions`);
  for(let i=0;i<count;i++){const bird=E('img',undefined,'focus-parrot');bird.src='/assets/focus-parrot-v1.png';bird.alt='';bird.draggable=false;bird.style.left=perches[i][0]+'%';bird.style.top=perches[i][1]+'%';if(i%2)bird.classList.add('flipped');tree.append(bird);}forest.append(tree);
 }
 $('#garden-caption').textContent=stats.completed===0?'Finish your first focus session to welcome a parrot.':stats.completed>perches.length?'One parrot per completed session. Scroll to see your growing grove.':'One completed session, one new parrot.';
}
function renderFocus(){
 const current=state.focus_session;$('#active-focus').hidden=!current;$('#focus-form').hidden=!!current;
 if(current){$('#focus-intention').textContent=current.intention;tickFocus();}
 renderGarden();$('#focus-history').replaceChildren(...state.focus_history.filter(s=>s.id!==current?.id).slice(0,8).map(s=>{
  const row=E('div',undefined,'history-row');row.append(E('span',s.intention),E('span',`${s.successful?'Completed':'Ended early'} · ${Math.round(s.focused_seconds/60)} min · ${shortDate(s.started)}`,'muted small'));return row;
 }));if(!$('#focus-history').children.length)$('#focus-history').append(E('p','No sessions yet.','muted small'));
}
function tickFocus(){
 const s=state?.focus_session;if(!s)return;const now=Date.now()/1000,isBreak=s.phase==='break',paused=s.phase==='paused';
 const sec=Math.max(0,Math.ceil(isBreak?s.break_until-now:paused?s.remaining:s.ends-now));
 $('#focus-phase').textContent=isBreak?(s.successful?'Session complete · break time':'Taking a break'):paused?'Paused · ready when you are':'Focusing';
 $('#focus-timer').textContent=Math.floor(sec/60)+':'+String(sec%60).padStart(2,'0');
 $('#focus-guidance').textContent=s.successful?'Your parrot is on the tree. Start another session when you’re ready.':isBreak||paused?'Your focus time is saved. Resume when you’re ready; reminders stay quiet.':'Reminders and call-outs are quiet, including urgent ones.';
 $('#focus-pause').hidden=isBreak||paused;$('#pause-duration-label').hidden=isBreak||paused;$('#focus-resume').hidden=!(isBreak||paused)||s.successful;$('#focus-stop').textContent=s.successful?'Finish break':'End session';
 if(!sec&&!paused&&!tickFocus.refreshing){tickFocus.refreshing=true;refresh().catch(()=>{}).finally(()=>tickFocus.refreshing=false);}
}
$('#focus-pomodoro').onchange=()=>$('#pomodoro-length').hidden=!$('#focus-pomodoro').checked;
$('#focus-task').onchange=()=>{const task=state.tasks.find(t=>String(t.id)===$('#focus-task').value);if(task)$('#focus-intention-input').value=task.title;};
$('#focus-form').onsubmit=async e=>{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{await action({action:'focus_start',intention:$('#focus-intention-input').value,task:$('#focus-task').value?Number($('#focus-task').value):null,minutes:Number($('#focus-minutes').value),break_minutes:$('#focus-pomodoro').checked?Number($('#focus-break-minutes').value):0});}catch(e){notice(e.message);}finally{b.disabled=false;}};
$('#focus-stop').onclick=()=>action({action:'focus_stop',id:state.focus_session.id}).catch(e=>notice(e.message));
$('#focus-pause').onclick=()=>action({action:'focus_pause',id:state.focus_session.id,minutes:Number($('#pause-minutes').value)}).catch(e=>notice(e.message));
$('#focus-resume').onclick=()=>action({action:'focus_resume',id:state.focus_session.id}).catch(e=>notice(e.message));setInterval(tickFocus,1000);
$('#chat-form').onsubmit=async e=>{e.preventDefault();if(chatBusy)return;const text=$('#message').value.trim();if(!text)return;chatBusy=true;$('#chat-send').disabled=true;$('#chat-status').textContent=$('#chat-mode').value==='plan'?'Drafting tasks…':'Paco is thinking…';try{if($('#chat-mode').value==='plan'){draft=await api({action:'intake_preview',text});renderDraft();$('#chat-status').textContent='Review before adding.';}else{const result=await api({action:'chat',text});proposal=result.proposal;$('#proposal').replaceChildren();if(proposal)$('#proposal').append(E('p',describeProposal(proposal.action),'small muted'),button('Apply suggestion',async()=>{await action({action:'accept_suggestion',id:proposal.id});proposal=null;$('#proposal').replaceChildren();},'primary'));$('#message').value='';$('#chat-status').textContent='';await refresh();renderConversation();}}catch(err){$('#chat-status').textContent=err.message;}finally{chatBusy=false;$('#chat-send').disabled=false;}};
function renderDraft(){const box=$('#proposal');box.replaceChildren();if(!draft)return;for(const q of draft.plan.questions)box.append(E('p',q,'small muted'));for(const t of draft.plan.tasks){const row=E('div',undefined,'draft-task'),title=E('input');title.value=t.title;title.setAttribute('aria-label','Proposed task title');title.oninput=()=>t.title=title.value;const details=E('details');details.append(E('summary','Details'));const p=draft.plan.projects.find(p=>p.ref===t.project)||state.projects.find(p=>String(p.id)===t.project);details.append(E('p',[p?.name,t.assignee,t.deadline?timeDate(t.deadline):'No deadline',...(t.tags||[])].filter(Boolean).join(' · '),'small muted'),E('p',t.description,'small muted'));row.append(title,button('Remove',()=>{draft.plan.tasks=draft.plan.tasks.filter(x=>x.ref!==t.ref);for(const x of draft.plan.tasks){x.depends_on=x.depends_on.filter(r=>r!==t.ref);if(x.parent===t.ref)x.parent=null;}renderDraft();}));box.append(row,details);}const actions=E('div',undefined,'draft-actions');const apply=button('Add '+draft.plan.tasks.length+' tasks',async()=>{apply.disabled=true;try{const r=await action({action:'intake_apply',id:draft.id,plan:draft.plan});draft=null;box.replaceChildren();$('#message').value='';$('#chat-status').textContent='Added '+r.count+' tasks.';}finally{apply.disabled=false;}},'primary');apply.disabled=!draft.plan.tasks.length;actions.append(apply,button('Discard',()=>{draft=null;box.replaceChildren();$('#chat-status').textContent='';}));box.append(actions);}
let openReminder=null;
async function showReminder(){
 const match=/^#reminder-(\d+)$/.exec(location.hash);
 const dialog=$('#reminder-dialog');
 if(!match){if(dialog.open)dialog.close();openReminder=null;return;}
 const id=Number(match[1]);
 if(openReminder?.id!==id){
   const data=await api({action:'reminder_members',id});
   if(location.hash!==match[0])return;
   openReminder={id,...data};
 }
 const tasks=(state?.tasks||[]).filter(t=>openReminder.tasks.includes(t.id)&&t.my_responsibility);
 $('#reminder-label').textContent=openReminder.label;
 $('#reminder-items').replaceChildren(...tasks.map(taskRow));
 if(!dialog.open)dialog.showModal();
}
$('#close-reminder').onclick=()=>$('#reminder-dialog').close();
$('#reminder-dialog').onclose=()=>{if(location.hash.startsWith('#reminder-'))location.hash='tasks';};
$('#split-reminder').onclick=async()=>{
 try{await api({action:'separate_reminders',id:openReminder.id});$('#reminder-dialog').close();notice('Separate reminders saved.');}catch(e){notice(e.message);}
};
window.addEventListener('hashchange',()=>showReminder().catch(e=>notice(e.message)));
refresh().catch(e=>notice(e.message));setInterval(()=>refresh().catch(()=>{renderConnection('Reconnecting…');}),15000);

function describeProposal(a){if(a.action==='add')return 'Add task: '+a.title+(a.deadline?' · Due '+a.deadline:'');if(a.action==='estimate')return 'Update the time estimate and deadline for '+(state.tasks.find(t=>t.id===a.id)?.title||'this task');if(a.action==='preference')return 'Change availability to '+a.value;if(a.action==='automation_propose')return 'Create a routine: '+a.title;return 'Review Paco’s proposed change';}

function renderReview(){
 const items=state.tasks.filter(t=>t.in_scope!==false&&t.attention?.status==='suggested'&&!CLOSED.includes(t.state));
 $('#review-count').textContent='· '+items.length;$('#review-items').replaceChildren();
 for(const t of items.slice(0,8)){
  const row=E('div',undefined,'review-row'),text=button(t.title,()=>editTask(t),'task-summary');
  const actions=E('div',undefined,'review-actions');actions.append(button('Mine',()=>action({action:'attention_decide',id:t.id,choice:'accept'})),button('Dismiss',()=>action({action:'attention_decide',id:t.id,choice:'dismiss'})));
  row.append(text,E('span',t.project?.name||'Uncategorized','muted small'),actions);$('#review-items').append(row);
 }
 if(items.length>8)$('#review-items').append(button(`See all ${items.length} suggestions`,()=>{$('#status-filter').value='suggested';renderTasks();}));
 if(!items.length)$('#review-items').append(E('p','Nothing to review.','muted small'));
 $('#brain-sync-status').textContent=state.brain_sync_error||'';
}
let brainEditing=null,brainAttempt=null;
function roleRow(role={}){
 const row=E('div',undefined,'brain-role');row.dataset.id=role.id||crypto.randomUUID();
 for(const [field,label,placeholder] of [['person','Person','Username or email'],['aliases','Other identities','Emails or usernames, comma separated'],['responsibilities','Responsibilities','What this person owns']]){
  const l=E('label',label),input=E('input');input.dataset.field=field;input.placeholder=placeholder;input.maxLength=field==='responsibilities'?2000:field==='aliases'?1800:120;input.value=field==='aliases'?(role.aliases||[]).join(', '):role[field]||'';if(field==='person')input.required=true;l.append(input);row.append(l);
 }
 const label=E('label','Role'),select=E('select');select.dataset.field='mode';for(const [value,title] of [['execute','Execute'],['manage','Manage'],['review','Review'],['decide','Decide'],['informed','Stay informed']]){const o=E('option',title);o.value=value;select.append(o);}select.value=role.mode||'execute';label.append(select);row.append(label,button('Remove',()=>row.remove(),'small'));$('#brain-roles').append(row);
}
function editBrain(project=null){
 brainEditing=(state.project_briefs||[]).find(b=>b.project===project)||{project:project,id:null,revision:0,data:state.projects.find(p=>p.id===project)||{}};brainAttempt=null;
 const f=$('#brain-form');f.reset();for(const field of ['name','area','hints','objective','milestone','done_when','out_of_scope','stakeholders','decisions'])f.elements[field].value=brainEditing.data[field]||'';
 f.elements.sources.value=(brainEditing.data.sources||[]).join('\n');$('#brain-roles').replaceChildren();(brainEditing.data.roles||[]).forEach(roleRow);
 $('#brain-error').textContent='';$('#brain-revision').textContent=brainEditing.id?'Shared revision '+brainEditing.revision:'Save to share this project brief with your company.';
 if(!$('#brain-dialog').open)$('#brain-dialog').showModal();
}
$('#new-project-brain').onclick=()=>editBrain();$('#add-brain-role').onclick=()=>roleRow();$('#close-brain').onclick=()=>$('#brain-dialog').close();
$('#reload-brain').onclick=async()=>{try{await action({action:'project_brain_refresh'});editBrain(brainEditing.project);}catch(e){$('#brain-error').textContent=e.message;}};
$('#brain-form').onsubmit=async e=>{
 e.preventDefault();const f=e.target,b=$('#save-brain');b.disabled=true;
 try{
  const data={};for(const field of ['name','area','hints','objective','milestone','done_when','out_of_scope','stakeholders','decisions'])data[field]=f.elements[field].value;
  data.sources=f.elements.sources.value.split('\n').map(x=>x.trim()).filter(Boolean);
  data.roles=[...$('#brain-roles').children].map(row=>{const r={id:row.dataset.id};row.querySelectorAll('[data-field]').forEach(n=>r[n.dataset.field]=n.dataset.field==='aliases'?n.value.split(',').map(x=>x.trim()).filter(Boolean):n.value);return r;});
  const serialized=JSON.stringify(data);if(!brainAttempt||brainAttempt.data!==serialized)brainAttempt={data:serialized,id:crypto.randomUUID()};
  await action({action:'project_brain_save',project:brainEditing.project,revision:brainEditing.revision,data,request_id:brainAttempt.id});$('#brain-dialog').close();notice('Shared project brain saved.');
 }catch(e){$('#brain-error').textContent=e.message;}finally{b.disabled=false;}
};
