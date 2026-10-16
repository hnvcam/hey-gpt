const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/page.js'),'utf8');

function fixture({draft='',label='Start Voice',origin='https://chatgpt.com',duplicate=false,already=false,notice=false,flicker=false,afterStopBusy=false,afterStopDisabled=false,busy=false,statusText='',statusLabel='',progress=false,speaking=false,composerDisabled=false,micOnly=false,turns=[]}={}){
 let clicks=0,recording=already,listener=null,tick=null,messages=[],clock=0,stopped=false;
 const button=name=>({textContent:name,disabled:false,getAttribute:key=>key==='aria-label'?name:null,
  getClientRects:()=>[{}],click:()=>{clicks++;recording=name!=='End Voice';if(name==='End Voice')stopped=true;}});
 const composer={textContent:draft,disabled:composerDisabled,getAttribute:()=>null,getClientRects:()=>[{}]};
 const ctx={location:{origin},getComputedStyle:()=>({visibility:'visible'}),
  setTimeout:fn=>{clock++;fn();return 1;},setInterval:fn=>{tick=fn;return 2;},clearInterval:()=>{tick=null;},
  chrome:{runtime:{sendMessage:async msg=>messages.push(msg)}},
  document:{addEventListener:(name,fn)=>{listener=fn;},removeEventListener:()=>{listener=null;},querySelectorAll:selector=>{
   if(selector.startsWith('[data-user-message-bubble'))return turns;
   if(selector==='button'&&!recording&&((stopped&&afterStopBusy)||busy))return [button('Stop')];
   if(selector==='button'&&!recording&&stopped&&afterStopDisabled){const b=button('Dictate');b.disabled=true;return [b];}
   if(selector==='button'&&recording&&micOnly)return [button('Turn off microphone'),button('Send')];
   if(selector==='button'&&recording&&speaking)return [button('End Voice'),button('Stop speaking')];
   if(selector==='button')return (recording||(flicker&&stopped&&clock===2))?[button('End Voice')]:duplicate?[button(label),button(label)]:[button(label)];
   if(selector==='[role="status"]')return statusText||statusLabel?[{textContent:statusText,getAttribute:key=>key==='aria-label'?statusLabel:null,getClientRects:()=>[{}]}]:[];
   if(selector.includes('role="progressbar"'))return progress?[{getClientRects:()=>[{}]}]:[];
   if(selector.includes('role="alert"'))return notice?[{textContent:'Voice limit reached',getClientRects:()=>[{}]}]:[];
   return [composer];
  }}};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 return {run:action=>ctx.heyGPT(action,'voice','test-token'),
  setEvents:(ui_state,age=0)=>{ctx.heyGPTState.events={ui_state,connected:true,received:Date.now()-age};},clicks:()=>clicks,messages,clock:()=>clock,
  frame:value=>{recording=value;tick?.();},
  end:trusted=>{if(trusted&&listener){const end=button('End Voice');listener({isTrusted:true,target:{closest:()=>end}});}recording=false;for(let i=0;i<3;i++)tick?.();},
  setNotice:()=>{notice=true;},
  setDraft:()=>{composer.textContent='nội dung chưa gửi';}};
}

test('preflight does not click; wake clicks once and observes Voice UI',async()=>{
 const f=fixture();assert.equal((await f.run('inspect')).state,'READY');assert.equal(f.clicks(),0);
 assert.equal((await f.run('start')).state,'BROWSER_VOICE');assert.equal(f.clicks(),1);
});
test('draft, wrong origin, duplicate, missing button, live limit and existing Voice block',async()=>{
 for(const options of [{draft:'câu chưa gửi'},{origin:'https://example.com'},{duplicate:true},{label:'Send'},{notice:true}]){
  const f=fixture(options);assert.equal((await f.run('start')).state,'BLOCKED');assert.equal(f.clicks(),0);
 }
});
test('existing Voice is attached on a wake without clicking Start or End',async()=>{
 const f=fixture({already:true});assert.equal((await f.run('start')).state,'BROWSER_VOICE');
 assert.equal(f.clicks(),0);
});
test('trusted End Voice authorizes local rearm only',async()=>{
 const f=fixture();await f.run('start');f.end(true);
 assert.equal(f.messages.length,1);assert.equal(f.messages[0].userEnded,true);
 assert.equal(f.messages[0].token,'test-token');assert.equal(f.clicks(),1);
});
test('server/tool Voice end with stable closed UI authorizes local rearm only',async()=>{
 const f=fixture();await f.run('start');f.end(false);
 assert.equal(f.messages.length,1);assert.equal(f.messages[0].userEnded,true);assert.equal(f.clicks(),1);
});
test('quota notice overrides a trusted End Voice click',async()=>{
 const f=fixture();await f.run('start');f.setNotice();f.end(true);
 assert.equal(f.messages.length,1);assert.equal(f.messages[0].userEnded,false);
});
test('turning assistant off ends Voice once and stops monitoring',async()=>{
 const f=fixture();await f.run('start');assert.equal((await f.run('stop')).state,'STOPPED');
 assert.equal(f.clicks(),2);assert.equal(f.messages.length,0);
});
test('one transient missing Voice control does not shut down the listener',async()=>{
 const f=fixture();await f.run('start');f.frame(false);
 assert.equal(f.messages.length,0);f.frame(true);assert.equal(f.messages.filter(m=>m.cmd==='voice-ended').length,0);
});
test('stop waits for stable closed UI across React flicker',async()=>{
 const f=fixture({flicker:true});await f.run('start');
 const before=f.clock();const result=await f.run('stop');
 assert.equal(result.closed,true);assert.ok(f.clock()-before>=3);assert.equal(f.clicks(),2);
});
test('Voice already ended before stop request can rearm only after stable ready UI',async()=>{
 const f=fixture();const result=await f.run('stop');
 assert.equal(result.closed,true);assert.equal(f.clicks(),0);assert.ok(f.clock()>=3);
 const limited=fixture({notice:true});assert.equal((await limited.run('stop')).closed,false);
});

