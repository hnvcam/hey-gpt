let port=null,ready=null,bound=null,enabled=false,armed=false,generation=0,sessionToken=null,stopPending=false;
let local={state:'DISARMED',local_mic_open:false,detail:'not-connected'};
let browserState={state:'IDLE',detail:''};
const pending=new Map(),seen=new Set();
const extensionVersion=chrome.runtime.getManifest().version;
let recovery=null;
const RECOVERY_WAIT=15000,RECOVERY_POLL=500;
function cancelRecovery(){
  if(recovery?.timer)clearTimeout(recovery.timer);
  recovery=null;
}
function beginRecovery(){
  if(recovery||!enabled||!bound||bound.mode!=='voice')return;
  const item={tabId:bound.tabId,epoch:generation,url:null,deadline:Date.now()+RECOVERY_WAIT,
              reloaded:false,stable:0,timer:null};
  recovery=item;
  const current=()=>recovery===item&&enabled&&generation===item.epoch&&bound?.tabId===item.tabId;
  const schedule=()=>{if(current())item.timer=setTimeout(tick,RECOVERY_POLL);};
  async function tick(){
    if(!current())return;
    // A wake/start attempt owns the page until it completes. Never reload it.
    if(sessionToken!==null){schedule();return;}
    try{
      const tab=await chrome.tabs.get(item.tabId);
      if(!current())return;
      if(!valid(tab.url)){cancelRecovery();return;}
      if(item.url===null)item.url=tab.url;
      if(tab.url!==item.url){cancelRecovery();return;}
      if(tab.status==='loading'){
        if(Date.now()>=item.deadline){cancelRecovery();browserState={state:'WAITING',detail:'recovery-timeout'};await report('WAITING');return;}
        schedule();return;
      }
      const check=await page(item.tabId,'recovery-inspect');
      if(!current()||sessionToken!==null){schedule();return;}
      if(check.detail==='browser-notice'){cancelRecovery();await fail('browser-notice');return;}
      if(check.state==='BLOCKED'){
        cancelRecovery();browserState={state:'WAITING',detail:check.detail};await report('WAITING');return;
      }
      item.stable=check.state==='READY'?item.stable+1:0;
      if(item.stable>=3){
        cancelRecovery();browserState={state:'IDLE',detail:'waiting-for-next-wake'};await report('IDLE');return;
      }
      if(check.state==='READY'){schedule();return;}
      if(Date.now()<item.deadline){schedule();return;}
      if(item.reloaded||check.canReload!==true){
        cancelRecovery();browserState={state:'WAITING',detail:'recovery-timeout'};await report('WAITING');return;
      }
      if(await chrome.idle.queryState(60)==='locked'){cancelRecovery();await disable(false);return;}
      browserState={state:'WAITING',detail:'reloading-chatgpt'};await report('WAITING');
      if(!current()||sessionToken!==null)return;
      // Recheck both destination and draft/notice immediately before reloading.
      const destination=await chrome.tabs.get(item.tabId);
      const fresh=await page(item.tabId,'recovery-inspect');
      if(!current()||sessionToken!==null){schedule();return;}
      if(destination.url!==item.url||!valid(destination.url)){cancelRecovery();return;}
      if(fresh.detail==='browser-notice'){cancelRecovery();await fail('browser-notice');return;}
      if(fresh.state==='READY'){item.stable=1;schedule();return;}
      if(fresh.state!=='WAITING'||fresh.canReload!==true){
        cancelRecovery();browserState={state:'WAITING',detail:fresh.detail};await report('WAITING');return;
      }
      item.reloaded=true;item.deadline=Date.now()+RECOVERY_WAIT;item.stable=0;
      await chrome.tabs.reload(item.tabId);
      schedule();
    }catch{
      if(!current())return;
      if(Date.now()<item.deadline){schedule();return;}
      cancelRecovery();browserState={state:'WAITING',detail:'recovery-timeout'};await report('WAITING').catch(()=>{});
    }
  }
  schedule();
}
const valid=url=>{try{return new URL(url).origin==='https://chatgpt.com';}catch{return false;}};
async function badge(){
  const text=browserState.state==='BROWSER_VOICE'?'TALK':local.local_mic_open?'MIC':enabled?'ON':browserState.state==='NEEDS_CLICK'?'!':'OFF';
  await chrome.action.setBadgeText({text});
  await chrome.action.setBadgeBackgroundColor({color:local.local_mic_open?'#16844c':enabled?'#2563eb':'#64748b'});
}
function connect(){
  if(port)return ready;
  let resolveReady,rejectReady,settled=false;
  const waiting=new Promise((resolve,reject)=>{resolveReady=resolve;rejectReady=reject;});
  ready=waiting;
  let channel;
  const drop=detail=>{
    if(port!==channel)return;
    clearTimeout(timer);cancelRecovery();port=null;ready=null;armed=false;enabled=false;
    generation++;sessionToken=null;stopPending=false;
    if(!settled){settled=true;rejectReady(new Error(detail));}
    for(const item of pending.values())item.reject(new Error(detail));
    pending.clear();
    local={state:'DISCONNECTED',local_mic_open:false,detail};
    badge();
  };
  const timer=setTimeout(()=>{
    drop('native-connect-timeout');
    try{channel?.disconnect();}catch{}
  },5000);
  try{channel=chrome.runtime.connectNative('org.local.hey_gpt');port=channel;}
  catch{clearTimeout(timer);ready=null;settled=true;rejectReady(new Error('native-host-unavailable'));return waiting;}
  channel.onMessage.addListener(message=>{
    if(port!==channel)return;
    if(message.type==='status'){
      if(!settled){settled=true;clearTimeout(timer);resolveReady();}
      local=message;
      if(['DISARMED','ERROR'].includes(message.state)&&message.enabled===false){armed=false;enabled=false;}
      badge();
    }else if(message.type==='ack'){
      pending.get(message.request)?.resolve();pending.delete(message.request);
    }else if(message.type==='wake'){
      handleWake(message).catch(()=>fail('browser-operation-failed'));
    }else if(message.type==='stop'){
      handleStop(message).catch(()=>fail('voice-end-failed'));
    }else if(message.type==='control'){
      (message.action==='enable'?enable(false):disable(true)).catch(()=>fail('browser-operation-failed'));
    }else if(message.type==='error'){
      if(!settled){drop(message.detail||'native-host-unavailable');try{channel.disconnect();}catch{}}
      else fail(message.detail);
    }
  });
  channel.onDisconnect.addListener(()=>{
    const error=chrome.runtime.lastError;
    drop(error?'native-host-unavailable':'disconnected');
  });
  return waiting;
}
async function request(cmd,extra={}){
  await connect();const id=crypto.randomUUID();
  const done=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Dịch vụ local không phản hồi.'));},8000);
    pending.set(id,{resolve:()=>{clearTimeout(timer);resolve();},reject:e=>{clearTimeout(timer);reject(e);}});
  });
  try{port.postMessage({cmd,request:id,...extra});}
  catch{pending.get(id)?.reject(new Error('disconnected'));pending.delete(id);}
  return done;
}
async function page(tabId,action,mode='voice',token=''){
  await chrome.scripting.executeScript({target:{tabId},world:'MAIN',files:['voice-events.js']});
  await chrome.scripting.executeScript({target:{tabId},files:['page.js']});
  const results=await chrome.scripting.executeScript({target:{tabId},func:(a,m,t)=>globalThis.heyGPT(a,m,t),args:[action,mode,token]});
  return results[0]?.result||{state:'BLOCKED',detail:'no-page-result'};
}
async function report(state){if(port)await request('report',{state,detail:browserState.detail||''});await badge();}
async function disable(stopVoice=false,reason='user-disarmed'){
  cancelRecovery();
  enabled=false;armed=false;generation++;sessionToken=null;stopPending=false;
  if(port)await request('disarm',{reason});
  if(bound){
    try{browserState=await page(bound.tabId,stopVoice?'stop':'unwatch',bound.mode);}catch{browserState={state:'STOPPED',detail:'tab-unavailable'};}
  }
  await report(browserState.state==='NEEDS_CLICK'?'NEEDS_ACTION':'STOPPED');
}
async function fail(detail){
  await disable(false,detail).catch(()=>{});
  browserState={state:'NEEDS_CLICK',detail};
  await report('NEEDS_ACTION').catch(()=>{});
}
async function chooseBound(fromPopup,mode){
  if(fromPopup){
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    if(!tab||!valid(tab.url))throw new Error('Mở tab ChatGPT trước khi bật trợ lý.');
    bound={tabId:tab.id,mode};return;
  }
  if(bound){try{if(valid((await chrome.tabs.get(bound.tabId)).url))return;}catch{}}
  const tabs=await chrome.tabs.query({url:'https://chatgpt.com/*'});
  if(tabs.length!==1)throw new Error('Mở một tab ChatGPT, hoặc chọn tab trong tiện ích Chrome.');
  bound={tabId:tabs[0].id,mode:'voice'};
}
async function armExisting(){
  if(!enabled||!bound)return;
  const check=await page(bound.tabId,'inspect',bound.mode);
  if(bound.mode==='voice'&&check.detail==='browser-already-recording') {
    sessionToken=crypto.randomUUID();
    const attached=await page(bound.tabId,'attach','voice',sessionToken);
    if(attached.state!=='BROWSER_VOICE')return fail(attached.detail);
    armed=false;browserState=attached;
    await request('arm');
    await request('session',{session:sessionToken,existing:true});
    await report('VOICE');return;
  }
  if(!['READY','WAITING'].includes(check.state))return fail(check.detail);
  armed=true;browserState=check.state==='WAITING'?check:{state:'IDLE',detail:''};
  await request('arm');await report(check.state==='WAITING'?'WAITING':'IDLE');
}
async function enable(fromPopup,mode='voice'){
  if(enabled&&bound){
    if(!fromPopup)return;
    const [active]=await chrome.tabs.query({active:true,currentWindow:true});
    if(active?.id===bound.tabId&&mode===bound.mode)return;
  }
  await disable(false);
  await connect();await request('register',{extension_version:extensionVersion});
  await chooseBound(fromPopup,mode);
  enabled=true;generation++;await armExisting();
}
async function handleWake(message){
  if(!armed||!enabled||!bound||seen.has(message.id)||Math.abs(Date.now()/1000-message.at)>5)return;
  seen.add(message.id);if(seen.size>50)seen.delete(seen.values().next().value);
  armed=false;const chosen={...bound},token=generation;
  const tab=await chrome.tabs.get(chosen.tabId);
  if(!valid(tab.url))return fail('target-tab-changed');
  if(await chrome.idle.queryState(60)==='locked')return disable(false);
  await chrome.tabs.update(chosen.tabId,{active:true});await chrome.windows.update(tab.windowId,{focused:true});
  if(generation!==token||!enabled)return;
  sessionToken=crypto.randomUUID();
  browserState=await page(chosen.tabId,'start',chosen.mode,sessionToken);
  if(generation!==token||!enabled){await page(chosen.tabId,'stop').catch(()=>{});return;}
  if(browserState.state==='BROWSER_VOICE'){cancelRecovery();await request('session',{session:sessionToken});await report('VOICE');}
  else if(browserState.state==='BROWSER_DICTATION'){
    // Dictation leaves editable text; do not auto-submit it or rearm over a draft.
    enabled=false;await request('disarm');await report('DICTATION');
  }else if(browserState.state==='WAITING'){
    await request('defer');if(generation!==token||!enabled)return;
    sessionToken=null;armed=true;await report('WAITING');
  }else await fail(browserState.detail);
}
async function resumeAfterEnd(token){
  if(!enabled||!bound||token!==sessionToken)return;
  const epoch=generation;
  if(await chrome.idle.queryState(60)==='locked')return disable(false);
  const check=await page(bound.tabId,'ready','voice');
  if(!enabled||generation!==epoch||token!==sessionToken)return;
  if(!['READY','WAITING'].includes(check.state))return fail(check.detail);
  await request('resume',{session:token});
  if(!enabled||generation!==epoch||token!==sessionToken)return;
  sessionToken=null;stopPending=false;armed=true;
  browserState=check.state==='WAITING'?check:{state:'IDLE',detail:'waiting-for-next-wake'};
  await report(check.state==='WAITING'?'WAITING':'IDLE');
  if(check.state==='WAITING')beginRecovery();
}
async function handleStop(message){
  if(!enabled||!bound||!sessionToken||stopPending||message.session!==sessionToken||seen.has(message.id)||Math.abs(Date.now()/1000-message.at)>5)return;
  seen.add(message.id);if(seen.size>50)seen.delete(seen.values().next().value);
  const token=sessionToken,epoch=generation;stopPending=true;
  browserState=await page(bound.tabId,'stop','voice',token);
  if(epoch!==generation||!enabled)return;
  if(browserState.state!=='STOPPED'||browserState.closed!==true)return fail(browserState.detail);
  await resumeAfterEnd(token);
}
async function voiceEnded(message,sender){
  if(!enabled||!bound||sender.tab?.id!==bound.tabId||message.token!==sessionToken||stopPending)return;
  if(message.userEnded!==true)return fail(message.detail==='browser-notice'?'browser-notice':'voice-ended-unexpectedly');
  await resumeAfterEnd(sessionToken);
}
async function voiceActivity(message,sender){
  if(!enabled||!bound||sender.tab?.id!==bound.tabId||message.token!==sessionToken||stopPending)return;
  const state=['idle','busy','unknown'].includes(message.ui_state)?message.ui_state:'unknown';
  await request('activity',{session:sessionToken,ui_state:state,voice_events:message.voice_events});
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(sender.id!==chrome.runtime.id)return;
  if(sender.tab){
    if(message.cmd==='voice-ended')voiceEnded(message,sender).catch(()=>fail('rearm-failed'));
    if(message.cmd==='voice-activity')voiceActivity(message,sender).catch(()=>{});
    return;
  }
  if(sender.url!==chrome.runtime.getURL('popup.html'))return;
  (async()=>{
    if(message.cmd==='info'){await connect();await request('register',{extension_version:extensionVersion});await request('status');}
    else if(message.cmd==='arm')await enable(true,message.mode==='dictate'?'dictate':'voice');
    else if(message.cmd==='disarm')await disable(true);
    reply({ok:true,enabled,armed,local,browser:browserState,target:bound});
  })().catch(error=>{if(message.cmd!=='info')fail('setup-required').catch(()=>{});reply({ok:false,error:error.message});});
  return true;
});
chrome.tabs.onRemoved.addListener(id=>{if(bound?.tabId===id){disable(false).catch(()=>{});bound=null;}});
chrome.tabs.onUpdated.addListener((id,change)=>{
  if(recovery?.tabId===id&&change.url&&(!recovery.url||change.url!==recovery.url))cancelRecovery();
  // A manual reload cancels our pending recovery; an owned reload is one-shot.
  if(recovery?.tabId===id&&change.status==='loading'&&!recovery.reloaded)cancelRecovery();
  // ChatGPT may report loading while it opens Voice. Keep the same-origin tab bound;
  // a loading event alone is not evidence that the user left ChatGPT.
  if(bound?.tabId===id&&change.url&&!valid(change.url))disable(false).catch(()=>{});
});
chrome.idle.onStateChanged.addListener(state=>{if(state==='locked')disable(false).catch(()=>{});});
// Connect for tray controls; never enable microphone merely because Chrome starts.
connect().then(()=>request('register',{extension_version:extensionVersion})).catch(()=>{});badge();
