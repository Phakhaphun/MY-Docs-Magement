"use strict";
const el=id=>document.getElementById(id);
let state=null, pending=false, connected=false, polling=false, signature='', actionError='';
const size=bytes=>{if(bytes===null||bytes===undefined)return '—';if(bytes<1024)return bytes+' B';if(bytes<1048576)return (bytes/1024).toFixed(1)+' KB';return (bytes/1048576).toFixed(2)+' MB';};
async function action(method,...args){
  if(pending)return;
  pending=true;actionError='';render();
  try{const result=await window.pywebview.api[method](...args);if(result.error)actionError=result.error;else state=result;}
  catch(error){actionError='Could not complete the action. '+error.message;}
  finally{pending=false;render();}
}
function render(updateStatus=true){
  if(!state)return;
  const busy=state.running||pending;
  for(const id of ['addFiles','emptyAdd','clearFiles','chooseOutput'])el(id).disabled=busy;
  document.querySelectorAll('[name=preset]').forEach(input=>input.disabled=busy);
  el('compress').disabled=busy||!state.files.length||state.files.some(file=>!file.pages);
  el('compress').hidden=state.running;el('cancel').hidden=!state.running;
  el('cancel').disabled=pending||state.cancelling;el('cancel').textContent=state.cancelling?'Cancelling…':'Cancel';
  el('openOutput').hidden=!state.result?.paths?.length||state.running;
  el('fileCount').textContent=state.files.length;
  el('emptyState').hidden=!!state.files.length;el('fileList').hidden=!state.files.length;
  el('clearFiles').hidden=!state.files.length;
  el('outputPath').value=state.output;el('outputPath').title=state.output;
  if(updateStatus)el('status').textContent=actionError||state.message;
  el('warning').textContent=state.warning||'';
  el('progress').hidden=!state.running;el('progress').value=state.progress;
  const completed=state.files.filter(file=>file.after_size!==null&&file.after_size!==undefined);
  const before=completed.reduce((total,file)=>total+file.before_size,0),after=completed.reduce((total,file)=>total+file.after_size,0);
  el('summary').textContent=completed.length?`${size(before)} → ${size(after)} · ${size(before-after)} saved${state.failed?' · '+state.failed+' failed':''}`:state.files.length?`${state.files.length} PDF${state.files.length===1?'':'s'} · ${size(state.files.reduce((total,file)=>total+file.size,0))}`:'No files added';
  const nextSignature=JSON.stringify([state.files,busy]);
  if(nextSignature===signature)return;
  signature=nextSignature;el('fileList').replaceChildren();
  for(const file of state.files){
    const row=document.createElement('div');row.className='file-row '+file.status;
    const icon=document.createElement('span');icon.className='file-icon';icon.textContent='PDF';
    const content=document.createElement('div');
    const name=document.createElement('div');name.className='file-name';name.textContent=file.name;
    const meta=document.createElement('div');meta.className='file-meta';meta.textContent=`${file.pages} page${file.pages===1?'':'s'} · ${size(file.size)}`;
    content.append(name,meta);
    if(file.after_size!==null&&file.after_size!==undefined){const sizes=document.createElement('div');sizes.className='file-sizes';sizes.append(document.createTextNode(size(file.before_size)+' → '));const after=document.createElement('b');after.textContent=size(file.after_size);sizes.append(after);content.append(sizes);}
    const detail=document.createElement('div');detail.className='file-detail';detail.textContent=file.detail;content.append(detail);
    const remove=document.createElement('button');remove.className='remove';remove.textContent='×';remove.setAttribute('aria-label','Remove '+file.name);remove.disabled=busy;remove.onclick=()=>action('remove_file',file.id);
    row.append(icon,content,remove);el('fileList').append(row);
  }
}
el('addFiles').onclick=el('emptyAdd').onclick=()=>action('choose_files');
el('chooseOutput').onclick=()=>action('choose_output');el('clearFiles').onclick=()=>action('clear_files');
el('compress').onclick=()=>action('start',document.querySelector('[name=preset]:checked').value);
el('cancel').onclick=()=>action('cancel_conversion');
el('openOutput').onclick=async()=>{try{const result=await window.pywebview.api.open_output();if(result.error)el('status').textContent=result.error;}catch(error){el('status').textContent=error.message;}};
document.querySelectorAll('[name=preset]').forEach(input=>input.addEventListener('change',()=>{el('presetHelp').textContent=input.value==='lossless'?'Optimizes PDF data without reducing image quality. Size savings depend on the file.':'Recompresses embedded images. Text remains selectable and searchable.';}));
document.addEventListener('dragover',event=>event.preventDefault());document.addEventListener('drop',event=>{event.preventDefault();parent.forwardPDFDrop(event.dataTransfer);});
window.addEventListener('pywebviewready',async()=>{if(connected)return;connected=true;await action('get_state');setInterval(async()=>{if(polling||pending||document.hidden)return;polling=true;try{state=await window.pywebview.api.get_state();render();}catch(error){el('status').textContent=error.message;}finally{polling=false;}},350);});
