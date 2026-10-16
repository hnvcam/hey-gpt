const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/background.js'),'utf8');
function fixture(){
 let next=0,clock=0;const timers=new Map(),ports=[];
 const event=()=>({callbacks:[],addListener(fn){this.callbacks.push(fn);},emit(x){for(const fn of this.callbacks)fn(x);}});
 const chrome={runtime:{getManifest:()=>({version:'0.6.0'}),onMessage:event(),id:'test',getURL:s=>'extension://test/'+s,
   connectNative:()=>{const p={onMessage:event(),onDisconnect:event(),disconnect(){this.onDisconnect.emit();},postMessage(){throw Error('disconnected');}};ports.push(p);return p;}},
   action:{setBadgeText:async()=>{},setBadgeBackgroundColor:async()=>{}},tabs:{onRemoved:event(),onUpdated:event()},idle:{onStateChanged:event()}};
 const ctx={chrome,crypto:require('node:crypto').webcrypto,URL,Date,setTimeout:(fn,ms)=>{const id=++next;timers.set(id,{fn,due:clock+ms});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(ctx);vm.runInContext(source,ctx);
 return {ports,run:s=>vm.runInContext(s,ctx),advance:ms=>{clock+=ms;for(const [id,t] of [...timers])if(t.due<=clock){timers.delete(id);t.fn();}}};
}
test('missing initial status is bounded and clears the native port, without connecting Voice',async()=>{
 const f=fixture();const ready=f.run('connect()');const rejected=assert.rejects(ready,/native-connect-timeout/);
 f.advance(5000);await rejected;assert.equal(f.run('port'),null);assert.equal(f.run('enabled'),false);
 const again=f.run('connect()');f.ports[1].onMessage.emit({type:'status',state:'DISARMED',enabled:false});await again;
 assert.equal(f.ports.length,2);
});
test('an early native-host error settles connect immediately rather than waiting forever',async()=>{
 const f=fixture();const ready=f.run('connect()');const rejected=assert.rejects(ready,/service-unavailable/);
 f.ports[0].onMessage.emit({type:'error',detail:'service-unavailable'});await rejected;
 assert.equal(f.run('port'),null);
});
test('a late disconnect from the expired port cannot break a newer connection',async()=>{
 const f=fixture();const old=f.run('connect()');const rejected=assert.rejects(old);f.advance(5000);await rejected;
 const fresh=f.run('connect()');f.ports[1].onMessage.emit({type:'status',state:'DISARMED'});await fresh;
 f.ports[0].onDisconnect.emit();assert.equal(f.run('port!==null'),true);
});
test('postMessage failure rejects the waiting command and removes its timeout',async()=>{
 const f=fixture();const connection=f.run('connect()');f.ports[0].onMessage.emit({type:'status',state:'DISARMED'});await connection;
 await assert.rejects(f.run("request('status')"),/disconnected/);assert.equal(f.run('pending.size'),0);
});
