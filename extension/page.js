/* Isolated extension world. Never reads chat messages or calls private endpoints. */
(() => {
  const state = globalThis.heyGPTState ||= {watch:null};
  // Only status metadata crosses from MAIN world. It cannot open Voice or invoke
  // extension commands. The bound tab/session checks remain in background.js.
  if(typeof window!=='undefined'&&state.eventsListener&&state.eventsVersion!==2){
    window.removeEventListener('message',state.eventsListener);state.eventsListener=null;
  }
  if (!state.eventsListener && typeof window !== 'undefined') {
    state.eventsVersion=2;
    state.eventsListener = event => {
      const data=event.data;
      if(event.source!==window||event.origin!==location.origin||data?.kind!=='hey-gpt-voice-events'||data.nonce!==state.eventsNonce||data.observer_version!==2)return;
      if(!['idle','busy','unknown'].includes(data.ui_state)||!Number.isFinite(data.at)||Math.abs(Date.now()-data.at)>2000)return;
      state.events={ui_state:data.ui_state,playback_state:['busy','quiet','unknown'].includes(data.playback_state)?data.playback_state:'unknown',
        playback_quiet_ms:Number.isFinite(data.playback_quiet_ms)?Math.max(0,data.playback_quiet_ms):0,connected:data.connected===true,microphone_ready:data.microphone_ready===true,supported:data.supported===true,
        event_count:Number.isSafeInteger(data.event_count)?Math.max(0,data.event_count):0,
        event_types:Array.isArray(data.event_types)?data.event_types.filter(x=>typeof x==='string'&&/^[a-z0-9_.]{1,80}$/.test(x)).slice(-8):[],
        received:Date.now()};
    };
    window.addEventListener('message',state.eventsListener);
  }
  function queryEvents() {
    if(typeof window==='undefined')return;
    state.eventsNonce=String(Date.now())+'-'+(state.eventsQuery=(state.eventsQuery||0)+1);
    window.postMessage({kind:'hey-gpt-query-voice-events',nonce:state.eventsNonce},location.origin);
    return state.eventsNonce;
  }
  function eventStatus() {
    const events=state.events;
    return events&&Date.now()-events.received>=0&&Date.now()-events.received<2500&&events.connected?events.ui_state:'unknown';
  }
  function playbackStatus(){
    const events=state.events;
    return events&&events.connected&&Date.now()-events.received>=0&&Date.now()-events.received<2500?events.playback_state:'unknown';
  }
  const visible = el => Boolean(el.getClientRects().length) && getComputedStyle(el).visibility !== 'hidden';
  const buttons = labels => [...document.querySelectorAll('button')].filter(el => visible(el) && labels.includes(el.getAttribute('aria-label') || el.textContent.trim()));
  const endLabels = ['End Voice','Kết thúc cuộc trò chuyện','Kết thúc thoại'];
  const dictLabels = ['Stop dictation','Stop recording','Dừng đọc chính tả','Dừng ghi âm'];
  const responseBusy = () => buttons(['Stop','Stop generating','Stop response','Dừng tạo','Dừng phản hồi','Stop speaking','Dừng nói']).length > 0;
  const composers = () => [...document.querySelectorAll('[role="textbox"][contenteditable="true"],textarea')].filter(visible);
  const micLabels=['Turn off microphone','Turn on microphone','Tắt micrô','Bật micrô','Tắt micro','Bật micro'];
  const voiceOpen = () => buttons(endLabels).length > 0 || buttons(micLabels).length > 0;
  const dictOpen = () => buttons(dictLabels).length > 0;
  // Only live notices; never scan chat history for errors or quoted instructions.
  const blocked = () => [...document.querySelectorAll('[role="alert"],[role="dialog"]')].some(el => visible(el) &&
    /limit|quota|reached|try again|error|unavailable|permission|hạn mức|giới hạn|thử lại|lỗi|không khả dụng|quyền/i.test(el.textContent));
  function inspect(mode) {
    if (location.origin !== 'https://chatgpt.com') return {state:'BLOCKED',detail:'wrong-origin'};
    if (blocked()) return {state:'BLOCKED',detail:'browser-notice'};
    if (voiceOpen() || dictOpen()) return {state:'BLOCKED',detail:'browser-already-recording'};
    const inputs = composers();
    if (inputs.length !== 1) return {state:'BLOCKED',detail:'composer-not-found'};
    if ((inputs[0].value || inputs[0].textContent || '').trim()) return {state:'BLOCKED',detail:'composer-has-draft'};
    const labels = mode === 'dictate' ? ['Dictate','Đọc chính tả'] : ['Start Voice','Bắt đầu chế độ giọng nói','Bắt đầu trò chuyện bằng giọng nói'];
    if(responseBusy())return {state:'WAITING',detail:'response-generating'};
    const candidates = buttons(labels).filter(el => !el.disabled);
    if(!candidates.length && (buttons(labels).some(el=>el.disabled) || buttons(['Dictate','Đọc chính tả']).some(el=>el.disabled)))return {state:'WAITING',detail:'voice-start-unavailable'};
    return candidates.length === 1 ? {state:'READY',detail:mode,button:candidates[0]} : {state:'BLOCKED',detail:'voice-button-missing-or-ambiguous'};
  }
  function turnStatus() {
    if(location.origin!=='https://chatgpt.com'||blocked()||!voiceOpen())return 'unknown';
    if(composers().some(el=>(el.value||el.textContent||'').trim()))return 'busy';
    const transport=eventStatus();
    if(playbackStatus()==='busy'||transport==='busy'||responseBusy())return 'busy';
    // These DOM markers were measured with a synthetic Vietnamese question in
    // live Voice. Streaming text has data-markdown-animated and no message ID;
    // a finalized turn loses the animation marker and gains its message ID.
    // Inspect structure only: never read or forward question/answer text.
    const turns=[...document.querySelectorAll('[data-user-message-bubble="true"],[data-markdown-text-style="assistant-message"]')].filter(visible);
    const latest=turns.at(-1);
    if(!latest)return 'unknown';
    if(latest.getAttribute('data-user-message-bubble')==='true')return 'busy';
    if(latest.hasAttribute('data-markdown-animated'))return 'busy';
    const complete=latest.closest('[data-chatgpt-selection-message-id]');
    if(!complete?.getAttribute('data-chatgpt-selection-message-id'))return 'unknown';
    // A live peer and completed latest turn are both required. A survey,
    // stale global Response complete label, or missing selectors never suffice.
    return playbackStatus()==='quiet'?'idle':'unknown';
  }

  function stopWatching() {
    if (!state.watch) return;
    clearInterval(state.watch.timer);
    document.removeEventListener('click',state.watch.onClick,true);
    state.watch=null;
  }
  function recoveryInspect() {
    if(location.origin!=='https://chatgpt.com')return {state:'BLOCKED',detail:'wrong-origin',canReload:false};
    if(blocked())return {state:'BLOCKED',detail:'browser-notice',canReload:false};
    if(voiceOpen()||dictOpen())return {state:'BLOCKED',detail:'browser-already-recording',canReload:false};
    const inputs=composers();
    if(inputs.length!==1)return {state:'WAITING',detail:'voice-transition-pending',canReload:false};
    if((inputs[0].value||inputs[0].textContent||'').trim())return {state:'BLOCKED',detail:'composer-has-draft',canReload:false};
    const check=inspect('voice');
    return {state:check.state==='READY'?'READY':'WAITING',detail:check.detail,canReload:true};
  }
  async function closedStable() {
    let stable=0;
    for(let n=0;n<32;n++) {
      await new Promise(resolve=>setTimeout(resolve,250));
      if(location.origin!=='https://chatgpt.com')return {state:'NEEDS_CLICK',detail:'wrong-origin',closed:false};
      if(blocked())return {state:'NEEDS_CLICK',detail:'browser-notice',closed:false};
      // Following an explicit End click, the composer can still be remounting.
      // Closure and readiness for the next call are separate observations.
      stable=!voiceOpen() && !dictOpen()?stable+1:0;
      if(stable>=3)return {state:'STOPPED',detail:'voice-ended',closed:true};
    }
    return {state:'NEEDS_CLICK',detail:'voice-end-unconfirmed',closed:false};
  }
  async function readyStable() {
    const ended=await closedStable();
    if(!ended.closed)return {state:'BLOCKED',detail:ended.detail};
    const check=inspect('voice');
    // Local wake listening does not require Chrome's next Start button yet.
    if(check.detail==='browser-notice'||check.detail==='wrong-origin')return {state:'BLOCKED',detail:check.detail};
    return check.state==='READY'?{state:'READY',detail:'voice'}:
      {state:'WAITING',detail:check.detail};
  }
  function watch(token) {
    stopWatching();
    const watchState={token,userEnded:false,endingAt:0,absent:0};
    queryEvents();
    watchState.onClick=event=>{
      const el=event.target.closest?.('button');
      if (event.isTrusted && el && endLabels.includes(el.getAttribute('aria-label') || el.textContent.trim()) && voiceOpen()) {
        watchState.userEnded=true;watchState.endingAt=Date.now();
      }
    };
    document.addEventListener('click',watchState.onClick,true);
    watchState.timer=setInterval(()=>{
      if(blocked()){stopWatching();chrome.runtime.sendMessage({cmd:'voice-ended',token,userEnded:false,detail:'browser-notice'}).catch(()=>{});return;}
      if (voiceOpen()) {
        queryEvents();watchState.absent=0;
        const ui_state = turnStatus();
        watchState.idleSince=ui_state==='idle'?(watchState.idleSince??Date.now()):null;
        if (Date.now()-(watchState.lastHeartbeat || 0)>500) {
          watchState.lastHeartbeat=Date.now();
          chrome.runtime.sendMessage({cmd:'voice-activity',token,ui_state,voice_events:{source:'data-channel',playback_state:playbackStatus(),playback_quiet_ms:state.events?.playback_quiet_ms||0,connected:state.events?.connected===true,supported:ui_state!=='unknown',event_count:state.events?.event_count||0,event_types:state.events?.event_types||[]}}).catch(()=>{});
        }
        // A click which did not actually end Voice must not authorize a later disconnect.
        if (watchState.userEnded && Date.now()-watchState.endingAt>10000) watchState.userEnded=false;
        return;
      }
      const result=inspect('voice');
      // React can briefly remove/recreate the controls. A single missed poll
      // is not proof that the call ended. Real notices still stop immediately.
      if(!blocked() && ++watchState.absent<3)return;
      if(!watchState.closedAt)watchState.closedAt=Date.now();
      if(composers().length!==1&&!blocked()&&Date.now()-watchState.closedAt<15000)return;
      if (watchState.userEnded && Date.now()-watchState.endingAt<=10000 && composers().length!==1 && !blocked()) return;
      // A server/tool hangup is a normal closure too. Rearm only local wake
      // listening after three closed observations; never start another Voice.
      const normal=!dictOpen() && composers().length===1 && !blocked();
      const message={cmd:'voice-ended',token,userEnded:normal,
                     detail:normal?'voice-ended':blocked()?'browser-notice':'voice-ended-unexpectedly'};
      stopWatching();
      chrome.runtime.sendMessage(message).catch(()=>{});
    },750);
    state.watch=watchState;
  }
  async function voiceReady(token) {
    let stable=0;
    for(let n=0;n<160;n++) {
      if(!state.watch||state.watch.token!==token)return {state:'BLOCKED',detail:'voice-not-ready'};
      if(location.origin!=='https://chatgpt.com'||blocked())return {state:'BLOCKED',detail:'browser-notice'};
      queryEvents();
      await new Promise(resolve=>setTimeout(resolve,250));
      const events=state.events;
      const unmuted=buttons(['Turn off microphone','Tắt micrô','Tắt micro']).some(el=>!el.disabled);
      stable=voiceOpen()&&unmuted&&events?.connected&&events.microphone_ready&&
        Date.now()-events.received<1500?stable+1:0;
      if(stable>=2)return {state:'VOICE_READY'};
    }
    return {state:'BLOCKED',detail:'voice-not-ready'};
  }
  globalThis.heyGPT=async function(action,mode='voice',token='',options={}) {
    if(action==='voice-ready')return voiceReady(token);
    if(action==='turn-status')return {ui_state:turnStatus()};
    if(action==='recovery-inspect')return recoveryInspect();
    if(action==='ready')return readyStable();
    if((action==='start'||action==='attach') && mode==='voice' &&
       location.origin==='https://chatgpt.com' && !blocked() && voiceOpen()) {
      watch(token);
      return {state:'BROWSER_VOICE',detail:'voice-already-open-attached'};
    }
    if(action==='attach')return {state:'BLOCKED',detail:blocked()?'browser-notice':'voice-not-open'};
    if(action==='stop-idle'||action==='stop-command') {
      const watchState=state.watch;
      if(!watchState||watchState.token!==token)return {state:'STOP_VETOED'};
      const prior=state.events,nonce=queryEvents();
      if(nonce){
        for(let n=0;n<8&&state.events===prior;n++)await new Promise(resolve=>setTimeout(resolve,125));
        if(state.events===prior)return {state:'STOP_VETOED'};
      }
      if(state.watch!==watchState||playbackStatus()!=='quiet')return {state:'STOP_VETOED'};
      if(action==='stop-idle'){
        const seconds=Number.isFinite(options.idleSeconds)?Math.max(1,Math.min(3600,options.idleSeconds)):15;
        if(turnStatus()!=='idle'||watchState.idleSince==null||Date.now()-watchState.idleSince<seconds*1000)
          return {state:'STOP_VETOED'};
      }
      action='stop';
    }
    if (action==='stop') {
      stopWatching();
      const end=buttons(endLabels);
      if (end.length===1) {
        end[0].click();
        return closedStable();
      }
      if(!dictOpen())return closedStable();
      return {state:dictOpen()?'NEEDS_CLICK':'STOPPED',detail:dictOpen()?'stop-dictation-in-chatgpt':'no-voice-open',closed:false};
    }
    if (action==='unwatch') {stopWatching();return {state:'STOPPED'};}
    const check=inspect(mode),{button,...publicCheck}=check;
    if (action==='inspect' || check.state!=='READY') return publicCheck;
    if (action!=='start') return {state:'BLOCKED',detail:'unsupported-action'};
    button.click(); // Once only. This does not manufacture trusted user activation.
    for (let n=0;n<32;n++) {
      await new Promise(resolve=>setTimeout(resolve,250));
      if (blocked()) return {state:'NEEDS_CLICK',detail:'browser-notice'};
      if (mode==='voice' && voiceOpen()) {watch(token);return {state:'BROWSER_VOICE',detail:'voice-ui-open'};}
      if (mode==='dictate' && dictOpen()) return {state:'BROWSER_DICTATION',detail:'dictation-ui-open'};
    }
    return {state:'NEEDS_CLICK',detail:'review-browser-permission-limit-or-start-button'};
  };
})();
