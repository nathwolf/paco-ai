'use strict';
const status=document.querySelector('#status');
document.querySelector('#connect').onclick=async()=>{try{
 const value=JSON.parse(document.querySelector('#code').value);
 const base=new URL(value.base);if(base.protocol!=='http:'||base.hostname!=='127.0.0.1'||!base.port||base.pathname!=='/'||base.username||base.password||base.search||base.hash||!/^[A-Za-z0-9_-]{40,80}$/.test(value.token))throw Error('Use the connection code from Paco.');
 const [tab]=await chrome.tabs.query({active:true,currentWindow:true});const url=new URL(tab.url);if(url.origin!=='https://meet.google.com'||!/^\/[a-z]{3}-[a-z]{4}-[a-z]{3}$/.test(url.pathname))throw Error('Select your Google Meet call first.');
 await chrome.runtime.sendMessage({kind:'pair',pair:{base:base.origin,token:value.token,tab:tab.id,url:url.origin+url.pathname}});
 await chrome.scripting.executeScript({target:{tabId:tab.id},files:['content.js']});document.querySelector('#code').value='';status.textContent='Connected to this call. Keep Paco capturing.';
 }catch(e){status.textContent=e.message;}};
document.querySelector('#disconnect').onclick=async()=>{await chrome.runtime.sendMessage({kind:'disconnect'});status.textContent='Disconnected.';};
chrome.storage.session.get('status').then(s=>{status.textContent=s.status||'Not connected';});
