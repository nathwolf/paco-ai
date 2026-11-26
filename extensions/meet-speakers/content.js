'use strict';
// Isolated extension world. Only runs after the user connects this specific tab.
if(!globalThis.pacoSpeakerTimer){
 let busy=false,paused=false;
 function snapshot(){
  const found=new Map(),active=[];let supported=false;
  for(const tile of document.querySelectorAll('[data-participant-id], [data-requested-participant-id]')){
   if(found.size>=200)break;
   const id=tile.getAttribute('data-participant-id')||tile.getAttribute('data-requested-participant-id');if(!id||id.length>200)continue;
   const named=tile.querySelector('[data-participant-name], [data-self-name]');
   const name=(tile.getAttribute('data-participant-name')||named?.getAttribute('data-participant-name')||named?.getAttribute('data-self-name')||'').trim();
   if(!name||name.length>120||name.includes('\n'))continue;
   const own=tile.getAttribute('data-is-self')==='true';
   found.set(id,{id,name,self:own});
   const indicator=tile.matches('[data-is-speaking]')?tile:tile.querySelector('[data-is-speaking]');
   const label=tile.getAttribute('aria-label')||'';
   if(indicator)supported=true;
   const speaking=indicator?.getAttribute('data-is-speaking')==='true'||label.toLowerCase().endsWith(' is speaking');
   if(speaking){supported=true;active.push(id);}
  }
  return {status:supported&&found.size?'ok':'unavailable',participants:[...found.values()],active:[...new Set(active)]};
 }
 globalThis.pacoSpeakerTimer=setInterval(async()=>{
  if(busy)return;busy=true;
  try{const result=await chrome.runtime.sendMessage({kind:'sample',sample:paused?{status:'paused',participants:[],active:[]}:snapshot()});paused=!!result?.paused;if(result?.stop){clearInterval(globalThis.pacoSpeakerTimer);delete globalThis.pacoSpeakerTimer;}}
  catch(_){clearInterval(globalThis.pacoSpeakerTimer);delete globalThis.pacoSpeakerTimer;}finally{busy=false;}
 },500);
}
