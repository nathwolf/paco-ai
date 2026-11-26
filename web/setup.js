'use strict';
const $=s=>document.querySelector(s);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
const NAMES={gitlab:'GitLab',linear:'Linear',microsoft_todo:'Microsoft To Do',outlook_calendar:'Outlook Calendar',github:'GitHub issues',github_reviews:'GitHub reviews',gmail:'Gmail',mattermost:'Mattermost',calendar:'Google Calendar',tasks:'Google Tasks',drive:'Google Drive',linear:'Linear',slack:'Slack',outlook:'Outlook',jira:'Jira',asana:'Asana',todoist:'Todoist',apple_calendar:'Apple Calendar',apple_reminders:'Apple Reminders'};
const PROVIDERS={anthropic:'Claude API',bedrock:'AWS Bedrock',openai:'OpenAI API',claude_code:'Claude Code',codex_cli:'Codex CLI',ollama:'Ollama',private:'Your server'};
// Which fields each provider needs, what the model field means, and where data goes.
const MODEL_FIELDS={
 ollama:{model:'Ollama model, e.g. qwen3:8b',hint:'Runs on this Mac. Nothing leaves it, so no permissions are needed below.'},
 private:{model:'Model name your server expects',endpoint:true,key:'API key, if your server needs one',hint:'An address on localhost stays on this Mac. A remote server receives only what you allow below.'},
 claude_code:{model:'Optional: model alias such as sonnet',hint:'Uses your signed-in Claude Code subscription, with tools turned off and no project files. Runs through Anthropic, so it receives only what you allow below.'},
 codex_cli:{model:'Optional: model name',hint:'Uses your signed-in Codex subscription in a read-only sandbox with no project files. Runs through OpenAI, so it receives only what you allow below.'},
 anthropic:{model:'Model ID, e.g. claude-sonnet-5-5',key:'API key · saved in Keychain',hint:'Receives only what you allow below.'},
 bedrock:{model:'Bedrock model ID, e.g. us.anthropic.claude-sonnet-5-5-v1:0',region:true,key:'Bedrock API key · saved in Keychain',hint:'Uses a Bedrock API key (bearer token) in your chosen region. Receives only what you allow below.'},
 openai:{model:'Model ID',key:'API key · saved in Keychain',hint:'Receives only what you allow below.'}};
function modelFields(){const f=$('#model-form'),spec=MODEL_FIELDS[f.elements.provider.value]||{};f.elements.model.placeholder=spec.model||'Model ID';
 f.elements.endpoint.hidden=!spec.endpoint;f.elements.region.hidden=!spec.region;f.elements.key.hidden=!spec.key;if(spec.key)f.elements.key.placeholder=spec.key;$('#model-hint').textContent=spec.hint||'';}
