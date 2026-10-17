const {test}=require('node:test'),assert=require('node:assert/strict');
const Playback=require('../extension/playback.js');
function fixture(){
 const meter=new Playback();let now=100000,energy=0,duration=0,packets=0,emitted=0,delay=0;
 function sample({level=0,seconds=.75,stalled=false,bufferDelay=.1,id='audio'}={}){
  now+=seconds*1000;
  if(!stalled){duration+=seconds;energy+=level*level*seconds;packets++;emitted+=48000*seconds;delay+=48000*seconds*bufferDelay;}
  meter.update({id,timestamp:now,totalAudioEnergy:energy,totalSamplesDuration:duration,
                packetsReceived:packets,jitterBufferDelay:delay,jitterBufferEmittedCount:emitted,audioLevel:0},now);
  return meter.snapshot(now);
 }
 return {meter,sample,advance:ms=>{now+=ms;return meter.snapshot(now);},now:()=>now};
}
test('text completion cannot hide more than 15 seconds of remote speech',()=>{
 const f=fixture();f.sample();
 for(let second=0;second<60;second++)assert.equal(f.sample({level:.02}).state,'busy');
});
test('quiet requires advancing silent counters and a settling interval',()=>{
 const f=fixture();assert.equal(f.sample().state,'unknown');
 assert.equal(f.sample({level:.01}).state,'busy');
 assert.equal(f.sample().state,'unknown');assert.equal(f.sample().state,'unknown');
 assert.equal(f.sample().state,'quiet');
 assert.equal(f.sample({level:.0002}).state,'busy');
});
test('a brief sound between polls is detected even if instantaneous audioLevel is zero',()=>{
 const f=fixture();f.sample();assert.equal(f.sample({level:.002}).state,'busy');
});
test('network stalls, delayed polling, missing counters and ambiguous streams are unknown',()=>{
 const f=fixture();for(let i=0;i<4;i++)f.sample();assert.equal(f.meter.snapshot(f.now()).state,'quiet');
 assert.equal(f.sample({stalled:true}).state,'unknown');
 for(let i=0;i<4;i++)f.sample();assert.equal(f.advance(3000).state,'unknown');
 assert.equal(f.sample().state,'unknown');
 f.meter.update(null,f.now());assert.equal(f.meter.snapshot(f.now()).state,'unknown');
});
test('large jitter buffers and a changed stream cannot establish immediate quiet',()=>{
 const f=fixture();f.sample();assert.equal(f.sample({bufferDelay:2}).state,'busy');
 assert.equal(f.sample({id:'new-stream'}).state,'unknown');
});
test('counter rollback, stale browser timestamps and unsupported metrics fail closed',()=>{
 const f=fixture();for(let i=0;i<4;i++)f.sample();
 f.meter.update({id:'audio',timestamp:f.now()-4000},f.now());
 assert.equal(f.meter.snapshot(f.now()).state,'unknown');
});
