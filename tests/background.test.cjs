const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/background.js'),'utf8');
function fixture(closed=true){
 const requests=[],pages=[],reloads=[];
 let clock=Date.now(),timerId=0;const timers=new Map();
 class TestDate extends Date {static now(){return clock;}}
 let navigation=null;
 const event={addListener:()=>{}};
 const port={onMessage:event,onDisconnect:event,postMessage:()=>{}};
 const context={crypto:require('node:crypto').webcrypto,URL,Date:TestDate,setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,due:clock+ms});return id;},clearTimeout:id=>timers.delete(id),console,
  chrome:{action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}},
   runtime:{getManifest:()=>({version:'0.6.0'}),connectNative:()=>port,onMessage:event,id:'test',getURL:s=>'extension://test/'+s},
   tabs:{reload:async id=>reloads.push(id),query:async()=>[{id:1,url:'https://chatgpt.com/'}],get:async()=>({url:'https://chatgpt.com/',windowId:2}),update:async()=>{},onRemoved:event,onUpdated:{addListener:fn=>{navigation=fn;}}},
   windows:{update:async()=>{}},idle:{queryState:async()=>'active',onStateChanged:event}},
  recordRequest:async(cmd,extra)=>requests.push({cmd,extra}),
  recordPage:async(id,action)=>{pages.push(action);return action==='voice-ready'?{state:'VOICE_READY'}:action==='start'?{state:'BROWSER_VOICE'}:['inspect','ready'].includes(action)?{state:'READY'}:{state:'STOPPED',closed};}};
 vm.createContext(context);vm.runInContext(source.replace(/connect\(\)\.then\(\(\)=>request\('register',[^\n]+/, 'badge();'),context);
 vm.runInContext("request=recordRequest;page=recordPage;port={};enabled=true;armed=true;bound={tabId:1,mode:'voice'};sessionToken='session-token';local={local_mic_open:true};",context);
 return {context,requests,pages,reloads,advance:async ms=>{clock+=ms;const due=[...timers.entries()].filter(([,t])=>t.due<=clock);for(const [id,t] of due){timers.delete(id);await t.fn();}},navigate:async(change)=>{await navigation(1,change);await new Promise(resolve=>setImmediate(resolve));},run:s=>vm.runInContext(s,context)};
}
const event=()=>({type:'stop',id:crypto.randomUUID(),session:'session-token',at:Date.now()/1000});
test('spoken command/idle close existing Voice once, resume same local listener, never start a new Voice',async()=>{
 const f=fixture();f.context.event=event();await f.run('handleStop(event)');
 assert.deepEqual(f.pages,['stop','ready']);assert.equal(f.requests.filter(x=>x.cmd==='resume').length,1);
 assert.equal(f.requests.filter(x=>x.cmd==='arm').length,0);assert.equal(f.run('armed&&enabled'),true);
 await f.run('handleStop(event)');assert.equal(f.pages.filter(x=>x==='stop').length,1);
});
test('unconfirmed stop disables listener without resume or retries',async()=>{
 const f=fixture(false);f.context.event=event();await f.run('handleStop(event)');
 assert.equal(f.requests.some(x=>x.cmd==='resume'),false);assert.equal(f.run('enabled'),false);
 assert.equal(f.pages.filter(x=>x==='stop').length,1);assert.equal(f.pages.includes('start'),false);
});
test('stale session cannot close a current conversation',async()=>{
 const f=fixture();f.context.event={...event(),session:'old-session'};await f.run('handleStop(event)');assert.equal(f.pages.length,0);
});
test('wake may open Chrome while local microphone stays open for later stop commands',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};await f.run('handleWake(event)');
 assert.equal(f.pages.includes('start'),true);assert.equal(f.requests.some(x=>x.cmd==='session'),true);
 assert.equal(f.run('local.local_mic_open'),true);
});

