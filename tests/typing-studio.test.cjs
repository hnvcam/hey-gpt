const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';}
  append(...nodes){for(const node of nodes){node.parentElement=this;this.children.push(node);}}
  replaceChildren(){this.children=[];}
  querySelectorAll(tag){return this.children.flatMap(node=>[...(node.tag===tag?[node]:[]),...node.querySelectorAll(tag)]);}
}
function view(report){
  const result=new Element('div'),saved=new Element('td');new Element('tr').append(saved);
  const elements={result,saved20:saved};
  const context=vm.createContext({document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag)}});
  const html=fs.readFileSync(path.join(__dirname,'../tools/typing_studio.html'),'utf8');
  vm.runInContext(html.split('<script>')[1].split('async function poll()')[0],context);
  const clicks=[];context.act=(route,data)=>clicks.push({route,data});
  context.feedback({plan:[{id:'20',text:'end typing'}],completed:['20'],report},false);
  return {result,saved,clicks};
}
test('capture problem names the exact item and retries only that recording',()=>{
  const v=view({installed:false,summary:{},issues:[{prompt:'20',phrase:'end typing',take:4,category:'recording',reason:'No sound was captured.',retry_recommended:true}]});
  assert.equal(v.result.querySelectorAll('h3')[0].textContent,'Item 20 · end typing · take 4');
  assert.equal(v.result.querySelectorAll('p')[0].textContent,'No sound was captured.');
  const button=v.result.querySelectorAll('button')[0];assert.equal(button.textContent,'Retry item 20');button.onclick();
  assert.equal(v.clicks[0].route,'record');assert.equal(v.clicks[0].data.selection,'20');
  assert.equal(v.saved.parentElement.className,'needs-retake');
});
test('recognizer miss preserves the recording without demanding a retake',()=>{
  const v=view({installed:false,summary:{},issues:[{prompt:'20',phrase:'end typing',take:4,category:'recognizer',reason:'The agent missed this recording.',retry_recommended:false}]});
  assert.equal(v.result.querySelectorAll('button').length,0);
  assert.equal(v.saved.textContent,'Audio kept · agent needs adjustment');
  assert.equal(v.result.querySelectorAll('h3')[0].textContent,'Item 20 · end typing · take 4');
});
test('legacy generic failed report is treated as recognition feedback',()=>{
  const v=view({installed:false,summary:{},rows:[{prompt:'20',phrase:'end typing',passed:false}]});
  assert.equal(v.result.querySelectorAll('button').length,0);
  assert.match(v.result.querySelectorAll('p')[0].textContent,/No retake is required/);
});
