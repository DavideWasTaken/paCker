import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {buildPackingScene, disposePackingScene, inspectionCenter} from './packing-scene.js';
import {fitPackingCamera} from './camera.js';

const $ = id => document.getElementById(id);
const options = {angle_step:15, restarts:8, max_candidates:200000, time_limit_ms:1000, seed:42, gap:0};
const box = (id,width,length,height,max_weight=5000,quantity=-1) => ({id,width,length,height,max_weight,cost:1,quantity});
const product = (id,width,length,height,quantity,weight=100) => ({id,width,length,height,quantity,weight});
const samples = {
  overview:{boxes:[box('Compact cube',10,10,10,5000,2)],items:[product('Cube',9,9,9,2)]},
  diagonal:{boxes:[box('Square S',180,180,30),box('Rectangle L',240,180,30)],items:[product('Long bar',220,30,20,1)]},
  bars:{boxes:[box('Single square',100,100,10,5000,1)],items:[product('Narrow bar',120,5,10,4)]},
  mixed:{boxes:[box('Box S',220,160,100),box('Box M',300,220,140)],items:[product('Package A',140,80,30,2),product('Package B',80,60,40,3),product('Accessory',180,25,20,2)]},
  tiles:{boxes:[box('Layer box',200,160,90)],items:[product('Package',100,80,30,12)]},
  stock:{boxes:[box('Limited stock',140,140,60,500,1),box('Standard box',180,180,80,700)],items:[product('Heavy product',70,70,30,6,250)]},
  rod:{boxes:[box('Cube',100,100,100)],items:[{id:'Rod',width:150,length:8,height:8,rotation:'free3d',diagonal:true}],options:{support_mode:'geometric',time_limit_ms:1000,max_candidates:100000,restarts:8,seed:42,angle_step:15,clearance:0}}
};

let documentResult = null;
let packing = null;
let focusedBox = null;
let selected = -1;
let busy = false;
let operationGeneration = 0;
let validationGeneration = 0;
let submittedEditorText = '';
const stage = $('canvas');
let renderer;
try {renderer = new THREE.WebGLRenderer({antialias:true,alpha:true});}
catch (error) {$('message').textContent = 'WebGL is unavailable. Try a browser with graphics support.'; throw error;}
renderer.setPixelRatio(Math.min(devicePixelRatio,2));
renderer.setClearColor(0x000000,0);
renderer.outputColorSpace = THREE.SRGBColorSpace;
stage.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38,1,.01,1e9);
camera.up.set(0,0,1);
const controls = new OrbitControls(camera,renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = .09;
scene.add(new THREE.HemisphereLight(0xffffff,0x7b8c98,2.5));
const light = new THREE.DirectionalLight(0xffffff,3);
light.position.set(150,-250,450);
scene.add(light);
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
let down = null;
renderer.domElement.addEventListener('pointerdown', e => {down={x:e.clientX,y:e.clientY};});
renderer.domElement.addEventListener('pointerup', e => {
  if (!down || Math.hypot(e.clientX-down.x,e.clientY-down.y)>5 || !packing) return;
  const rect=renderer.domElement.getBoundingClientRect();
  pointer.set((e.clientX-rect.left)/rect.width*2-1,-(e.clientY-rect.top)/rect.height*2+1);
  raycaster.setFromCamera(pointer,camera);
  const visible=packing.items.filter(entry => entry.mesh.visible && (focusedBox===null || entry.boxIndex===focusedBox));
  const hit=raycaster.intersectObjects(visible.map(entry=>entry.mesh),false)[0];
  if (hit) selectItem(packing.items.findIndex(entry=>entry.mesh===hit.object));
});
new ResizeObserver(() => {
  const width=stage.clientWidth,height=stage.clientHeight;
  if (!width || !height) return;
  renderer.setSize(width,height,false);
  camera.aspect=width/height;
  camera.updateProjectionMatrix();
  if (packing) fitCamera(null);
}).observe(stage);
function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}
animate();

