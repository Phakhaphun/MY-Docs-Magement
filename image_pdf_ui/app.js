"use strict";
const el=id=>document.getElementById(id);
let state=null,pending=false,polling=false,connected=false,initialized=false,signature='',dragged=null,lastCompletion=null,completionResult=null;
let generation=0,queue=[],thumbnailBusy=false,sendPending=false;
const cache=new Map();
const icons={left:'m14 5-7 7 7 7',right:'m10 5 7 7-7 7',rotateLeft:'M4 10a8 8 0 1 1 1 8M4 4v6h6',rotateRight:'M20 10a8 8 0 1 0-1 8M20 4v6h-6',remove:'M5 5l14 14M19 5 5 19'};
const locked=()=>pending||!!state?.running;
async function action(method,...args){
  if(pending)return;pending=true;sync();
  try{const result=await window.pywebview.api[method](...args);if(result.error)el('status').textContent=result.error;else{state=result;render();}}
  catch(error){el('status').textContent=error.message;}
  finally{pending=false;sync();pump();}
}
function options(){return {page_size:el('pageSize').value,orientation:el('orientation').value,margin:Number(el('margin').value),mode:el('mode').value};}
function sync(){
  if(!state)return;const busy=locked();
  for(const id of ['addImages','emptyAdd','chooseOutput','clearImages','pageSize','margin','mode'])el(id).disabled=busy;
  el('orientation').disabled=busy||el('pageSize').value==='original';
  el('createPDF').disabled=busy||!state.files.length||state.files.some(file=>!file.width)||!el('margin').value.trim()||!el('margin').checkValidity();
  el('createPDF').hidden=!!state.running;el('createPDF').textContent=el('mode').value==='combine'?'Create PDF':'Create PDFs';
  el('cancel').hidden=!state.running;el('cancel').disabled=pending||state.cancelling;el('cancel').textContent=state.cancelling?'Cancelling…':'Cancel';
  el('viewResult').hidden=!state.result||state.running;el('viewResult').disabled=busy;
  el('layoutHelp').textContent=el('pageSize').value==='original'?'Uses image resolution metadata, or 96 DPI when unavailable. Margins add space around the image.':'Images fit inside the page without cropping.';
  for(const card of el('imageGrid').children){card.draggable=!busy;for(const button of card.querySelectorAll('button'))button.disabled=busy||button.dataset.boundary==='true';}
}
function render(){
  if(!state)return;
  if(!initialized){for(const [id,key] of [['pageSize','page_size'],['orientation','orientation'],['margin','margin'],['mode','mode']])el(id).value=state.options[key];initialized=true;}
  el('imageCount').textContent=state.files.length;el('clearImages').hidden=!state.files.length;
  el('emptyState').hidden=!!state.files.length;el('imageGrid').hidden=!state.files.length;
  el('summary').textContent=state.files.length?`${state.files.length} image${state.files.length===1?'':'s'} · In the order shown`:'No images added';
  el('status').textContent=state.message;el('warning').textContent=state.warning||'';
  el('outputPath').value=state.output;el('outputPath').title=state.output;
  el('progress').hidden=!state.running;el('progress').value=state.progress;
  sync();showCompletion();
  const next=JSON.stringify(state.files);if(next===signature)return;signature=next;
  generation++;observer.disconnect();queue=[];el('imageGrid').replaceChildren();
  for(const [index,file] of state.files.entries()){
    const card=document.createElement('article');card.className='image-card'+(file.width?'':' error');card.dataset.id=file.id;card.draggable=!locked();
    const thumb=document.createElement('div');thumb.className='thumb';
    const badge=document.createElement('span');badge.className='order-badge';badge.textContent=index+1;
    const image=document.createElement('img');image.alt=file.name;image.hidden=true;image.draggable=false;image.style.transform=`rotate(${file.rotation}deg)`;
    const message=document.createElement('span');message.className='thumb-message';message.textContent=file.width?'Loading preview…':file.detail;
    thumb.append(badge,image,message);
    const name=document.createElement('div');name.className='image-name';name.textContent=file.name;name.title=file.name;
    const meta=document.createElement('div');meta.className='image-meta';meta.textContent=file.width?`${file.rotation%180?file.height:file.width} × ${file.rotation%180?file.width:file.height} px`:'Cannot read this image';
    const controls=document.createElement('div');controls.className='image-actions';
    function button(label,icon,fn,boundary=false){const control=document.createElement('button');control.type='button';control.title=label;control.setAttribute('aria-label',label);control.dataset.action=icon;control.dataset.boundary=String(boundary);control.disabled=locked()||boundary;control.innerHTML=`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[icon]}"/></svg>`;control.onclick=fn;controls.append(control);}
    button('Move image left','left',()=>move(file.id,index-1),index===0);
    button('Rotate left 90°','rotateLeft',()=>rotate(file.id,-90));button('Rotate right 90°','rotateRight',()=>rotate(file.id,90));
    button('Move image right','right',()=>move(file.id,index+1),index===state.files.length-1);button('Remove image','remove',()=>action('remove_file',file.id));
    card.append(thumb,name,meta,controls);el('imageGrid').append(card);
    card.ondragstart=event=>{if(locked()){event.preventDefault();return;}dragged=file.id;event.dataTransfer.setData('text/plain',file.id);event.dataTransfer.effectAllowed='move';card.classList.add('dragging');};
    card.ondragend=()=>{dragged=null;card.classList.remove('dragging');document.querySelectorAll('.drag-over').forEach(item=>item.classList.remove('drag-over'));};
    card.ondragover=event=>{if(dragged&&!locked()){event.preventDefault();card.classList.add('drag-over');}};
    card.ondragleave=()=>card.classList.remove('drag-over');
    card.ondrop=event=>{if(!dragged||locked())return;event.preventDefault();event.stopPropagation();card.classList.remove('drag-over');if(dragged!==file.id)move(dragged,index);dragged=null;};
    if(file.width)observer.observe(card);
  }
  sync();
}
function plan(){return state.files.map(file=>({id:file.id,rotation:file.rotation}));}
function rotate(id,degrees){if(locked())return;const items=plan(),item=items.find(item=>item.id===id);item.rotation=(item.rotation+degrees+360)%360;action('set_layout',items);}
function move(id,index){if(locked()||index<0||index>=state.files.length)return;const items=plan(),from=items.findIndex(item=>item.id===id);const [item]=items.splice(from,1);items.splice(index,0,item);action('set_layout',items);}
const observer=new IntersectionObserver(entries=>{for(const entry of entries){const card=entry.target;card.dataset.inView=String(entry.isIntersecting);if(entry.isIntersecting)queue.push({card,generation});else{const image=card.querySelector('img');image.removeAttribute('src');image.hidden=true;card.querySelector('.thumb-message').hidden=false;}}pump();},{root:el('imageScroll'),rootMargin:'180px'});
async function pump(){
  if(thumbnailBusy||locked()||!connected)return;thumbnailBusy=true;
  try{while(queue.length&&!locked()){
    const task=queue.shift(),card=task.card;if(!card.isConnected||task.generation!==generation||card.dataset.inView!=='true')continue;
    let result=cache.get(card.dataset.id);
    if(!result){result=await window.pywebview.api.thumbnail(card.dataset.id);if(!result.error){cache.set(card.dataset.id,result);if(cache.size>60)cache.delete(cache.keys().next().value);}}
    if(!card.isConnected||task.generation!==generation||card.dataset.inView!=='true')continue;
    if(result.error){card.querySelector('.thumb-message').textContent='Preview unavailable';continue;}
    const image=card.querySelector('img');image.onload=()=>{if(card.isConnected&&card.dataset.inView==='true'){image.hidden=false;card.querySelector('.thumb-message').hidden=true;}};image.src=result.image;
  }}catch(error){el('status').textContent=error.message;}finally{thumbnailBusy=false;}
}
function showCompletion(){
  const result=state.result;if(state.running||!result||result.id===lastCompletion||window.frameElement?.hidden)return;
  completionResult=result;lastCompletion=result.id;
  const count=result.paths.length,warning=result.cancelled||result.error;
  el('completionTitle').textContent=result.error?'Could not create PDFs':result.cancelled?'PDF creation cancelled':count===1?'PDF created':'PDFs created';
  el('completionIcon').textContent=warning?'!':'✓';el('completionDialog').classList.toggle('has-warning',!!warning);
  el('completionSummary').textContent=`Saved ${count} PDF${count===1?'':'s'}.`;
  el('completionPaths').replaceChildren();for(const path of result.paths){const line=document.createElement('div');line.textContent=path;el('completionPaths').append(line);}el('completionPaths').hidden=!count;
  el('completionNote').textContent=result.error||(result.cancelled?'Completed PDFs have been kept. No incomplete PDF was saved.':'Original images are unchanged. Your PDFs are ready.');
  el('completionError').hidden=true;el('completionError').textContent='';el('completionOpen').hidden=!count;el('nextSteps').hidden=!count;
  el('completionDialog').showModal();
}
async function openOutput(){try{const result=await window.pywebview.api.open_output();if(result.error)throw new Error(result.error);}catch(error){el('completionError').textContent=error.message;el('completionError').hidden=false;}}
async function sendTo(target){
  if(sendPending||!completionResult)return;sendPending=true;el('completionError').hidden=true;el('continueOCR').disabled=el('continueCompress').disabled=true;
  try{const result=await window.pywebview.api.send_to(target,completionResult.id);if(result.error)throw new Error(result.error);el('completionDialog').close();parent.selectWorkspace(result.workspace);parent.document.getElementById(result.workspace).contentDocument.getElementById('completionDialog')?.close();}
  catch(error){el('completionError').textContent=error.message;el('completionError').hidden=false;}
  finally{sendPending=false;el('continueOCR').disabled=el('continueCompress').disabled=false;}
}
el('addImages').onclick=el('emptyAdd').onclick=()=>action('choose_files');el('chooseOutput').onclick=()=>action('choose_output');el('clearImages').onclick=()=>action('clear_files');
el('createPDF').onclick=()=>action('start',options());el('cancel').onclick=()=>action('cancel_conversion');
for(const id of ['pageSize','orientation','margin','mode'])el(id).addEventListener('input',sync);
el('completionDone').onclick=()=>el('completionDialog').close();el('completionOpen').onclick=openOutput;
el('viewResult').onclick=()=>{lastCompletion=null;showCompletion();};
el('completionDialog').addEventListener('close',()=>{(el('createPDF').disabled?el('addImages'):el('createPDF')).focus();});
el('continueOCR').onclick=()=>sendTo('ocr');el('continueCompress').onclick=()=>sendTo('compressor');
document.addEventListener('dragover',event=>event.preventDefault());document.addEventListener('drop',event=>{event.preventDefault();if(!dragged)parent.forwardPDFDrop(event.dataTransfer);});
window.addEventListener('pywebviewready',async()=>{if(connected)return;connected=true;await action('get_state');setInterval(async()=>{if(pending||polling||window.frameElement?.hidden)return;polling=true;try{state=await window.pywebview.api.get_state();render();pump();}catch(error){el('status').textContent=error.message;}finally{polling=false;}},400);});