// Rows with their own Connect button; their sync state is shown on the row itself.
const ROWS={github:['github','github_reviews'],apple_calendar:['apple_calendar'],apple_reminders:['apple_reminders']};
let initialized=false;
function notice(text){$('#notice').hidden=false;$('#notice').textContent=text;}
function saved(text){$('#saved').textContent=text;clearTimeout(saved.timer);saved.timer=setTimeout(()=>{$('#saved').textContent='';},4000);}
function ago(t){const s=Math.max(0,Date.now()/1000-t);return s<90?'just now':s<5400?Math.round(s/60)+' min ago':s<129600?Math.round(s/3600)+' h ago':Math.round(s/86400)+' days ago';}
function describe(x){
  if(x.error)return {text:x.error.replace(/^(\w+Error|\w+Exception) — reconnect or retry$/,'Couldn’t sync ($1). Check the account, then reconnect.'),problem:true};
  return {text:x.last_success?'Synced '+ago(x.last_success):'Waiting for first sync',problem:false};
}
async function act(data){const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Paco':'1'},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error||'Could not save');return result;}
function form(id,fn){$(id).onsubmit=async e=>{e.preventDefault();const button=e.target.querySelector('button:not([type=button])');button.disabled=true;try{await fn(e.target);saved('Saved');await refresh();}catch(e){notice(e.message);}finally{button.disabled=false;}};}
async function refresh(){const [r,c]=await Promise.all([fetch('/api/state'),fetch('/api/companion')]);if(!r.ok||!c.ok)throw Error('Paco is unavailable. Reopen the launcher.');const s=await r.json(),companion=await c.json();renderCompany(s);
 $('#flow-status').textContent=s.flow.message;$('#judge-state').textContent=s.callout.judge_state;$('#judge-state').classList.toggle('problem',s.callout.judge&&!s.callout.judge_ready);
 $('#model-status').textContent=s.model?'Connected: '+(PROVIDERS[s.model.provider]||s.model.provider)+(s.model.model?' · '+s.model.model:''):'Not connected yet';
 const connected=new Set(s.sources);const status=Object.fromEntries(s.sync.map(x=>[x.source,x]));const shown=new Set();
 for(const [row,keys] of Object.entries(ROWS)){
  const button=document.querySelector(`[data-source="${row}"]`),state=document.querySelector(`[data-state="${row}"]`);
  const isOn=row==='github'?connected.has('github'):connected.has(row);
  button.textContent=isOn?'Reconnect':'Connect';button.classList.toggle('quiet',isOn);
  const parts=keys.filter(k=>status[k]).map(k=>{shown.add(k);const d=describe(status[k]);return {...d,text:(keys.length>1?NAMES[k]+': ':'')+d.text};});
  state.textContent=isOn?(parts.length?parts.map(p=>p.text).join(' · '):'Connected · waiting for first sync'):'';
  state.classList.toggle('problem',parts.some(p=>p.problem));
 }
 const accounts=Object.entries(s.connector_accounts||{});
 $('#accounts').replaceChildren(...accounts.map(([provider,account])=>{const row=node('div',undefined,'source');const label=node('span',NAMES[provider]||provider);label.append(node('small','Account '+(account.username||account.account)));
  const st=status[provider];shown.add(provider);if(st){const d=describe(st);label.append(node('small',d.text,'state'+(d.problem?' problem':'')));}
  if(provider==='mattermost'&&account.bot?.enabled){const chat=node('a','Message Paco ↗');chat.href=account.bot.url;chat.target='_blank';chat.rel='noopener';label.append(chat,node('small','Replies while this Mac is awake and unlocked. Checks about every 15 seconds.'));const pending=s.mattermost_proposals||[];if(pending.length)label.append(node('small',pending.length+' suggested task updates to review. Ask Paco “show pending changes” in your DM.'));}
  const off=node('button','Disconnect');off.className='quiet';off.onclick=async()=>{if(!confirm('Disconnect '+(NAMES[provider]||provider)+'? Its token is removed from Keychain.'))return;off.disabled=true;try{await act({action:'connector_revoke',provider});saved('Disconnected');await refresh();}catch(e){notice(e.message);off.disabled=false;}};
  row.append(label,off);return row;}));
 // Everything else (Google sources, background loops) as a compact list.
 $('#source-status').replaceChildren(...s.sync.filter(x=>!shown.has(x.source)).map(x=>{const d=describe(x);return node('p',(NAMES[x.source]||x.source)+': '+d.text,d.problem?'problem':'');}));
 renderProjects(s);
 $('#agent-status').textContent=s.agents.filter(a=>a.enabled).map(a=>(a.provider==='claude'?'Claude Code':'Codex')+' · '+a.workspace).join('\n');
 const sourceCount=s.sources.filter(x=>!['model','meeting_model','calendar_write','calendars'].includes(x)).length;
 $('#readiness').textContent=!(sourceCount||s.company?.account)?'No sources connected yet. Paco needs a source to discover work automatically.':!s.model?'Sources are connected. Add a model for reasoning and conversation.':'';
 if(!initialized){initialized=true;const am=s.activity_model||{},af=$('#activity-model-form');af.elements.provider.value=am.provider||'default';af.elements.model.value=am.model||'';af.elements.endpoint.value=am.endpoint||'';af.elements.allow_activity.checked=(am.allowed_sources||[]).includes('activity');af.elements.allow_tasks.checked=(am.allowed_sources||[]).includes('chat');af.elements.remote_processing.checked=!!am.remote_processing;af.elements.json_mode.checked=am.json_mode!==false;activityFields();const flowForm=$('#flow-form');flowForm.elements.enabled.checked=s.flow.enabled;flowForm.elements.apps.value=s.flow.apps;flowForm.elements.pause_seconds.value=s.flow.pause_seconds;flowForm.elements.urgent_interrupts.checked=s.flow.urgent_interrupts;$('#autostart').checked=companion.autostart||!companion.setup_complete;const co=$('#callout-form');co.elements.enabled.checked=s.callout.enabled;co.elements.sound.checked=s.callout.sound;co.elements.judge.checked=s.callout.judge;co.elements.always.value=s.callout.always;co.elements.never.value=s.callout.never;co.elements.behind.value=String(s.callout.behind);$('#mode').value=s.mode;
  const hours=(s.preferences.hours||'9-18').split('-');$('#rhythm-form').elements.start.value=hours[0];$('#rhythm-form').elements.end.value=hours[1];
  const days=(s.preferences.workdays||'0,1,2,3,4').split(',');['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].forEach((name,i)=>{const label=node('label',name);const input=node('input');input.type='checkbox';input.value=String(i);input.checked=days.includes(String(i));label.append(input);$('#days').append(label);});
  if(s.model){const f=$('#model-form');f.elements.provider.value=s.model.provider;f.elements.model.value=s.model.model||'';f.elements.endpoint.value=s.model.endpoint||'';f.elements.region.value=s.model.region||'';modelFields();for(const category of ['chat','gmail','mattermost','meeting','activity'])f.elements[category].checked=(s.model.allowed_sources||[]).includes(category);}
  for(const [mood,expression] of Object.entries(companion.expressions)){const b=node('button');b.type='button';b.title='Show a '+expression.label.toLowerCase()+' notification';const img=node('img');img.src='/assets/'+expression.file;img.alt='';b.append(img,node('span',expression.label),node('small',expression.when||''));b.onclick=()=>act({action:'demo',mood}).then(()=>saved('Preview sent — top right of your screen')).catch(e=>notice(e.message));$('#expressions').append(b);}
 }
}
function renderProjects(s){
 const list=$('#project-list');
 list.replaceChildren(...s.projects.map(p=>{const row=node('div',undefined,'source');const label=node('span',p.name);
  label.append(node('small',[p.area,p.hints&&('hints: '+p.hints)].filter(Boolean).join(' · ')||'No hints yet: Paco’s model sorts tasks'));
  const actions=node('div',undefined,'row');const edit=node('button','Edit','quiet');edit.type='button';
  edit.onclick=()=>{const f=$('#project-form');f.elements.id.value=p.id;f.elements.name.value=p.name;f.elements.area.value=p.area;f.elements.hints.value=p.hints;$('#project-new').open=true;f.elements.name.focus();};
  const del=node('button','Delete','danger');del.type='button';del.onclick=async()=>{if(!confirm('Delete '+p.name+'? Its tasks stay, without a project.'))return;try{await act({action:'project_delete',id:p.id});saved('Deleted');await refresh();}catch(e){notice(e.message);}};
  actions.append(edit,del);row.append(label,actions);return row;}));
 if(!s.projects.length)list.replaceChildren(node('p','Projects appear as connected work arrives. Add a project now to teach Paco your own names, areas and clues.','hint'));
 const select=$('#focus-project'),chosen=s.focus?String(s.focus.id):'';
 select.replaceChildren(node('option','All projects'),...s.projects.map(p=>{const o=node('option',p.name+(p.area?' · '+p.area:''));o.value=String(p.id);return o;}));select.options[0].value='';select.value=chosen;
 $('#focus-status').textContent=s.focus?'Focusing on '+s.focus.name+' until the end of today. Other projects stay quiet unless they’re urgent.':'Until the end of today, only the chosen project checks in. Anything you marked urgent still does.';
}
async function saveRhythm(){const f=$('#rhythm-form');const days=[...$('#days').querySelectorAll('input:checked')].map(n=>n.value).join(',');if(!days)throw Error('Choose at least one working day');if(Number(f.elements.start.value)>=Number(f.elements.end.value))throw Error('The end of your working day must be after its start');await act({action:'preference',key:'hours',value:f.elements.start.value+'-'+f.elements.end.value});await act({action:'preference',key:'workdays',value:days});await act({action:'preference',key:'mode',value:$('#mode').value});}
form('#rhythm-form',saveRhythm);
form('#project-form',async f=>{const d=Object.fromEntries(new FormData(f));if(!d.id)delete d.id;await act({action:'project_save',...d});f.reset();f.elements.id.value='';$('#project-new').open=false;});
$('#project-cancel').onclick=()=>{const f=$('#project-form');f.reset();f.elements.id.value='';$('#project-new').open=false;};
$('#focus-save').onclick=()=>act({action:'focus_project',project:$('#focus-project').value?Number($('#focus-project').value):null}).then(()=>{saved('Focus day saved');return refresh();}).catch(e=>notice(e.message));
form('#callout-form',async f=>act({action:'callout_config',enabled:f.elements.enabled.checked,sound:f.elements.sound.checked,judge:f.elements.judge.checked,always:f.elements.always.value,never:f.elements.never.value,behind:Number(f.elements.behind.value)}));
$('#hear-scream').onclick=()=>{const a=$('#screech');a.currentTime=0;a.play().catch(()=>notice('Your Mac blocked the sound. Check that it isn’t muted.'));};
$('#callout-preview').onclick=()=>act({action:'callout_preview'}).then(()=>saved('Call-out sent — top right of your screen')).catch(e=>notice(e.message));
$('#callout-permission').onclick=()=>act({action:'capture_permission'}).then(r=>notice(r.message)).catch(e=>notice(e.message));
form('#flow-form',async f=>act({action:'flow_config',enabled:f.elements.enabled.checked,apps:f.elements.apps.value,pause_seconds:Number(f.elements.pause_seconds.value),urgent_interrupts:f.elements.urgent_interrupts.checked}));
form('#model-form',async f=>{await act({action:'model',provider:f.elements.provider.value,model:f.elements.model.value,endpoint:f.elements.endpoint.value,region:f.elements.region.value,key:f.elements.key.value,allowed_sources:['chat','gmail','mattermost','meeting','activity'].filter(k=>f.elements[k].checked)});f.elements.key.value='';});
form('#agent-form',async f=>act({action:'agent_connect',...Object.fromEntries(new FormData(f))}));
const HINTS={slack:'Slack requires a user token with search:read.',outlook:'A Microsoft Graph token with Mail.Read. Only emails you flag become tasks; reconnect when the token expires.',outlook_calendar:'A Microsoft Graph token with Calendars.Read. Meetings protect your time, get a reminder 15 minutes before, and a Join link.',microsoft_todo:'A Microsoft Graph token with Tasks.Read.',jira:'Jira uses an OAuth access token and your atlassian.net site.',gitlab:'A personal access token with read_api. Leave the address empty for gitlab.com, or enter your own GitLab’s https:// address.',linear:'A Linear personal API key (Settings → Security & access).',asana:'Asana uses a personal or OAuth access token.',todoist:'Todoist uses a personal or OAuth access token.'};
function connectorFields(){const f=$('#connector-form'),p=f.elements.provider.value,site=p==='jira'||p==='gitlab';f.elements.base.hidden=!site;f.elements.base.required=p==='jira';f.elements.base.placeholder=p==='gitlab'?'https://gitlab.example.com (empty for gitlab.com)':'https://your-team.atlassian.net';$('#connector-hint').textContent=HINTS[p];}
$('#connector-form').elements.provider.onchange=connectorFields;connectorFields();
$('#model-form').elements.provider.onchange=modelFields;modelFields();
$('#model-test').onclick=async()=>{const b=$('#model-test');b.disabled=true;$('#model-status').textContent='Asking the model…';try{const r=await act({action:'model_test'});$('#model-status').textContent='Working: '+r.message;}catch(e){$('#model-status').textContent='Not working: '+e.message;}finally{b.disabled=false;}};
form('#connector-form',async f=>{const data=Object.fromEntries(new FormData(f));if(!['jira','gitlab'].includes(data.provider)||!data.base)delete data.base;await act({action:'connector_connect',...data});f.elements.token.value='';await act({action:'sync'});});
document.querySelectorAll('[data-source]').forEach(button=>button.onclick=async()=>{button.disabled=true;try{const source=button.dataset.source;await act(source==='github'?{action:'github_connect'}:{action:'apple_connect',source});saved('Connected');await act({action:'sync'});await refresh();setTimeout(()=>refresh().catch(()=>{}),6000);}catch(e){notice(e.message);}finally{button.disabled=false;}});
$('#finish').onclick=async()=>{const button=$('#finish');button.disabled=true;try{await saveRhythm();await act({action:'setup_finish',autostart:$('#autostart').checked});$('#notice').hidden=true;$('#saved').textContent='Running in background';if(window.parent!==window)parent.postMessage({paco:'navigate',tab:'tasks'},location.origin);else if(window.webkit?.messageHandlers?.paco)window.webkit.messageHandlers.paco.postMessage('setup-complete');else notice('Setup saved. You can close this window; Paco stays running.');}catch(e){notice(e.message);}finally{button.disabled=false;}};
refresh().catch(e=>notice(e.message));
setInterval(async()=>{try{await refresh();}catch(_){}},15000);

form('#company-form',async f=>{const d=Object.fromEntries(new FormData(f));try{await act({action:'company_connect',...d});}finally{f.elements.password.value='';}});
$('#company-sync').onclick=()=>act({action:'company_sync'}).then(refresh).catch(e=>notice(e.message));
$('#company-disconnect').onclick=()=>act({action:'company_disconnect'}).then(refresh).catch(e=>notice(e.message));
function renderCompany(s){const c=s.company||{};$('#company-status').textContent=c.account?'Signed in as '+c.account.username+' · '+(c.error|| (c.last_sync?'Synced '+new Date(c.last_sync*1000).toLocaleTimeString():'Waiting to sync')):'Not connected. Tasks stay on this Mac until you sign in.';$('#company-form').hidden=!!c.account;$('#company-sync').hidden=!c.account;$('#company-disconnect').hidden=!c.account;$('#company-mcp-label').hidden=!c.account;$('#company-mcp').value=c.account?c.account.url+'/mcp':'';
 $('#company-conflicts').replaceChildren(...(c.conflicts||[]).map(x=>{const n=node('div',undefined,'source');n.append(node('span','Changed in both places: '+x.fields.join(', ')));for(const [label,choice] of [['Keep this Mac’s version','local'],['Use company version','remote']]){const b=node('button',label);b.onclick=()=>act({action:'company_resolve',id:x.id,choice}).then(refresh).catch(e=>notice(e.message));n.append(b);}return n;}));}

function activityFields(){const p=$('#activity-provider').value;$('#activity-model-fields').hidden=p==='default';for(const id of ['#activity-endpoint-label','#activity-key-label','#activity-private-options'])$(id).hidden=p!=='private';$('#activity-model-test').hidden=p==='default';}
$('#activity-provider').onchange=activityFields;
form('#activity-model-form',async f=>{await act({action:'activity_model',provider:f.elements.provider.value,model:f.elements.model.value,endpoint:f.elements.endpoint.value,key:f.elements.key.value,allow_activity:f.elements.allow_activity.checked,allow_tasks:f.elements.allow_tasks.checked,remote_processing:f.elements.remote_processing.checked,json_mode:f.elements.json_mode.checked,max_tokens:256});f.elements.key.value='';});
$('#activity-model-test').onclick=async()=>{try{const r=await act({action:'model_test',which:'activity'});saved(r.message);}catch(e){notice(e.message);}};
