// Run with: node --test tests/frontend_audit.mjs
// The actual editor functions run in an isolated DOM/API harness. No CARLA session is opened.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const app=readFileSync(new URL('../scene_studio/web/app.js',import.meta.url),'utf8');
const seq=readFileSync(new URL('../scene_studio/web/sequencer.js',import.meta.url),'utf8');
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject}};
function source(name){const line=app.split('\n').find(x=>x.startsWith(`function ${name}(`)||x.startsWith(`async function ${name}(`));assert.ok(line,`actual editor function ${name}`);return line}
function harness(names,extra={}){
 const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',style:{},classList:{remove(){}},removeAttribute(){}});return elements.get(id)};
 const ctx={scene:{id:'sample',name:'Original',duration:30,actors:[],events:[],ego:'ego'},live:{state:'idle'},dirty:true,saving:false,editorBusy:false,startPending:false,history:[],redo:[],lastRun:null,selected:null,eventId:null,offlinePlaying:false,
  $:el,clone:structuredClone,keys:new Set(),sequencer:{drag:null,validating:false,selected:null,setTime(){}},toast(){},updateMode(){},attach(){},render(){},rebuildActors(){},focus(){},resetAuthoringView(){},refreshScenes:async()=>{},checkpoint(){},changed(){ctx.dirty=true},...extra};
 ctx.activeSession=()=>ctx.startPending||['starting','running','paused','preview'].includes(ctx.live.state);
 vm.createContext(ctx);for(const name of names)vm.runInContext(source(name),ctx);return ctx;
}

