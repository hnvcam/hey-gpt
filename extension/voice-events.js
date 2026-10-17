/* Passive observer of the site's existing WebRTC data channels. No requests,
   audio capture, SDP, tokens, transcripts, or payloads are saved or forwarded. */
(() => {
  if(location.origin!=='https://chatgpt.com')return;
  const shared=window.heyGPTVoiceObserver ||= {peers:new Set(),channels:new WeakSet(),sequence:0,hooked:false};
  const peers=shared.peers,channels=shared.channels;
  const cleanKind = value => typeof value==='string'&&/^[a-zA-Z0-9_.:-]{1,80}$/.test(value)?value.toLowerCase().replace(/[:-]/g,'_'):'unrecognized';
  function traceShape(event) {
    const values=[],keys=[];
    function walk(value,path,depth){
      if(!value||typeof value!=='object'||Array.isArray(value)||depth>2)return;
      for(const [key,item] of Object.entries(value)){
        if(!/^[a-zA-Z0-9_]{1,32}$/.test(key))continue;
        const at=path?path+'.'+key:key;
        keys.push('keys.'+at.toLowerCase());
        if(['type','event_type','kind','state','new_state','actor','event','t','status','name'].includes(key)){
          const kind=cleanKind(item);if(kind!=='unrecognized')values.push((at.toLowerCase()+'.'+kind).slice(0,80));
        }
        if(depth<2&&!['text','transcript','audio','delta','arguments','content'].includes(key))walk(item,at,depth+1);
      }
    }
    walk(event,'',0);return [...keys.slice(0,4),...values.slice(0,4)];
  }
  function receive(peer, data) {
    if (typeof data !== 'string' || data.length > 262144) return;
    let event; try { event = JSON.parse(data); } catch { return; }
    if (!event || typeof event !== 'object' || Array.isArray(event)) return;
    let format='format.object';
    for(let layer=0;layer<3&&event?.type==='data_message';layer++) {
      let inner=event.data;
      if(typeof inner==='string') {
        format='format.string';
        if(!/^[\s]*[\[{]/.test(inner)) {
          if(/^[A-Za-z0-9+/=\s]+$/.test(inner)) {
            try {inner=atob(inner);format='format.base64';}catch{}
          }
        }
        try{inner=JSON.parse(inner);}catch{format+='.opaque';break;}
      }
      if(!inner||typeof inner!=='object'||Array.isArray(inner))break;
      event=inner;
    }
    const type = event.type || event.event_type;
    const kind = cleanKind(type);
    const shape=[format,...traceShape(event)].slice(-8);
    const flags=[];
    if(type==='state_update'&&typeof event.payload?.new_state==='string')flags.push(cleanKind(event.payload.new_state));
    for(const candidate of [event,event.payload])if(candidate&&typeof candidate==='object'){
      for(const key of ['enabled','active','speaking','thinking','is_speaking','is_thinking','done'])
        if(typeof candidate[key]==='boolean')flags.push(key+'_'+String(candidate[key]));
    }
    const descriptor=kind+(flags.length?'.'+[...new Set(flags)].join('.'):'');
    peer.kinds=[...peer.kinds.filter(x=>x!==descriptor),descriptor.slice(0,80)].slice(-8);
    if(kind==='unrecognized')peer.kinds=[...peer.kinds,...shape.slice(-3)].slice(-8);
    peer.count++; peer.lastEvent = Date.now();
    // Verified against the site's loaded transceiver/voice message handler.
    // thinking_update configures model selection; it is not a busy signal.
    if(type==='state_update') {
      const remote=event.payload?.new_state;
      if(remote==='listening') {
        // Server readiness does not prove that Chrome finished buffered speech.
        peer.listening=true;peer.known=false;peer.busy=false;peer.userSpeaking=false;peer.error=false;
      } else if(['thinking','speaking','listening_intently'].includes(remote)) {
        peer.listening=false;peer.known=true;peer.busy=true;peer.turnSeen=true;
      } else {peer.known=false;peer.busy=false;}
    }
    if(type==='tool_update'&&event.payload?.update_type==='hangup') {
      peer.busy=true;peer.turnSeen=true;
    }
    // These strings are observed in the supplied HAR's actor-state schema.
    // Their presence on a live data channel is verified separately at runtime.
    const state = event.state, actor = event.actor;
    if (actor === 'CHATGPT_VOICE_ACTOR_ASSISTANT') {
      if (state === 'CHATGPT_VOICE_ACTOR_STATE_LISTENING') {
        peer.listening = true; peer.known = false; peer.busy = peer.userSpeaking;
        peer.awaiting = false; peer.error = false;
      } else if (['CHATGPT_VOICE_ACTOR_STATE_THINKING', 'CHATGPT_VOICE_ACTOR_STATE_SPEAKING'].includes(state)) {
        peer.listening = false; peer.known = true; peer.busy = true;
      }
    }
    if (actor === 'CHATGPT_VOICE_ACTOR_USER') {
      if (state === 'CHATGPT_VOICE_ACTOR_STATE_SPEAKING') {
        peer.turnSeen=true;peer.userSpeaking = true; peer.awaiting = true; peer.busy = true;
      } else if (state === 'CHATGPT_VOICE_ACTOR_STATE_LISTENING') peer.userSpeaking = false;
    }
    if (type === 'input_audio_buffer.speech_started') { peer.turnSeen=true;peer.userSpeaking = true; peer.awaiting = true; }
    if (type === 'input_audio_buffer.speech_stopped') peer.userSpeaking = false;
    if (type === 'response.created') {
      peer.awaiting = false;
      peer.response = typeof event.response?.id === 'string' ? event.response.id : null;
    }
    if (['input_audio_buffer.speech_started', 'input_audio_buffer.speech_stopped',
         'input_audio_buffer.committed', 'response.created', 'response.in_progress'].includes(type)) peer.busy = true;
    if (['output_audio_buffer.started', 'response.audio.delta', 'response.output_audio.delta'].includes(type)) {
      peer.busy = true; peer.playing = true;
    }
    // Generation completion is not proof that buffered speech finished playing.
    if (['response.done', 'response.audio.done', 'response.output_audio.done'].includes(type)) peer.busy = true;
    if (type === 'output_audio_buffer.stopped' &&
        (!peer.response || event.response_id === peer.response)) {
      peer.known = true; peer.busy = peer.userSpeaking || peer.awaiting; peer.playing = false;
    }
    if (type === 'output_audio_buffer.cleared') {
      peer.known = false; peer.busy = true; peer.playing = false;
    }
    if (type === 'error' || (type === 'response.done' &&
        ['failed','incomplete'].includes(event.response?.status))) {
      peer.error = true; peer.known = false;
    }
  }
  function attachChannel(peer, channel) {
    if (channels.has(channel)) return;
    channels.add(channel); peer.channels.add(channel);
    channel.addEventListener('message', event => shared.receive(peer, event.data));
    channel.addEventListener('error', () => { peer.error = true; peer.known = false; });
  }
  async function samplePlayback(peer) {
    if(peer.sampling)return peer.sampling;
    if(typeof peer.connection.getStats!=='function'||
       typeof globalThis.heyGPTPlaybackTracker!=='function')return;
    peer.playback ||= new globalThis.heyGPTPlaybackTracker();
    const sampling=(async()=>{try {
      const report=await peer.connection.getStats();
      const audio=[];
      for(const row of report.values())if(row.type==='inbound-rtp'&&
        (row.kind==='audio'||row.mediaType==='audio'))audio.push(row);
      peer.playback.update(audio.length===1?audio[0]:null,Date.now());
    } catch {peer.playback.reset();}
    })();
    peer.sampling=sampling;
    try{await sampling;}finally{if(peer.sampling===sampling)peer.sampling=null;}
  }
  function observePeer(connection) {
    let peer=[...peers].find(p=>p.connection===connection);
    if(peer)return peer;
    peer={connection,id:++shared.sequence,channels:new Set(),known:false,busy:false,playing:false,
      userSpeaking:false,awaiting:false,response:null,error:false,count:0,lastEvent:0,kinds:[]};
    peers.add(peer);
    connection.addEventListener('datachannel',event=>attachChannel(peer,event.channel));
    connection.addEventListener('connectionstatechange',()=>{
      if(connection.connectionState==='failed'){peer.error=true;peer.known=false;}
      if(connection.connectionState==='closed')peers.delete(peer);
    });
    while(peers.size>8)peers.delete(peers.values().next().value);
    return peer;
  }
  shared.queryPlayback = async event => {
    if (event.source !== window || event.origin !== location.origin ||
        event.data?.kind !== 'hey-gpt-query-voice-events' ||
        typeof event.data.nonce !== 'string' || event.data.nonce.length > 80) return;
    const active = [...peers].filter(p => !['closed','failed','disconnected'].includes(p.connection.connectionState) &&
      [...p.channels].some(channel => channel.readyState === 'open'));
    const peer = active.length === 1 ? active[0] : null;
    if(peer)await samplePlayback(peer);
    const playback=peer&&!peer.error?peer.playback?.snapshot(Date.now()):null;
    const microphone_ready = Boolean(peer && !peer.error && peer.listening === true && !peer.busy &&
      peer.connection.connectionState === 'connected' &&
      typeof peer.connection.getSenders === 'function' && peer.connection.getSenders().some(sender =>
        sender.track?.kind === 'audio' && sender.track.readyState === 'live' &&
        sender.track.enabled === true && sender.track.muted === false));
    const ui_state = !peer || peer.error ? 'unknown' : peer.busy ? 'busy' : peer.known ? 'idle' : 'unknown';
    window.postMessage({kind:'hey-gpt-voice-events',observer_version:2, nonce:event.data.nonce, at:Date.now(),
      ui_state, microphone_ready, playback_state:playback?.state||'unknown',
      playback_quiet_ms:playback?.quiet_ms||0, connected:Boolean(peer&&!peer.error), supported:Boolean(peer?.known),
      event_count:peer?.count || 0, event_age_ms:peer?.lastEvent ? Math.max(0,Date.now()-peer.lastEvent) : null,
      event_types:peer?.kinds || ['active_peers.'+active.length,'total_peers.'+peers.size]}, location.origin);
  };
  if(!shared.queryListenerV2){
    shared.queryListenerV2=event=>shared.queryPlayback(event);
    window.addEventListener('message',shared.queryListenerV2);
  }
  shared.receive=receive;
  if(shared.hooked)return;
  shared.hooked=true;
  const NativeChannel=window.RTCDataChannel;
  if(typeof NativeChannel==='function'){
    const send=NativeChannel.prototype.send;
    NativeChannel.prototype.send=function(...args){
      if(!channels.has(this)){
        const channel=this;
        const connection={get connectionState(){return channel.readyState==='open'?'connected':'closed';},
          addEventListener:()=>{}};
        attachChannel(observePeer(connection),channel);
      }
      return Reflect.apply(send,this,args);
    };
  }
  const NativePeer = window.RTCPeerConnection;
  if (typeof NativePeer === 'function') {
    const create = NativePeer.prototype.createDataChannel;
    NativePeer.prototype.createDataChannel = function(...args) {
      const channel=Reflect.apply(create,this,args);
      attachChannel(observePeer(this),channel);
      return channel;
    };
    window.RTCPeerConnection = new Proxy(NativePeer, {
      construct(target,args,newTarget){
        const connection=Reflect.construct(target,args,newTarget);
        observePeer(connection);return connection;
      }
    });
  }
})();