test('ChatGPT same-origin loading during Voice does not disable the assistant',async()=>{
 const f=fixture();await f.navigate({status:'loading',url:'https://chatgpt.com/c/test-conversation'});
 assert.equal(f.run('enabled'),true);
 assert.equal(f.requests.some(x=>x.cmd==='disarm'),false);
});
test('leaving ChatGPT detaches the tab and preserves the local listener',async()=>{
 const f=fixture();await f.navigate({url:'https://example.com/'});
 assert.equal(f.run('enabled'),true);
 assert.equal(f.run('bound'),null);
 assert.equal(f.requests.some(x=>x.cmd==='detach'),true);
 assert.equal(f.requests.some(x=>x.cmd==='disarm'),false);
});
test('automatic failure preserves its real reason in local status',async()=>{
 const f=fixture();await f.run("fail('voice-end-unconfirmed')");
 const stopped=f.requests.find(x=>x.cmd==='disarm');
 assert.equal(stopped.extra.reason,'voice-end-unconfirmed');
 const report=f.requests.find(x=>x.cmd==='report'&&x.extra.state==='NEEDS_ACTION');
 assert.equal(report.extra.detail,'voice-end-unconfirmed');assert.equal(f.pages.includes('start'),false);
});
test('explicitly enabling while Voice is open attaches without another Voice start',async()=>{
 const f=fixture();
 f.run("connect=async()=>{};enabled=false;page=async(id,action)=>action==='inspect'?{state:'BLOCKED',detail:'browser-already-recording'}:action==='attach'?{state:'BROWSER_VOICE'}:action==='voice-ready'?{state:'VOICE_READY'}:{state:'STOPPED'}");
 await f.run('enable(true)');
 assert.equal(f.run('enabled'),true);
 assert.equal(f.requests.filter(x=>x.cmd==='arm').length,2);
 assert.equal(f.requests.find(x=>x.cmd==='session').extra.existing,true);
});

test('confirmed close while Chrome busy resumes same mic without disarm or Voice retry',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable'}");
 await f.run('handleStop(event)');
 assert.equal(f.run('enabled&&armed'),true);
 assert.equal(f.requests.filter(x=>x.cmd==='resume').length,1);
 assert.equal(f.requests.some(x=>['disarm','arm'].includes(x.cmd)),false);
 assert.equal(f.requests.some(x=>x.cmd==='report'&&x.extra.state==='WAITING'),true);
});
test('new wake while Chrome busy returns to local listening without retry or disarm',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("page=async()=>({state:'WAITING',detail:'response-generating'})");
 await f.run('handleWake(event)');
 assert.equal(f.run('enabled&&armed'),true);
 assert.equal(f.requests.filter(x=>x.cmd==='defer').length,1);
 assert.equal(f.requests.some(x=>x.cmd==='disarm'),false);
});
test('quota notice still disables, with no defer or retry',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("page=async()=>({state:'BLOCKED',detail:'browser-notice'})");
 await f.run('handleWake(event)');
 assert.equal(f.run('enabled'),false);
 assert.equal(f.requests.some(x=>x.cmd==='defer'),false);
 assert.equal(f.requests.some(x=>x.cmd==='disarm'),true);
});