test('both shipped frontend modules parse',()=>{
 new vm.Script(app.replace(/^import .*;\r?\n/gm,''));
 new vm.Script(seq.replace(/export /g,''));
});
test('save response preserves edits made while the request is in flight',async()=>{
 const request=deferred();let sent;
 const ctx=harness(['save'],{api:async(path,data)=>{sent=structuredClone(data);return request.promise}});
 const pending=ctx.save();ctx.scene.name='Edited while saving';request.resolve({scene:{...sent,name:'Original'}});await pending;
 assert.equal(ctx.scene.name,'Edited while saving');assert.equal(sent.name,'Original');assert.equal(ctx.dirty,true);assert.equal(ctx.saving,false);
});
test('save normalizes an unchanged scene, suppresses double clicks, and unlocks',async()=>{
 const request=deferred();let count=0;
 const ctx=harness(['save'],{api:async()=>{count++;return request.promise}});
 const pending=ctx.save();await ctx.save();assert.equal(count,1);request.resolve({scene:{id:'sample',name:'Saved'}});await pending;
 assert.equal(ctx.scene.name,'Saved');assert.equal(ctx.dirty,false);assert.equal(ctx.saving,false);
});
test('failed save retains unsaved state and re-enables saving',async()=>{
 const ctx=harness(['save'],{api:async()=>{throw Error('disk error')}});
 await assert.rejects(ctx.save(),/disk error/);assert.equal(ctx.dirty,true);assert.equal(ctx.saving,false);
});
test('late save cannot replace a different scene',async()=>{
 const request=deferred(),ctx=harness(['save'],{api:()=>request.promise});const p=ctx.save();ctx.scene={id:'other',name:'Other'};
 request.resolve({scene:{id:'sample',name:'Original'}});await p;assert.equal(ctx.scene.id,'other');assert.equal(ctx.dirty,true);
});
test('editing transactions refuse concurrent edits and always release their lock',async()=>{
 const gate=deferred(),ctx=harness(['authoringTask']);const p=ctx.authoringTask(()=>gate.promise);
 assert.equal(ctx.editorBusy,true);await assert.rejects(ctx.authoringTask(()=>{}),/上一项/);
 gate.reject(Error('snap failed'));await assert.rejects(p,/snap failed/);assert.equal(ctx.editorBusy,false);
 ctx.live.state='running';await assert.rejects(ctx.authoringTask(()=>{}),/停止/);
});
test('cancelled scene switch restores the selector and leaves edits intact',async()=>{
 const ctx=harness(['authoringTask','loadScene'],{confirmChange:async()=>false,api:()=>assert.fail('must not load')});
 ctx.$('scene-select').value='another';await ctx.loadScene('another');assert.equal(ctx.scene.id,'sample');assert.equal(ctx.$('scene-select').value,'sample');assert.equal(ctx.dirty,true);
});
test('Escape or Cancel closes confirmation without a permanently pending promise',async()=>{
 const ctx=harness(['confirmChange']);const dialog=ctx.$('confirm');dialog.showModal=()=>{};dialog.close=value=>{if(value!==undefined)dialog.returnValue=value;dialog.onclose()};
 const p=ctx.confirmChange('discard?');dialog.close();assert.equal(await p,false);
 const yes=ctx.confirmChange('discard?');ctx.$('confirm-ok').onclick();assert.equal(await yes,true);
});
test('start locks immediately, rejects another start and submits one stable snapshot',async()=>{
 const gate=deferred();let sent,starts=0;
 const ctx=harness(['start'],{api:async(path,data)=>{if(path==='validate')return gate.promise;starts++;sent=data;return {run_id:'run-one'}}});
 const p=ctx.start(false);assert.equal(ctx.startPending,true);await assert.rejects(ctx.start(false),/停止/);
 ctx.scene.name='changed outside UI';gate.resolve({});await p;
 assert.equal(starts,1);assert.equal(sent.scene.name,'Original');assert.equal(ctx.live.run_id,'run-one');assert.equal(ctx.startPending,false);
});
test('failed start unlocks authoring without pretending a run exists',async()=>{
 const ctx=harness(['start'],{api:async()=>{throw Error('invalid scene')}});
 await assert.rejects(ctx.start(false),/invalid/);assert.equal(ctx.startPending,false);assert.equal(ctx.live.state,'idle');
});
test('commands include the run ID known to the page',async()=>{
 let body;const ctx=harness(['api'],{live:{state:'running',run_id:'current'},lastRun:'previous',fetch:async(path,opt)=>{body=JSON.parse(opt.body);return {ok:true,json:async()=>({})}}});
 await ctx.api('command',{type:'stop'});assert.equal(body.run_id,'current');
 ctx.live={state:'starting'};await ctx.api('command',{type:'stop'});assert.equal(body.run_id,'previous');
});
function numberInput(value,min=0,max=180){const listeners={};return {type:'number',dataset:{},value:String(value),get valueAsNumber(){return this.value.trim()===''?NaN:Number(this.value)},get validity(){return {rangeUnderflow:this.valueAsNumber<min,rangeOverflow:this.valueAsNumber>max,badInput:false}},setAttribute(){},addEventListener(name,cb){listeners[name]=cb},blur(){listeners.blur()}}}
test('empty, malformed and out-of-range numeric drafts never become model zero/NaN',()=>{
 const ctx=harness(['protectNumberInput']),input=numberInput(30);let committed=30;
 input.oninput=()=>committed=input.valueAsNumber;ctx.protectNumberInput(input);
 for(const invalid of ['','-','999','-1']){input.value=invalid;input.oninput({});assert.equal(committed,30);input.blur();assert.equal(input.value,'30')}
 input.value='42.5';input.oninput({});assert.equal(committed,42.5);input.value='';input.oninput({});input.blur();assert.equal(input.value,'42.5');
});
test('undo resets stale previews and event selection while preserving redo',()=>{
 let reset=0;const ctx=harness(['undoEdit'],{history:[JSON.stringify({id:'earlier',ego:'other',events:[{id:'event-before'}]})],resetAuthoringView(){reset++}});
 ctx.undoEdit();assert.equal(ctx.scene.id,'earlier');assert.equal(ctx.selected,'other');assert.equal(ctx.eventId,'event-before');assert.equal(ctx.redo.length,1);assert.equal(reset,1);
});
test('view reset clears offline playback, stale plans and the selected clip',()=>{
 const ctx=harness(['resetAuthoringView'],{offlinePlaying:true,previewTime:9,routeMode:true,planSerial:3,planResult:{old:true},planKey:'old',planTimer:1,seekTimer:2,clearTimeout(){}});
 ctx.sequencer.selected='old-clip';ctx.sequencer.plan={old:true};ctx.resetAuthoringView();
 assert.equal(ctx.offlinePlaying,false);assert.equal(ctx.previewTime,0);assert.equal(ctx.routeMode,false);assert.equal(ctx.planResult,null);assert.equal(ctx.sequencer.plan,null);assert.equal(ctx.sequencer.selected,null);assert.equal(ctx.planSerial,4);
});
test('late route preview cannot overwrite a newly running session',async()=>{
 const gate=deferred(),ctx=harness(['refreshPlan'],{planKey:'',planSerial:0,planResult:null,api:()=>gate.promise});
 const p=ctx.refreshPlan();ctx.live.state='running';gate.resolve({tracks:{}});await p;assert.equal(ctx.planResult,null);
});
test('late route preview cannot rebuild a timeline while a clip is dragged',async()=>{
 const gate=deferred(),ctx=harness(['refreshPlan'],{planKey:'',planSerial:0,planResult:null,api:()=>gate.promise});
 const p=ctx.refreshPlan();ctx.sequencer.drag={clip:'c'};gate.resolve({tracks:{}});await p;assert.equal(ctx.planResult,null);
});
test('invalid current plan clears stale track estimates instead of showing them as current',async()=>{
 const ctx=harness(['refreshPlan'],{planKey:'old',planSerial:0,planResult:{tracks:{old:{}}},drawRoutes(){},api:async()=>{throw Error('invalid route')}});
 ctx.sequencer.plan=ctx.planResult;await assert.rejects(ctx.refreshPlan(),/invalid route/);assert.equal(ctx.planResult,null);assert.equal(ctx.sequencer.plan,null);assert.equal(ctx.planKey,'');
});
test('collision times retain known simulation time and identify unmapped frames without inventing time',()=>{
 const ctx=harness(['collisionTime']);assert.equal(ctx.collisionTime({time:2.25,frame:101}),'2.3s');
 assert.equal(ctx.collisionTime({time:null,frame:999}),'帧 999 · 时间未映射');
 assert.equal(ctx.collisionTime({frame:999}),'帧 999 · 时间未映射');
 assert.equal(ctx.collisionTime({time:0,frame:101}),'0.0s');
});
test('polling renders unmapped collision time and still updates live controls',()=>{
 let updates=0;const ctx=harness(['collisionTime'],{esc:v=>String(v??''),actionNames:{},live:{events:[],collisions:[{time:null,frame:999,actor:'ego',other:'vehicle.test'}]},renderEvents(){},updateLive(){updates++}});
 const line=app.split('\n').find(x=>x.trimStart().startsWith("$('log').innerHTML="));assert.ok(line);vm.runInContext(line,ctx);
 assert.match(ctx.$('log').innerHTML,/帧 999 · 时间未映射/);assert.equal(updates,1);
});

