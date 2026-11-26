'use strict';
let sending=false;
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
 (async()=>{
  // Pairing settings can only come from our extension popup, never page scripts.
  if(message.kind==='pair'||message.kind==='disconnect'){
   if(sender.tab||sender.url!==chrome.runtime.getURL('popup.html'))throw Error('Not allowed');
   if(message.kind==='disconnect'){await chrome.storage.session.remove('pair');return {ok:true};}
   await chrome.storage.session.set({pair:message.pair,status:'Waiting for speaker indicators…'});return {ok:true};
  }
  if(message.kind!=='sample')return {stop:true};
  const {pair}=await chrome.storage.session.get('pair');
  if(!pair||sender.tab?.id!==pair.tab||sender.frameId!==0||new URL(sender.url).origin+new URL(sender.url).pathname!==pair.url)return {stop:true};
  if(sending)return {ok:true};sending=true;
  try{
   const response=await fetch(pair.base+'/api/speaker-signal',{method:'POST',headers:{Authorization:'Bearer '+pair.token,'Content-Type':'application/json'},body:JSON.stringify({...message.sample,url:pair.url}),signal:AbortSignal.timeout(3000),cache:'no-store',credentials:'omit',redirect:'error'});
   const result=await response.json();
   await chrome.storage.session.set({status:response.ok?'Paco: '+result.status.replaceAll('_',' '):result.error});
   if(response.status===403){await chrome.storage.session.remove('pair');return {stop:true};}
   return {ok:response.ok,paused:result.status==='paused'};
  }catch(e){await chrome.storage.session.set({status:'Paco is unavailable. Check that meeting capture is running.'});return {stop:true};}
  finally{sending=false;}
 })().then(respond).catch(()=>respond({stop:true}));return true;
});
