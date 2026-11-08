"use strict";
const el=id=>document.getElementById(id);
let state=null,pending=false,polling=false,connected=false,initialized=false,signature='',dragged=null,lastCompletion=null,completionResult=null;
let generation=0,queue=[],thumbnailBusy=false,sendPending=false;
let previewSignature='';
const cache=new Map();
const icons={left:'m14 5-7 7 7 7',right:'m10 5 7 7-7 7',rotateLeft:'M4 10a8 8 0 1 1 1 8M4 4v6h6',rotateRight:'M20 10a8 8 0 1 0-1 8M20 4v6h-6',remove:'M5 5l14 14M19 5 5 19'};
const locked=()=>pending||!!state?.running;
async function action(method,...args){
  if(pending)return;pending=true;sync();
  try{const result=await window.pywebview.api[method](...args);if(result.error)el('status').textContent=result.error;else{state=result;render();}}
  catch(error){el('status').textContent=error.message;}
  finally{pending=false;sync();pump();}
}
function options(){return {page_size:el('pageSize').value,orientation:el('orientation').value,margin:Number(el('margin').value),mode:el('mode').value,custom_width:Number(el('customWidth').value),custom_height:Number(el('customHeight').value)};}
function buildPaperOptions(){
  const groups=new Map();el('pageSize').replaceChildren();
  for(const paper of state.paper_sizes){
    if(!groups.has(paper.group)){const group=document.createElement('optgroup');group.label=paper.group;groups.set(paper.group,group);el('pageSize').append(group);}
    const option=document.createElement('option');option.value=paper.id;option.textContent=`${paper.name} · ${paper.width} × ${paper.height} mm`;groups.get(paper.group).append(option);
  }
  const other=document.createElement('optgroup');other.label='Other';
  for(const [value,text] of [['original','Original image size'],['custom','Custom dimensions…']]){const option=document.createElement('option');option.value=value;option.textContent=text;other.append(option);}el('pageSize').append(other);
}
function geometry(file){
  const values=options(),margin=values.margin;
  if(!el('margin').value.trim()||!Number.isFinite(margin)||margin<0||margin>50)throw new Error('Use a margin between 0 and 50 mm.');
  let width,height;
  const rotated=file.rotation%180!==0,iw=rotated?file.height:file.width,ih=rotated?file.width:file.height;
  if(values.page_size==='custom'){
    width=values.custom_width;height=values.custom_height;
    if(!Number.isFinite(width)||!Number.isFinite(height)||width<1||height<1||width>5080||height>5080)throw new Error('Enter custom width and height between 1 and 5080 mm.');
  }else if(values.page_size==='original'){
    const dpi=file.dpi||[96,96];width=iw*25.4/dpi[rotated?1:0]+2*margin;height=ih*25.4/dpi[rotated?0:1]+2*margin;
  }else{
    const paper=state.paper_sizes.find(paper=>paper.id===values.page_size);
    if(!paper)throw new Error('Choose a page size.');
    width=paper.width;height=paper.height;
    if(values.orientation==='landscape'||(values.orientation==='auto'&&iw>ih))[width,height]=[height,width];
  }
  if(Math.max(width,height)>5080)throw new Error('Page size exceeds 5080 mm. Choose a smaller size.');
  if(Math.min(width,height)<=2*margin)throw new Error('Margins leave no room for the image. Reduce the margin or choose a larger page.');
  return {width,height,margin,iw,ih};
}
function updatePaperPreviews(){
  if(!state||!initialized)return '';
  const next=JSON.stringify([options(),state.files.map(file=>[file.id,file.rotation,file.width,file.height,file.dpi])]);
  if(next===previewSignature)return el('layoutError').hidden?'':el('layoutError').textContent;
  previewSignature=next;let error='';
  const format=value=>Number(value.toFixed(2));
  try{const first=state.files.find(file=>file.width)||{width:200,height:300,rotation:0,dpi:[96,96]};const page=geometry(first);el('paperDimensions').textContent=`${format(page.width)} × ${format(page.height)} mm${options().orientation==='auto'&& !['custom','original'].includes(options().page_size)?' · Auto per image':''}`;}catch(problem){error=problem.message;el('paperDimensions').textContent='Check page settings';}
  for(const card of el('imageGrid').children){
    const file=state.files.find(file=>file.id===card.dataset.id);if(!file?.width)continue;
    const paper=card.querySelector('.paper-preview'),image=paper.querySelector('img'),guide=paper.querySelector('.margin-guide');
    try{
      const page=geometry(file),ratio=page.width/page.height,fit=Math.min((page.width-2*page.margin)/page.iw,(page.height-2*page.margin)/page.ih);
      paper.style.width=(ratio>=1?88:88*ratio)+'%';paper.style.height=(ratio>=1?88/ratio:88)+'%';
      image.style.width=(file.width*fit/page.width*100)+'%';image.style.height=(file.height*fit/page.height*100)+'%';image.style.visibility='';
      image.style.transform=`translate(-50%,-50%) rotate(${file.rotation}deg)`;
      guide.style.inset=`${page.margin/page.height*100}% ${page.margin/page.width*100}%`;
      card.querySelector('.image-meta').textContent=`${format(page.width)} × ${format(page.height)} mm`;
      paper.classList.remove('invalid');
    }catch(problem){error=problem.message;paper.classList.add('invalid');image.style.visibility='hidden';}
  }
  el('layoutError').hidden=!error;el('layoutError').textContent=error;return error;
}
function sync(){
  if(!state)return;const busy=locked();
  if(el('pageSize').value!=='custom')for(const [id,fallback] of [['customWidth',210],['customHeight',297]]){const value=Number(el(id).value);if(!Number.isFinite(value)||value<1||value>5080)el(id).value=fallback;}
  for(const id of ['addImages','emptyAdd','chooseOutput','clearImages','pageSize','margin','mode','customWidth','customHeight','swapDimensions','sortImages'])el(id).disabled=busy;
  const fixed=['original','custom'].includes(el('pageSize').value);el('orientation').disabled=busy||fixed;
  el('orientationChoices').hidden=fixed;el('orientationLabel').hidden=fixed;
  el('customSizeFields').hidden=el('pageSize').value!=='custom';
  for(const button of document.querySelectorAll('[data-orientation]')){button.disabled=busy||fixed;button.setAttribute('aria-pressed',String(!fixed&&button.dataset.orientation===el('orientation').value));}
  for(const button of document.querySelectorAll('[data-margin]')){button.disabled=busy;button.setAttribute('aria-pressed',String(el('margin').value.trim()!==''&&Number(button.dataset.margin)===Number(el('margin').value)));}
  const error=updatePaperPreviews();
  el('createPDF').disabled=busy||!!error||!state.files.length||state.files.some(file=>!file.width)||!el('margin').value.trim()||!el('margin').checkValidity();
  el('createPDF').hidden=!!state.running;el('createPDF').textContent=el('mode').value==='combine'?'Create PDF':'Create PDFs';
  el('cancel').hidden=!state.running;el('cancel').disabled=pending||state.cancelling;el('cancel').textContent=state.cancelling?'Cancelling…':'Cancel';
  el('viewResult').hidden=!state.result||state.running;el('viewResult').disabled=busy;
  el('layoutHelp').textContent=el('pageSize').value==='original'?'Uses image DPI metadata, or 96 DPI. Margins add space around the image.':el('pageSize').value==='custom'?'Uses your exact dimensions. Swap width and height to change orientation.':'Images fit inside the page without cropping. Dashed guides show the margins.';
  for(const card of el('imageGrid').children){card.draggable=!busy;for(const button of card.querySelectorAll('button'))button.disabled=busy||button.dataset.boundary==='true';}
}
function render(){
  if(!state)return;
  if(!initialized){buildPaperOptions();for(const [id,key] of [['pageSize','page_size'],['orientation','orientation'],['margin','margin'],['mode','mode'],['customWidth','custom_width'],['customHeight','custom_height']])el(id).value=state.options[key];initialized=true;}
  el('imageCount').textContent=state.files.length;el('clearImages').hidden=!state.files.length;
  el('emptyState').hidden=!!state.files.length;el('imageGrid').hidden=!state.files.length;
  el('summary').textContent=state.files.length?`${state.files.length} image${state.files.length===1?'':'s'} · In the order shown`:'No images added';
  el('status').textContent=state.message;el('warning').textContent=state.warning||'';
  el('outputPath').value=state.output;el('outputPath').title=state.output;
  el('progress').hidden=!state.running;el('progress').value=state.progress;
  sync();showCompletion();
  const next=JSON.stringify(state.files);if(next===signature)return;signature=next;
  generation++;observer.disconnect();queue=[];previewSignature='';el('imageGrid').replaceChildren();
  for(const [index,file] of state.files.entries()){
    const card=document.createElement('article');card.className='image-card'+(file.width?'':' error');card.dataset.id=file.id;card.draggable=!locked();
    const thumb=document.createElement('div');thumb.className='thumb';
    const badge=document.createElement('span');badge.className='order-badge';badge.textContent=index+1;
    const paper=document.createElement('div');paper.className='paper-preview';const guide=document.createElement('div');guide.className='margin-guide';
    const image=document.createElement('img');image.alt=file.name;image.hidden=true;image.draggable=false;paper.append(image,guide);
    const message=document.createElement('span');message.className='thumb-message';message.textContent=file.width?'Loading preview…':file.detail;
    thumb.append(badge,paper,message);
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
for(const id of ['pageSize','orientation','margin','mode','customWidth','customHeight'])el(id).addEventListener('input',sync);
for(const button of document.querySelectorAll('[data-orientation]'))button.onclick=()=>{el('orientation').value=button.dataset.orientation;sync();};
for(const button of document.querySelectorAll('[data-margin]'))button.onclick=()=>{el('margin').value=button.dataset.margin;sync();};
el('swapDimensions').onclick=()=>{const width=el('customWidth').value;el('customWidth').value=el('customHeight').value;el('customHeight').value=width;sync();};
el('sortImages').onchange=()=>{const value=el('sortImages').value;el('sortImages').value='';if(locked()||!value)return;const ordered=[...state.files];if(value==='reverse')ordered.reverse();else ordered.sort((left,right)=>left.name.localeCompare(right.name,undefined,{numeric:true,sensitivity:'base'})*(value==='za'?-1:1));action('set_layout',ordered.map(file=>({id:file.id,rotation:file.rotation})));};
el('completionDone').onclick=()=>el('completionDialog').close();el('completionOpen').onclick=openOutput;
el('viewResult').onclick=()=>{lastCompletion=null;showCompletion();};
el('completionDialog').addEventListener('close',()=>{(el('createPDF').disabled?el('addImages'):el('createPDF')).focus();});
el('continueOCR').onclick=()=>sendTo('ocr');el('continueCompress').onclick=()=>sendTo('compressor');
document.addEventListener('dragover',event=>event.preventDefault());document.addEventListener('drop',event=>{event.preventDefault();if(!dragged)parent.forwardPDFDrop(event.dataTransfer);});
window.addEventListener('pywebviewready',async()=>{if(connected)return;connected=true;await action('get_state');setInterval(async()=>{if(pending||polling||window.frameElement?.hidden)return;polling=true;try{state=await window.pywebview.api.get_state();render();pump();}catch(error){el('status').textContent=error.message;}finally{polling=false;}},400);});