function sequencerHarness(validate=async()=>{}){
 const elements=new Map(),get=id=>{if(!elements.has(id))elements.set(id,{value:'.5',addEventListener(){}});return elements.get(id)};
 const ctx={document:{getElementById:get,querySelectorAll:()=>[]},window:{addEventListener(){}}};vm.createContext(ctx);vm.runInContext(seq.replace(/export /g,'')+'\nglobalThis.Sequencer=Sequencer;',ctx);
 const clip={id:'c',type:'speed',start:1,duration:2},scene={duration:30,actors:[{id:'ego',clips:[clip]}]},errors=[];
 const q=new ctx.Sequencer({scene:()=>scene,locked:()=>false,selectClip(){},beforeEdit(){},afterEdit(){},validate,error:e=>errors.push(e),dragInfo(){}});
 q.render=()=>{};const element={dataset:{clip:'c'},closest:()=>({dataset:{track:'ego'}}),style:{},setPointerCapture(){}};
 const event=(x=0,id=1)=>({button:0,clientX:x,pointerId:id,preventDefault(){},target:{classList:{contains:()=>false}}});return {q,clip,element,event,errors};
}
test('timeline pointer cancellation restores the original timing',()=>{
 const {q,clip,element,event}=sequencerHarness();q.begin(event(),element);q.move(event(64));assert.equal(clip.start,3);q.cancel(event());assert.equal(clip.start,1);assert.equal(q.drag,null);
});
test('timeline ignores a different pointer and blocks another drag while validation is pending',async()=>{
 const gate=deferred(),{q,clip,element,event}=sequencerHarness(()=>gate.promise);q.begin(event(),element);q.move(event(64,2));assert.equal(clip.start,1);
 q.move(event(64));await q.end(event(64,2));assert.ok(q.drag);const p=q.end(event(64));assert.equal(q.validating,true);q.begin(event(10),element);assert.equal(q.drag,null);
 gate.resolve({});await p;assert.equal(q.validating,false);assert.equal(clip.start,3);
});
test('rejected overlapping timeline edit rolls back and releases validation lock',async()=>{
 const {q,clip,element,event,errors}=sequencerHarness(async()=>{throw Error('overlap')});q.begin(event(),element);q.move(event(64));await q.end(event(64));
 assert.equal(clip.start,1);assert.equal(q.validating,false);assert.deepEqual(errors,['overlap']);
});