test('15 seconds of busy UI reloads once and preserves the local listener',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable',canReload:true}");
 await f.run('handleStop(event)');
 await f.advance(14000);assert.equal(f.reloads.length,0);
 await f.advance(1000);assert.equal(f.reloads.length,1);
 assert.equal(f.run('enabled&&armed'),true);
 assert.equal(f.requests.some(x=>['disarm','arm'].includes(x.cmd)),false);
 await f.advance(15000);await f.advance(15000);assert.equal(f.reloads.length,1);
 assert.equal(f.run('enabled&&armed'),true);
});
test('recovery finishes when Start Voice becomes ready, without opening Voice',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'response-generating',canReload:true}");
 await f.run('handleStop(event)');
 f.run("page=async()=>({state:'READY',canReload:true})");
 for(let n=0;n<3;n++)await f.advance(500);
 assert.equal(f.run('recovery'),null);assert.equal(f.reloads.length,0);
 assert.equal(f.run('enabled&&armed'),true);
 assert.equal(f.run('browserState.state'),'IDLE');
});
test('draft or active recording cancels automatic reload but keeps local listening',async()=>{
 for(const detail of ['composer-has-draft','browser-already-recording']){
  const f=fixture();f.context.event=event();
  f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable',canReload:true}");
  await f.run('handleStop(event)');
  f.context.guardDetail=detail;
  f.run("page=async()=>({state:'BLOCKED',detail:guardDetail,canReload:false})");
  await f.advance(15000);assert.equal(f.reloads.length,0);
  assert.equal(f.run('enabled&&armed'),true);
 }
});
test('quota appearing during recovery cancels reload and disables without retry',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'response-generating',canReload:true}");
 await f.run('handleStop(event)');
 f.run("page=async()=>({state:'BLOCKED',detail:'browser-notice',canReload:false})");
 await f.advance(15000);assert.equal(f.reloads.length,0);assert.equal(f.run('enabled'),false);
});
test('turning off or navigating cancels a queued reload',async()=>{
 for(const navigate of [false,true]){
  const f=fixture();f.context.event=event();
  f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'response-generating',canReload:true}");
  await f.run('handleStop(event)');
  if(navigate)await f.navigate({url:'https://chatgpt.com/c/another'});else await f.run('disable(false)');
  await f.advance(15000);assert.equal(f.reloads.length,0);
 }
});
test('fresh guard prevents losing a draft typed just before reload',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable',canReload:true}");
 await f.run('handleStop(event)');
 f.run("let recoveryReads=0;page=async()=>++recoveryReads===1?{state:'WAITING',canReload:true}:{state:'BLOCKED',detail:'composer-has-draft',canReload:false}");
 await f.advance(15000);assert.equal(f.reloads.length,0);assert.equal(f.run('enabled&&armed'),true);
});

test('after one reload ready UI is observed, never starting another Voice automatically',async()=>{
 const f=fixture();f.context.event=event();
 f.run("let checks=[];page=async(id,action)=>{checks.push(action);return action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable',canReload:true}}");
 await f.run('handleStop(event)');await f.advance(15000);assert.equal(f.reloads.length,1);
 f.run("page=async(id,action)=>{checks.push(action);return {state:'READY',canReload:true}}");
 for(let i=0;i<3;i++)await f.advance(500);
 assert.equal(f.run('recovery'),null);assert.equal(f.run('browserState.state'),'IDLE');
 assert.equal(f.run("checks.includes('start')"),false);assert.equal(f.reloads.length,1);
});
test('screen lock during recovery cancels reload and listening',async()=>{
 const f=fixture();f.context.event=event();
 f.run("page=async(id,action)=>action==='stop'?{state:'STOPPED',closed:true}:{state:'WAITING',detail:'voice-start-unavailable',canReload:true}");
 await f.run('handleStop(event)');f.run("chrome.idle.queryState=async()=>'locked'");
 await f.advance(15000);assert.equal(f.reloads.length,0);assert.equal(f.run('enabled'),false);
});

test('only current tab/session UI state reaches the idle timer',async()=>{
 const f=fixture();f.context.sender={tab:{id:1}};
 f.context.message={token:'session-token',ui_state:'busy'};
 await f.run('voiceActivity(message,sender)');
 assert.equal(f.requests.at(-1).extra.ui_state,'busy');
 f.context.message={token:'session-token',ui_state:'idle'};
 await f.run('voiceActivity(message,sender)');assert.equal(f.requests.at(-1).extra.ui_state,'idle');
 const count=f.requests.length;
 f.context.message={token:'old-session',ui_state:'idle'};
 await f.run('voiceActivity(message,sender)');assert.equal(f.requests.length,count);
});

