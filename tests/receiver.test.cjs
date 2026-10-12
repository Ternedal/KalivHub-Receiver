// Node built-in test runner. No dependencies.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'..','index.html'),'utf8');
const script=html.match(/<script>\s*([\s\S]*?)<\/script>\s*<\/body>/)?.[1];
assert.ok(script,'inline receiver script must exist');
function setup(){
 const elements=new Map();
 function node(){return {textContent:'',className:'',children:[],classList:{add(){},remove(){}},append(...xs){this.children.push(...xs)},replaceChildren(...xs){this.children=xs},onclick:null};}
 const get=id=>{if(!elements.has(id))elements.set(id,node());return elements.get(id)};
 let listener;let time=1000;let interval;
 const ctx={document:{getElementById:get,createElement:()=>node()},cast:{framework:{CastReceiverContext:{getInstance:()=>({addCustomMessageListener(ns,fn){assert.equal(ns,'urn:x-cast:dk.kalivhub.lab');listener=fn},start(){}})}}},Date:class extends Date{constructor(...args){super(...(args.length?args:[time]))}static now(){return time}},setInterval:fn=>{interval=fn},console};
 ctx.window=ctx;
 vm.runInNewContext(script,ctx,{timeout:1000});
 return {send:data=>listener({data}),get,advance:ms=>{time+=ms;vm.runInNewContext('void 0',ctx)},tick:()=>interval()};
}
test('valid snapshot displays text and rejects duplicate entities',()=>{
 const x=setup();x.send({type:'snapshot',version:1,session_id:'session_a1',sequence:0,entities:[{entity_id:'light.stue',name:'Stue',state:'on'}]});
 assert.match(x.get('connection').textContent,/1 enheder/);
 assert.equal(x.get('tiles').children.length,1);
 x.send({type:'snapshot',version:1,session_id:'session_a1',sequence:1,entities:[{entity_id:'light.stue',name:'A',state:'on'},{entity_id:'light.stue',name:'B',state:'off'}]});
 assert.equal(x.get('tiles').children.length,1);
});
test('sequence replay, live session change, malformed fields are rejected',()=>{
 const x=setup(),entity={entity_id:'light.stue',name:'Stue',state:'on'};
 x.send({type:'snapshot',version:1,session_id:'session_a1',sequence:5,entities:[entity]});
 x.send({type:'snapshot',version:1,session_id:'session_a1',sequence:4,entities:[]});
 assert.equal(x.get('tiles').children.length,1);
 x.send({type:'snapshot',version:1,session_id:'session_b2',sequence:0,entities:[]});
 assert.equal(x.get('tiles').children.length,1);
 x.send({type:'snapshot',version:1,session_id:'session_a1',entities:[]});
 assert.equal(x.get('tiles').children.length,1);
 x.send({type:'snapshot',version:1,entities:[]});
 assert.equal(x.get('tiles').children.length,1);
 x.send({type:'snapshot',version:2,entities:[]});
 assert.equal(x.get('tiles').children.length,1);
});
test('HTML-like names are treated as text, never markup',()=>{
 const x=setup();x.send({type:'snapshot',version:1,entities:[{entity_id:'light.stue',name:'<img src=x onerror=alert(1)>',state:'on'}]});
 assert.equal(x.get('tiles').children[0].children[0].textContent,'<img src=x onerror=alert(1)>');
});

test('stale snapshots expire, then a new sender session is accepted',()=>{
 const x=setup(),entity={entity_id:'light.stue',name:'Stue',state:'on'};
 x.send({type:'snapshot',version:1,session_id:'session_a1',sequence:9,entities:[entity]});
 assert.equal(x.get('tiles').children.length,1);
 x.advance(60000);x.tick();
 assert.equal(x.get('tiles').children.length,0);
 assert.match(x.get('connection').textContent,/afbrudt/);
 x.send({type:'snapshot',version:1,session_id:'session_b2',sequence:0,entities:[entity]});
 assert.equal(x.get('tiles').children.length,1);
});
test('invalid state does not replace a valid tile',()=>{
 const x=setup(),entity={entity_id:'light.stue',name:'Stue',state:'on'};
 x.send({type:'snapshot',version:1,entities:[entity]});
 x.send({type:'snapshot',version:1,entities:[{...entity,name:'bad\\nname'}]});
 assert.equal(x.get('tiles').children[0].children[0].textContent,'Stue');
 x.send({type:'snapshot',version:1,entities:Array.from({length:33},(_,i)=>({...entity,entity_id:'light.l'+i}))});
 assert.equal(x.get('tiles').children.length,1);
});
