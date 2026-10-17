const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/voice-events.js'),'utf8');
function setup(){
 class Events {constructor(){this.listeners={};}addEventListener(name,fn){(this.listeners[name]||=[]).push(fn);}emit(name,value={}){return Promise.all((this.listeners[name]||[]).map(fn=>fn(value)));}}
 class Channel extends Events {constructor(){super();this.readyState='open';}send(...args){this.sent=(this.sent||[]).concat([args]);return 'forwarded';}}
 class Peer extends Events {constructor(){super();this.connectionState='connected';this.track={kind:'audio',readyState:'live',enabled:true,muted:false};}getSenders(){return [{track:this.track}];}createDataChannel(){return new Channel();}}
 const win=new Events(),sent=[];win.RTCPeerConnection=Peer;win.RTCDataChannel=Channel;
 const cachedChannel=new Channel();
 win.postMessage=data=>sent.push(data);
 let now=Date.now();class TestDate extends Date {static now(){return now;}}
 const ctx={heyGPTPlaybackTracker:require('../extension/playback.js'),window:win,location:{origin:'https://chatgpt.com'},Date:TestDate,Reflect,Proxy,Set,WeakSet,JSON};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const pc=new win.RTCPeerConnection(),ch=pc.createDataChannel('existing');
 return {pc,ch,win,cachedChannel,advance:ms=>{now+=ms;},now:()=>now,reload:()=>vm.runInContext(source,ctx),query:async()=>{await win.emit('message',{source:win,origin:ctx.location.origin,data:{kind:'hey-gpt-query-voice-events',nonce:'query'}});return sent.at(-1);},
  event:e=>ch.emit('message',{data:JSON.stringify(e)})};
}
test('no event or unknown protocol is unknown; connected and quiet never implies idle',async()=>{
 const f=setup();assert.equal((await f.query()).ui_state,'unknown');f.event({type:'unknown',text:'private transcript'});
 assert.equal((await f.query()).ui_state,'unknown');assert.equal(JSON.stringify((await f.query())).includes('private'),false);
});
test('server actor listening is insufficient; user speech holds busy until server listens',async()=>{
 const f=setup();f.event({actor:'CHATGPT_VOICE_ACTOR_ASSISTANT',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal((await f.query()).ui_state,'unknown');f.event({actor:'CHATGPT_VOICE_ACTOR_USER',state:'CHATGPT_VOICE_ACTOR_STATE_SPEAKING'});
 assert.equal((await f.query()).ui_state,'busy');f.event({actor:'CHATGPT_VOICE_ACTOR_USER',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal((await f.query()).ui_state,'busy');f.event({actor:'CHATGPT_VOICE_ACTOR_ASSISTANT',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal((await f.query()).ui_state,'unknown');
});
test('long response, generation done, and encoded audio done stay busy until playback stop',async()=>{
 const f=setup();f.event({type:'response.created',response:{id:'turn-one'}});
 f.event({type:'response.audio.delta',delta:'secret audio'});
 f.event({type:'response.done',response:{status:'completed'}});
 f.event({type:'response.audio.done'});assert.equal((await f.query()).ui_state,'busy');
 f.event({type:'output_audio_buffer.stopped',response_id:'turn-one'});
 assert.equal((await f.query()).ui_state,'idle');assert.equal(JSON.stringify((await f.query())).includes('secret'),false);
});
test('completion for an old response cannot idle the next response or a speaking user',async()=>{
 const f=setup();f.event({type:'response.created',response:{id:'new'}});
 f.event({type:'output_audio_buffer.stopped',response_id:'old'});assert.equal((await f.query()).ui_state,'busy');
 f.event({type:'input_audio_buffer.speech_started'});
 f.event({type:'output_audio_buffer.stopped',response_id:'new'});assert.equal((await f.query()).ui_state,'busy');
});
test('failed, ambiguous peers, and closed/disconnected channels never establish idle',async()=>{
 const f=setup();f.event({type:'output_audio_buffer.stopped'});assert.equal((await f.query()).ui_state,'idle');
 f.ch.readyState='closed';assert.equal((await f.query()).ui_state,'unknown');f.ch.readyState='open';
 f.event({type:'error'});assert.equal((await f.query()).ui_state,'unknown');assert.equal((await f.query()).connected,false);
 const pc=new f.win.RTCPeerConnection();pc.createDataChannel('another');assert.equal((await f.query()).ui_state,'unknown');
});
test('remote channels are observed without creating channels or changing site messages',async()=>{
 const f=setup();const remote=new f.ch.constructor();f.pc.emit('datachannel',{channel:remote});
 remote.emit('message',{data:JSON.stringify({type:'output_audio_buffer.stopped'})});
 assert.equal((await f.query()).ui_state,'idle');remote.emit('message',{data:new Uint8Array([1,2,3])});
 assert.equal((await f.query()).event_count,1);
});

function frame(type,payload){return {type:'data_message',data:JSON.stringify({type,payload})};}
test('actual transceiver envelope listening/processing/speaking drives state; model config never establishes idle',async()=>{
 const f=setup();f.event(frame('thinking_update',{type:'thinking_update',enabled:false}));
 assert.equal((await f.query()).ui_state,'unknown');f.event(frame('session_bootstrap',{model_picker:'toggle'}));
 assert.equal((await f.query()).ui_state,'unknown');f.event(frame('state_update',{new_state:'listening'}));
 assert.equal((await f.query()).ui_state,'unknown');
 for(const state of ['thinking','speaking','listening_intently']){
  f.event(frame('state_update',{new_state:state}));assert.equal((await f.query()).ui_state,'busy');
  f.event(frame('thinking_update',{enabled:false}));assert.equal((await f.query()).ui_state,'busy');
 }
 f.event(frame('state_update',{new_state:'listening'}));assert.equal((await f.query()).ui_state,'unknown');
 assert.ok((await f.query()).event_types.includes('state_update.listening'));
});
test('server listening and metadata alone never prove playback completion',async()=>{
 const f=setup();f.event(frame('state_update',{new_state:'listening'}));
 for(const type of ['streaming_message_update','speaking_update','startup_telemetry'])f.event(frame(type,{}));
 assert.equal((await f.query()).ui_state,'unknown');
});

test('cached channels attach on site send and preserve original send exactly once',async()=>{
 const f=setup();f.pc.connectionState='closed';
 assert.equal(f.cachedChannel.sent,undefined);
 assert.equal(f.cachedChannel.send('site-ping'),'forwarded');
 assert.deepEqual(f.cachedChannel.sent,[['site-ping']]);
 f.cachedChannel.emit('message',{data:JSON.stringify(frame('state_update',{new_state:'listening'}))});
 assert.equal((await f.query()).ui_state,'unknown');assert.equal(f.cachedChannel.sent.length,1);
});

test('readiness waits for server listening plus an enabled live outgoing microphone',async()=>{
 const f=setup();assert.equal((await f.query()).microphone_ready,false);
 f.event(frame('state_update',{new_state:'listening'}));assert.equal((await f.query()).microphone_ready,true);
 assert.equal((await f.query()).ui_state,'unknown'); // Never confuse readiness with reply completion.
 for(const [field,value] of [['enabled',false],['muted',true],['readyState','ended']]){
  const before=f.pc.track[field];f.pc.track[field]=value;
  assert.equal((await f.query()).microphone_ready,false);f.pc.track[field]=before;
 }
 f.pc.connectionState='connecting';assert.equal((await f.query()).microphone_ready,false);
 f.pc.connectionState='connected';f.event(frame('state_update',{new_state:'thinking'}));
 assert.equal((await f.query()).microphone_ready,false);
 f.event(frame('state_update',{new_state:'listening'}));f.event({type:'error'});
 assert.equal((await f.query()).microphone_ready,false);
});
test('cached channel fallback cannot claim microphone readiness without a real sender',async()=>{
 const f=setup();f.pc.connectionState='closed';f.cachedChannel.send('ping');
 f.cachedChannel.emit('message',{data:JSON.stringify(frame('state_update',{new_state:'listening'}))});
 assert.equal((await f.query()).microphone_ready,false);
});

test('browser counter activity crosses the observer without forwarding private stats',async()=>{
 const f=setup();let energy=0,duration=0,packets=0;
 f.pc.getStats=async()=>new Map([['audio',{id:'audio',type:'inbound-rtp',kind:'audio',timestamp:f.now(),
  totalAudioEnergy:energy,totalSamplesDuration:duration,packetsReceived:packets,
  jitterBufferDelay:duration*48000*.1,jitterBufferEmittedCount:duration*48000,
  remoteAddress:'private-address'}]]);
 await f.query();
 f.advance(750);duration+=.75;energy+=.001;packets++;
 assert.equal((await f.query()).playback_state,'busy');
 for(let i=0;i<3;i++){f.advance(750);duration+=.75;packets++;await f.query();}
 const result=await f.query(); // Same browser timestamp is unverified, never stale quiet.
 assert.equal(result.playback_state,'unknown');
 assert.equal(JSON.stringify(result).includes('private-address'),false);
});
test('concurrent readiness and close checks await the same in-flight browser sample',async()=>{
 const f=setup();let release,calls=0;
 f.pc.getStats=()=>{calls++;return new Promise(resolve=>{release=resolve;});};
 const first=f.query(),second=f.query();
 assert.equal(calls,1);release(new Map());
 await Promise.all([first,second]);
 f.reload();assert.equal(f.win.listeners.message.length,1);
});
