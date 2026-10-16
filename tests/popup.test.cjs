const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../extension/popup.js'),'utf8');
function fixture(){
 const elements=new Map(),timers=new Map(),calls=[];let next=0,poll;
 const context={document:{getElementById:id=>{if(!elements.has(id))elements.set(id,{value:'voice',style:{}});return elements.get(id);}},
   chrome:{runtime:{getManifest:()=>({version:'0.6.0'}),sendMessage:message=>new Promise(resolve=>calls.push({message,resolve}))}},
   setInterval:fn=>{poll=fn;},setTimeout:(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id)};
 vm.createContext(context);vm.runInContext(source,context);
 return {calls,elements,poll:()=>poll(),timeout:()=>{for(const t of [...timers.values()])t.fn();},run:s=>vm.runInContext(s,context)};
}
test('slow popup request never piles up polling; timeout shows an error and explicit arm can retry',async()=>{
 const f=fixture();for(let i=0;i<50;i++)f.poll();assert.equal(f.calls.length,1);
 f.timeout();await new Promise(resolve=>setImmediate(resolve));
 assert.match(f.elements.get('status').textContent,/quá lâu/);f.poll();assert.equal(f.calls.length,1);
 const retry=f.run("update('arm')");assert.equal(f.calls.length,2);
 f.calls[1].resolve({ok:false,error:'native-connect-timeout'});await retry;
 assert.match(f.elements.get('status').textContent,/5 giây/);
});
