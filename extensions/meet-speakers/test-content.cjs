const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync(__dirname+'/content.js','utf8');
async function snapshot(tiles){let tick,sent;const ctx={document:{querySelectorAll:()=>tiles},chrome:{runtime:{sendMessage:async message=>{sent=message;return {ok:true};}}},setInterval:fn=>{tick=fn;return 1;},clearInterval:()=>{}};vm.runInNewContext(code,ctx);await tick();return JSON.parse(JSON.stringify(sent.sample));}
const tile=(id,name,speaking)=>({getAttribute:key=>({'data-participant-id':id,'data-participant-name':name,'data-is-speaking':speaking===undefined?null:String(speaking)})[key]??null,matches:()=>speaking!==undefined,querySelector:()=>null});
(async()=>{
 const active=await snapshot([tile('j','Juan',true),tile('a','Ana',false)]);assert.equal(active.status,'ok');assert.deepEqual(active.active,['j']);assert.equal(active.participants[0].name,'Juan');
 const missing=await snapshot([tile('j','Juan',undefined)]);assert.equal(missing.status,'unavailable');assert.deepEqual(missing.active,[]);
 const overlap=await snapshot([tile('j','Juan',true),tile('a','Ana',true)]);assert.deepEqual(overlap.active,['j','a']);
 const unnamed=await snapshot([tile('j','',true)]);assert.deepEqual(unnamed.participants,[]);assert.equal(unnamed.status,'unavailable');
 assert.deepEqual(Object.keys(active).sort(),['active','participants','status']);
 console.log('Meet DOM fixtures passed: active speaker, unsupported markers, overlap, missing names, metadata-only payload.');
})().catch(error=>{console.error(error);process.exitCode=1;});