test('normal stop confirms closed even while response is busy or Voice button is disabled',async()=>{
 for(const options of [{afterStopBusy:true},{afterStopDisabled:true}]){
  const f=fixture(options);await f.run('start');
  assert.equal((await f.run('stop')).closed,true);
  assert.equal((await f.run('ready')).state,'WAITING');
  assert.equal(f.clicks(),2);
 }
});
test('busy Start request waits without clicking Stop or retrying Voice',async()=>{
 const f=fixture({busy:true});assert.equal((await f.run('start')).state,'WAITING');
 assert.equal(f.clicks(),0);
});
test('manual End Voice remains normal even before Start Voice reappears',async()=>{
 const f=fixture({afterStopBusy:true});await f.run('start');f.end(true);
 assert.equal(f.messages[0].userEnded,true);
});

test('reload safety inspection accepts only a known empty composer without recording or notices',async()=>{
 const busy=fixture({busy:true});const ok=await busy.run('recovery-inspect');
 assert.equal(ok.state,'WAITING');assert.equal(ok.canReload,true);assert.equal(busy.clicks(),0);
 for(const options of [{draft:'chưa gửi'},{notice:true},{already:true},{origin:'https://example.com'}]){
  const f=fixture(options);assert.equal((await f.run('recovery-inspect')).canReload,false);assert.equal(f.clicks(),0);
 }
});

test('global Working, Response complete, and progress never establish live Voice idle',async()=>{
 for(const opts of [{statusText:'Response complete'},{statusLabel:'Working'},{progress:true},{}]){
  assert.equal((await fixture({already:true,...opts}).run('turn-status')).ui_state,'unknown');
 }
});
test('fresh channel states drive the timer while UI labels cannot override them',async()=>{
 const f=fixture({already:true,statusLabel:'Working'});
 f.setEvents('idle');assert.equal((await f.run('turn-status')).ui_state,'idle');
 f.setEvents('busy');assert.equal((await f.run('turn-status')).ui_state,'busy');
 f.setEvents('idle',5000);assert.equal((await f.run('turn-status')).ui_state,'unknown');
});
test('feedback page after hangup never supplies turn idle even with retained live-channel state',async()=>{
 const f=fixture({statusLabel:'Working'});f.setEvents('idle');
 assert.equal((await f.run('turn-status')).ui_state,'unknown');assert.equal(f.clicks(),0);
});

test('typing replaces End Voice with Send but microphone control proves Voice remains open',async()=>{
 const f=fixture({already:true,micOnly:true,draft:'nội dung chưa gửi'});
 assert.equal((await f.run('inspect')).detail,'browser-already-recording');
 assert.equal((await f.run('attach')).state,'BROWSER_VOICE');
 for(let i=0;i<6;i++)f.frame(true);
 assert.equal(f.messages.some(m=>m.cmd==='voice-ended'),false);
 f.setEvents('idle');assert.equal((await f.run('turn-status')).ui_state,'busy');
});

function turn(kind,{animated=false,complete=true}={}){return {getClientRects:()=>[{}],
 getAttribute:k=>k==='data-user-message-bubble'&&kind==='user'?'true':null,
 hasAttribute:k=>k==='data-markdown-animated'&&animated,
 closest:()=>complete?{getAttribute:()=> 'final-message-id'}:null};}
test('server idle cannot cut an animated long Voice response or pending user question',async()=>{
 for(const turns of [[turn('assistant',{animated:true,complete:false})],[turn('assistant'),turn('user')]]){
  const f=fixture({already:true,turns});f.setEvents('idle');
  for(let seconds=0;seconds<60;seconds++)assert.equal((await f.run('turn-status')).ui_state,'busy');
 }
});
test('finalized latest Voice turn can idle only with fresh connected observation',async()=>{
 const f=fixture({already:true,turns:[turn('assistant')]});f.setEvents('unknown');
 assert.equal((await f.run('turn-status')).ui_state,'idle');
 f.setEvents('busy');assert.equal((await f.run('turn-status')).ui_state,'busy');
 f.setEvents('unknown',5000);assert.equal((await f.run('turn-status')).ui_state,'unknown');
});
test('missing final message marker never implies idle even if server is listening',async()=>{
 const f=fixture({already:true,turns:[turn('assistant',{complete:false})]});f.setEvents('idle');
 assert.equal((await f.run('turn-status')).ui_state,'unknown');
});