function message(text,error=false){$('message').textContent=text;$('message').classList.toggle('error',error);}
function markEditorChanged(){
  if (documentResult?.request && $('request').value!==submittedEditorText)
    $('association').textContent=`Editor changed · result uses its saved request · ${documentResult.verified?'VERIFIED':'UNVERIFIED'} geometry`;
}
async function verifyDocument(){
  const document=documentResult;
  const generation=++validationGeneration;
  document.verified=false;
  $('export').disabled=true;$('png').disabled=true;
  $('attach-request').disabled=!(document.source==='legacy'||document.source==='attached');
  if (!document.request){$('association').textContent='UNVERIFIED · attach the original request to validate';return;}
  $('association').textContent='Checking layout geometry…';
  const abort=new AbortController();
  const timer=setTimeout(()=>abort.abort(),20000);
  try {
    const response=await fetch('/api/validate',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({request:document.request,result:document.result}),signal:abort.signal});
    const verdict=await response.json();
    if (generation!==validationGeneration || document!==documentResult)return;
    if (!response.ok || !verdict.valid) throw Error((verdict.errors||[verdict.error||'Validation failed.']).join('; '));
    document.verified=true;
    $('export').disabled=false;$('png').disabled=document.result.bins.length===0;
    $('attach-request').disabled=true;
    $('association').textContent='VERIFIED · original request and packed geometry checked';
    markEditorChanged();
  } catch(error) {
    if (generation!==validationGeneration || document!==documentResult)return;
    $('association').textContent=`UNVERIFIED · ${error.name==='AbortError'?'validation timed out':error.message||String(error)}`;
    $('attach-request').disabled=!(document.source==='legacy'||document.source==='attached');
  } finally {clearTimeout(timer);}
}
function updateModeHint(){$('padding-info').hidden=$('support-mode').value!=='geometric';}
function dimensions(value){return `${value.width} × ${value.length} × ${value.height}`;}
function marginText(result){
  const resolved=result.stats?.options || {};
  const margin=result.schema_version===2 ? (resolved.clearance ?? result.clearance ?? 0) : (resolved.gap ?? 0);
  return ` · margin ${margin}`;
}
function fitCamera(top=false){
  if (!packing || !packing.boxes.length) return;
  const target=focusedBox===null ? packing.root : packing.boxes[focusedBox].group;
  const bounds=new THREE.Box3().setFromObject(target);
  const direction=top===null ? camera.position.clone().sub(controls.target) :
    top ? new THREE.Vector3(0,-.001,1) : new THREE.Vector3(.8,-1,.78);
  const {center,extent,distance}=fitPackingCamera(THREE,camera,bounds,direction);
  controls.target.copy(center);
  controls.minDistance=extent*.08;
  controls.maxDistance=distance*8;
  controls.update();
}
function updateBoxInfo(){
  const r=documentResult?.result;
  if (!r) return;
  if (focusedBox===null) {
    $('bin-info').textContent=`All ${r.bins.length} boxes${marginText(r)}`;
    $('workspace-title').textContent='All boxes';
  } else {
    const b=r.bins[focusedBox];
    $('bin-info').textContent=`Box ${focusedBox+1} · ${b.type_id} · ${dimensions(b)}${marginText(r)}`;
    $('workspace-title').textContent=`Box ${focusedBox+1}`;
  }
  document.querySelectorAll('.box-card').forEach((card,index) => {
    card.classList.toggle('selected',index===focusedBox);
    card.setAttribute('aria-pressed',String(index===focusedBox));
  });
}
function focusBox(index){
  focusedBox=index;
  packing?.boxes.forEach(({group},i)=>{group.visible=index===null || i===index;});
  if (selected>=0 && index!==null && packing.items[selected].boxIndex!==index) selectItem(-1);
  updateBoxInfo();
  fitCamera();
}
function updateInspection(){
  if (!packing) return;
  const faithful=$('faithful').checked;
  $('step').disabled=faithful;
  $('explode').disabled=faithful;
  if (faithful) {$('step').value=packing.items.length;$('explode').value=0;}
  const count=Number($('step').value);
  const explode=Number($('explode').value)/100;
  $('step-value').textContent=`${count} / ${packing.items.length}`;
  $('explode-value').textContent=`${Math.round(explode*100)}%`;
  packing.items.forEach((entry,i) => {
    const {mesh,label,boxIndex}=entry;
    mesh.visible=faithful || i<count;
    mesh.position.copy(mesh.userData.base);
    if (!faithful && explode>0) {
      const b=packing.boxes[boxIndex].bin;
      mesh.position.fromArray(inspectionCenter(mesh.userData.base.toArray(),b,explode));
    }
    label.visible=mesh.visible;
    label.position.copy(mesh.position);
    label.position.z+=Math.max(entry.item.height*.15,Math.max(packing.boxes[boxIndex].bin.width,packing.boxes[boxIndex].bin.length,packing.boxes[boxIndex].bin.height)*.025);
  });
  if (selected>=count && !faithful) selectItem(-1);
  fitCamera(null);
}
function selectItem(index){
  selected=index;
  if (index>=0 && !$('faithful').checked && index>=Number($('step').value)) {
    $('step').value=index+1;
    updateInspection();
  }
  packing?.items.forEach(({mesh},i)=>{
    mesh.material.emissive.setHex(i===index?0x204f3f:0);
    mesh.material.emissiveIntensity=i===index?.25:0;
  });
  document.querySelectorAll('.item').forEach((el,i)=>{
    el.classList.toggle('selected',i===index);
    el.setAttribute('aria-pressed',String(i===index));
  });
  const entry=packing?.items[index];
  if (!entry) {$('selected-label').textContent='Select a product';$('selected-detail').hidden=true;return;}
  const {item,pose,boxIndex}=entry;
  $('selected-label').textContent=`${index+1}. ${item.id} #${item.instance+1} · ${dimensions(pose)}`;
  $('selected-detail').hidden=false;
  $('selected-detail-title').textContent=`Product ${index+1} details · Box ${boxIndex+1}`;
  $('selected-pose').textContent=`Center: ${pose.center.map(n=>Number(n.toFixed(3))).join(', ')} · Quaternion: ${pose.orientation.map(n=>Number(n.toFixed(6))).join(', ')}`;
}
function assertDisplayable(r){
  if (!r || !['complete','partial'].includes(r.status) || !Array.isArray(r.bins) || r.bins.length>256 || !Array.isArray(r.unpacked) || r.unpacked.length>256 || !r.stats) throw Error('This is not a paCker result.');
  if (!r.unpacked.every(item=>typeof item.id==='string'&&Number.isInteger(item.instance)&&item.instance>=0)) throw Error('Unplaced product identities cannot be displayed.');
  let count=0;
  for (const b of r.bins) {
    if (!['width','length','height'].every(k=>Number.isFinite(b[k])&&b[k]>0&&b[k]<=1e6) || !Array.isArray(b.items)) throw Error('Box dimensions cannot be displayed.');
    for (const item of b.items) {
      if (++count>256 || typeof item.id!=='string' || !['width','length','height'].every(k=>Number.isFinite(item[k])&&item[k]>0&&item[k]<=1e6)) throw Error('Product dimensions cannot be displayed.');
      if (r.schema_version===2) {
        if (!Array.isArray(item.center)||item.center.length!==3||!item.center.every(n=>Number.isFinite(n)&&Math.abs(n)<=2e6)||!Array.isArray(item.orientation)||item.orientation.length!==4||!item.orientation.every(Number.isFinite)||!Number.isFinite(Math.hypot(...item.orientation))||Math.hypot(...item.orientation)<1e-12) throw Error('Product pose cannot be displayed.');
      } else if (!['x','y','z','angle'].every(k=>Number.isFinite(item[k])&&Math.abs(item[k])<=2e6)) throw Error('Product pose cannot be displayed.');
    }
  }
  if (!['utilization','elapsed_ms','candidates','box_count'].every(k=>Number.isFinite(r.stats[k])&&r.stats[k]>=0)) throw Error('Result statistics cannot be displayed.');
}
function showResult(result, request=null, source='import'){
  assertDisplayable(result);
  if (packing) {scene.remove(packing.root);disposePackingScene(packing);}
  documentResult={request:request?structuredClone(request):null,result:structuredClone(result),source,verified:false};
  packing=buildPackingScene(THREE,result);
  scene.add(packing.root);
  focusedBox=null;selected=-1;
  $('selected-detail').hidden=true;
  $('selected-detail').open=false;
  $('selected-label').textContent='Select a product';
  $('export').disabled=true;$('png').disabled=true;
  $('association').textContent=request ? 'Checking layout geometry…' : 'UNVERIFIED · no request attached';
  $('boxes').textContent=result.bins.length;
  $('fill').textContent=(100*result.stats.utilization).toFixed(1)+'%';
  $('packed').textContent=packing.items.length;
  $('elapsed').textContent=result.stats.elapsed_ms.toFixed(1)+' ms';
  $('box-cards').replaceChildren();
  result.bins.forEach((b,i)=>{
    const card=document.createElement('button');card.className='box-card';card.setAttribute('aria-pressed','false');
    const title=document.createElement('strong');title.textContent=`Box ${i+1} · ${b.type_id}`;
    const detail=document.createElement('span');detail.textContent=`${dimensions(b)} · ${b.items.length} product${b.items.length===1?'':'s'}`;
    card.append(title,detail);card.addEventListener('click',()=>focusBox(i));$('box-cards').append(card);
  });
  $('items').replaceChildren();
  packing.items.forEach(({item,pose,color,boxIndex},i)=>{
    const card=document.createElement('button');card.className='item';card.setAttribute('aria-pressed','false');
    const swatch=document.createElement('span');swatch.className='swatch';swatch.style.background=`#${color.toString(16).padStart(6,'0')}`;
    const text=document.createElement('span');
    const name=document.createElement('span');name.className='name';name.textContent=`${i+1}. ${item.id} #${item.instance+1} · Box ${boxIndex+1}`;
    const dims=document.createElement('span');dims.className='dims';dims.textContent=dimensions(pose);
    text.append(name,dims);card.append(swatch,text);card.addEventListener('click',()=>{if(focusedBox!==null && focusedBox!==boxIndex)focusBox(boxIndex);selectItem(i);});$('items').append(card);
  });
  if (!packing.items.length) {$('items').textContent='No products packed.';}
  $('unpacked-items').replaceChildren();
  if (!result.unpacked.length) {$('unpacked-items').textContent='None';}
  else result.unpacked.forEach(item=>{const label=document.createElement('span');label.className='unpacked-item';label.textContent=`${item.id} #${item.instance+1}`;$('unpacked-items').append(label);});
  $('faithful').checked=true;
  $('step').max=packing.items.length;
  $('step').value=packing.items.length;
  $('explode').value=0;
  updateInspection();
  updateBoxInfo();
  fitCamera();
  verifyDocument();
}
function setRequestEditor(request){
  $('request').value=JSON.stringify(request,null,2);
  $('support-mode').value=['geometric','full_base'].includes(request.options?.support_mode)?request.options.support_mode:'contact';
  $('padding').value=request.options?.support_mode==='geometric' ? (request.options?.clearance??0) : (request.options?.gap??0);
  updateModeHint();
}
function loadSample(){
  const request=structuredClone(samples[$('sample').value]);
  request.options={...options,...request.options};
  setRequestEditor(request);
}
function normalizedRequest(){
  const request=JSON.parse($('request').value);
  if (!Array.isArray(request.items)||!Array.isArray(request.boxes)) throw Error('The request needs items and boxes arrays.');
  const clearance=Number($('padding').value);
  if (!Number.isFinite(clearance)||clearance<0) throw Error('Padding must be a nonnegative number.');
  request.options={...request.options,support_mode:$('support-mode').value};
  if (request.options.support_mode==='geometric') {request.options.clearance=clearance;request.options.gap=0;}
  else {request.options.gap=clearance;delete request.options.clearance;}
  request.items=request.items.map(item=>({
    ...item,
    rotation:item.rotation??$('rotation-default').value,
    diagonal:item.diagonal??true
  }));
  if (request.items.some(item=>item.rotation==='free3d' && (request.options.support_mode!=='geometric'||item.diagonal!==true))) throw Error('Free 3D requires geometric support and diagonal: true for that item.');
  return request;
}
async function calculate(){
  if (busy) return;
  const generation=++operationGeneration;
  busy=true;$('solve').disabled=true;message('Calculating…');
  try {
    const editorText=$('request').value;
    const request=normalizedRequest();
    const response=await fetch('/api/pack',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
    const result=await response.json();
    if (generation!==operationGeneration) return;
    if (!response.ok||result.error) throw Error(result.error||'Calculation failed.');
    showResult(result,request,'solver');
    submittedEditorText=editorText;
    markEditorChanged();
    message(result.status==='partial'?`${result.unpacked.length} product(s) unplaced. Adjust the order or search budget.`:'Layout ready.');
  } catch (error) {if (generation===operationGeneration) message(error.message||String(error),true);}
  finally {if (generation===operationGeneration) {busy=false;$('solve').disabled=false;}}
}
function supersedePendingCalculation(){
  ++operationGeneration;
  busy=false;$('solve').disabled=false;
}
$('sample').addEventListener('change',()=>{supersedePendingCalculation();loadSample();markEditorChanged();calculate();});
$('support-mode').addEventListener('change',updateModeHint);
$('solve').addEventListener('click',calculate);
$('request').addEventListener('input',()=>{$('sample').value='custom';markEditorChanged();});
$('all-boxes').addEventListener('click',()=>{if(packing)focusBox(null);});
$('top').addEventListener('click',()=>fitCamera(true));
$('reset').addEventListener('click',()=>fitCamera());
$('faithful').addEventListener('change',updateInspection);
$('step').addEventListener('input',updateInspection);
$('explode').addEventListener('input',updateInspection);
$('import').addEventListener('click',()=>$('file').click());
$('file').addEventListener('change',async()=>{
  const file=$('file').files[0];if(!file)return;
  try {
    if (file.size>1048576) throw Error('File exceeds 1 MiB.');
    const data=JSON.parse(await file.text());
    if (data.request&&data.result) {showResult(data.result,data.request,'import');supersedePendingCalculation();setRequestEditor(data.request);submittedEditorText=$('request').value;message('Request and result imported.');}
    else if (Array.isArray(data.bins)) {showResult(data,null,'legacy');supersedePendingCalculation();message('Legacy result imported without a request. Geometry is unverified.');}
    else if (Array.isArray(data.items)&&Array.isArray(data.boxes)) {setRequestEditor(data);supersedePendingCalculation();markEditorChanged();message('Request imported. Calculate a layout to view it.');}
    else throw Error('Unrecognized JSON document.');
    $('sample').value='custom';
  } catch(error) {message(error.message||String(error),true);}
  finally {$('file').value='';}
});
$('export').addEventListener('click',()=>{
  if (!documentResult?.verified)return;
  const data=documentResult.request ? {request:documentResult.request,result:documentResult.result} : documentResult.result;
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const anchor=document.createElement('a');anchor.href=url;anchor.download='packer-layout.json';anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('attach-request').addEventListener('click',()=>$('request-file').click());
$('request-file').addEventListener('change',async()=>{
  const file=$('request-file').files[0];if(!file)return;
  const record=documentResult;
  try {
    if (!record || !['legacy','attached'].includes(record.source)) throw Error('Load a result without a request first.');
    if (file.size>1048576) throw Error('File exceeds 1 MiB.');
    const request=JSON.parse(await file.text());
    if (record!==documentResult) return;
    record.request=structuredClone(request);
    record.source='attached';
    setRequestEditor(request);submittedEditorText=$('request').value;
    await verifyDocument();
  } catch(error){message(error.message||String(error),true);}
  finally {$('request-file').value='';}
});
$('png').addEventListener('click',async()=>{
  const record=documentResult;
  if (!record?.verified || !record.result.bins.length)return;
  const index=focusedBox??0,view=$('png-view').value;
  $('png').disabled=true;
  const frame=document.createElement('iframe');
  frame.style.cssText='position:fixed;left:-2000px;top:0;width:1024px;height:768px;border:0';
  const loaded=new Promise((resolve,reject)=>{frame.onload=resolve;frame.onerror=()=>reject(Error('Image page could not load.'));});
  let expired=false,timer;
  const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{expired=true;reject(Error('Image renderer timed out.'));},15000);});
  frame.src='/render.html';
  document.body.appendChild(frame);
  try {
    await Promise.race([(async()=>{
      await loaded;
      if(expired)return;
      while (!frame.contentWindow.renderPageReady) {
        await new Promise(resolve=>setTimeout(resolve,30));
        if(expired)return;
      }
      await frame.contentWindow.renderScene({result:record.result,boxIndex:index,view});
      if (expired || record!==documentResult || !record.verified)return;
      const url=frame.contentWindow.capturePng();
      const anchor=document.createElement('a');anchor.href=url;anchor.download=`packer-box-${index+1}-${view}.png`;anchor.click();
      message(`Exported Box ${index+1} in ${view} view at actual packed positions.`);
    })(),timeout]);
  } catch(error){message(error.message||String(error),true);}
  finally {expired=true;clearTimeout(timer);frame.remove();if(record===documentResult)$('png').disabled=!record.verified;}
});
loadSample();calculate();