test('warm wake chimes only after a separate microphone-readiness confirmation',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 await f.run('handleWake(event)');
 assert.deepEqual(f.pages,['inspect','start','voice-ready']);
 const cmds=f.requests.map(x=>x.cmd);
 assert.ok(cmds.indexOf('voice-ready')>cmds.indexOf('session'));
 assert.equal(cmds.filter(x=>x==='voice-ready').length,1);
 await f.run('handleWake(event)');assert.equal(cmds.filter(x=>x==='voice-ready').length,1);
});
test('Voice UI without a ready microphone never sends the chime command',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("page=async(id,action)=>action==='inspect'?{state:'READY'}:action==='start'?{state:'BROWSER_VOICE'}:{state:'BLOCKED',detail:'voice-not-ready'}");
 await f.run('handleWake(event)');
 assert.equal(f.requests.some(x=>x.cmd==='voice-ready'),false);
 assert.equal(f.run('enabled'),false);
 assert.equal(f.requests.find(x=>x.cmd==='disarm').extra.reason,'voice-not-ready');
});
test('wake creates and binds a ChatGPT tab when none exists',async()=>{
 const f=fixture();f.context.created=[];f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("bound=null;chrome.tabs.query=async()=>[];chrome.tabs.create=async options=>{created.push(options);return {id:7,url:options.url}};");
 await f.run('handleWake(event)');
 assert.equal(f.context.created.length,1);assert.equal(f.run('bound.tabId'),7);
 assert.equal(f.requests.filter(x=>x.cmd==='voice-ready').length,1);
});
test('wake reuses a deterministically chosen existing tab rather than creating duplicates',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("bound=null;chrome.tabs.query=async()=>[{id:3,lastAccessed:200},{id:2,active:true,lastAccessed:100}];chrome.tabs.create=async()=>{throw Error('duplicate tab')}");
 await f.run('handleWake(event)');assert.equal(f.run('bound.tabId'),2);
});
test('disabling while Chrome is preparing cancels the pending start and chime',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("waitForPage=async()=>{enabled=false;generation++;return {state:'READY'}}");
 await f.run('handleWake(event)');
 assert.equal(f.pages.includes('start'),false);assert.equal(f.requests.some(x=>x.cmd==='voice-ready'),false);
});
test('an expired pending wake cannot start Voice after Chrome eventually loads',async()=>{
 const f=fixture();f.context.event={id:crypto.randomUUID(),at:Date.now()/1000};
 f.run("local.wake_id=event.id;waitForPage=async()=>{local.wake_id=null;return {state:'READY'}}");
 await f.run('handleWake(event)');assert.equal(f.pages.includes('start'),false);
});
test('enabling without a ChatGPT tab only enables the local mic without opening Chrome',async()=>{
 const f=fixture();f.run("enabled=false;bound=null;connect=async()=>{};chrome.tabs.query=async()=>[]");
 await f.run('enable(true)');
 assert.equal(f.requests.filter(x=>x.cmd==='arm').length,1);
 assert.equal(f.pages.length,0);assert.equal(f.run('enabled'),true);
});

test('resumed audio vetoes a pending idle stop and preserves the same Voice session',async()=>{
 const f=fixture();f.context.event={...event(),reason:'silence-timeout',idle_seconds:15};
 f.run("page=async(id,action)=>{pagesForVeto.push(action);return {state:'STOP_VETOED'}}");
 f.context.pagesForVeto=[];
 await f.run('handleStop(event)');
 assert.deepEqual(f.context.pagesForVeto,['stop-idle']);
 assert.equal(f.requests.filter(x=>x.cmd==='stop-vetoed').length,1);
 assert.equal(f.requests.some(x=>['disarm','resume'].includes(x.cmd)),false);
 assert.equal(f.run('enabled&&sessionToken===\"session-token\"&&!stopPending'),true);
});
