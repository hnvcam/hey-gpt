const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/voice-events.js'),'utf8');
function setup(){
 class Events {constructor(){this.listeners={};}addEventListener(name,fn){(this.listeners[name]||=[]).push(fn);}emit(name,value={}){for(const fn of this.listeners[name]||[])fn(value);}}
 class Channel extends Events {constructor(){super();this.readyState='open';}send(...args){this.sent=(this.sent||[]).concat([args]);return 'forwarded';}}
 class Peer extends Events {constructor(){super();this.connectionState='connected';}createDataChannel(){return new Channel();}}
 const win=new Events(),sent=[];win.RTCPeerConnection=Peer;win.RTCDataChannel=Channel;
 const cachedChannel=new Channel();
 win.postMessage=data=>sent.push(data);
 const ctx={window:win,location:{origin:'https://chatgpt.com'},Date,Reflect,Proxy,Set,WeakSet,JSON};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 const pc=new win.RTCPeerConnection(),ch=pc.createDataChannel('existing');
 return {pc,ch,win,cachedChannel,query:()=>{win.emit('message',{source:win,origin:ctx.location.origin,data:{kind:'hey-gpt-query-voice-events',nonce:'query'}});return sent.at(-1);},
  event:e=>ch.emit('message',{data:JSON.stringify(e)})};
}
test('no event or unknown protocol is unknown; connected and quiet never implies idle',()=>{
 const f=setup();assert.equal(f.query().ui_state,'unknown');f.event({type:'unknown',text:'private transcript'});
 assert.equal(f.query().ui_state,'unknown');assert.equal(JSON.stringify(f.query()).includes('private'),false);
});
test('server actor listening is insufficient; user speech holds busy until server listens',()=>{
 const f=setup();f.event({actor:'CHATGPT_VOICE_ACTOR_ASSISTANT',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal(f.query().ui_state,'unknown');f.event({actor:'CHATGPT_VOICE_ACTOR_USER',state:'CHATGPT_VOICE_ACTOR_STATE_SPEAKING'});
 assert.equal(f.query().ui_state,'busy');f.event({actor:'CHATGPT_VOICE_ACTOR_USER',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal(f.query().ui_state,'busy');f.event({actor:'CHATGPT_VOICE_ACTOR_ASSISTANT',state:'CHATGPT_VOICE_ACTOR_STATE_LISTENING'});
 assert.equal(f.query().ui_state,'unknown');
});
test('long response, generation done, and encoded audio done stay busy until playback stop',()=>{
 const f=setup();f.event({type:'response.created',response:{id:'turn-one'}});
 f.event({type:'response.audio.delta',delta:'secret audio'});
 f.event({type:'response.done',response:{status:'completed'}});
 f.event({type:'response.audio.done'});assert.equal(f.query().ui_state,'busy');
 f.event({type:'output_audio_buffer.stopped',response_id:'turn-one'});
 assert.equal(f.query().ui_state,'idle');assert.equal(JSON.stringify(f.query()).includes('secret'),false);
});
test('completion for an old response cannot idle the next response or a speaking user',()=>{
 const f=setup();f.event({type:'response.created',response:{id:'new'}});
 f.event({type:'output_audio_buffer.stopped',response_id:'old'});assert.equal(f.query().ui_state,'busy');
 f.event({type:'input_audio_buffer.speech_started'});
 f.event({type:'output_audio_buffer.stopped',response_id:'new'});assert.equal(f.query().ui_state,'busy');
});
test('failed, ambiguous peers, and closed/disconnected channels never establish idle',()=>{
 const f=setup();f.event({type:'output_audio_buffer.stopped'});assert.equal(f.query().ui_state,'idle');
 f.ch.readyState='closed';assert.equal(f.query().ui_state,'unknown');f.ch.readyState='open';
 f.event({type:'error'});assert.equal(f.query().ui_state,'unknown');assert.equal(f.query().connected,false);
 const pc=new f.win.RTCPeerConnection();pc.createDataChannel('another');assert.equal(f.query().ui_state,'unknown');
});
test('remote channels are observed without creating channels or changing site messages',()=>{
 const f=setup();const remote=new f.ch.constructor();f.pc.emit('datachannel',{channel:remote});
 remote.emit('message',{data:JSON.stringify({type:'output_audio_buffer.stopped'})});
 assert.equal(f.query().ui_state,'idle');remote.emit('message',{data:new Uint8Array([1,2,3])});
 assert.equal(f.query().event_count,1);
});

function frame(type,payload){return {type:'data_message',data:JSON.stringify({type,payload})};}
test('actual transceiver envelope listening/processing/speaking drives state; model config never establishes idle',()=>{
 const f=setup();f.event(frame('thinking_update',{type:'thinking_update',enabled:false}));
 assert.equal(f.query().ui_state,'unknown');f.event(frame('session_bootstrap',{model_picker:'toggle'}));
 assert.equal(f.query().ui_state,'unknown');f.event(frame('state_update',{new_state:'listening'}));
 assert.equal(f.query().ui_state,'unknown');
 for(const state of ['thinking','speaking','listening_intently']){
  f.event(frame('state_update',{new_state:state}));assert.equal(f.query().ui_state,'busy');
  f.event(frame('thinking_update',{enabled:false}));assert.equal(f.query().ui_state,'busy');
 }
 f.event(frame('state_update',{new_state:'listening'}));assert.equal(f.query().ui_state,'unknown');
 assert.ok(f.query().event_types.includes('state_update.listening'));
});
test('server listening and metadata alone never prove playback completion',()=>{
 const f=setup();f.event(frame('state_update',{new_state:'listening'}));
 for(const type of ['streaming_message_update','speaking_update','startup_telemetry'])f.event(frame(type,{}));
 assert.equal(f.query().ui_state,'unknown');
});

test('cached channels attach on site send and preserve original send exactly once',()=>{
 const f=setup();f.pc.connectionState='closed';
 assert.equal(f.cachedChannel.sent,undefined);
 assert.equal(f.cachedChannel.send('site-ping'),'forwarded');
 assert.deepEqual(f.cachedChannel.sent,[['site-ping']]);
 f.cachedChannel.emit('message',{data:JSON.stringify(frame('state_update',{new_state:'listening'}))});
 assert.equal(f.query().ui_state,'unknown');assert.equal(f.cachedChannel.sent.length,1);
});
