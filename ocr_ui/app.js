"use strict";
const el=id=>document.getElementById(id);
let state=null,catalog=[],selected=['eng','tha'],pending=false,polling=false,connected=false,loaded=false;
let actionError='',signature='',lastDownload=null,lastCompletion=null;
const size=bytes=>bytes<1048576?(bytes/1024).toFixed(0)+' KB':(bytes/1048576).toFixed(1)+' MB';
const missing=()=>catalog.filter(item=>selected.includes(item.code)&&!item.installed);
async function action(method,...args){
  if(pending)return;
  pending=true;actionError='';render();
  try{const result=await window.pywebview.api[method](...args);if(result.error)actionError=result.error;else state=result;}
  catch(error){actionError='Could not complete the action. '+error.message;}
  finally{pending=false;render();}
}
function renderLanguages(){
  el('selectedLanguages').replaceChildren();
  for(const code of selected){const item=catalog.find(item=>item.code===code);const chip=document.createElement('span');chip.className='language-chip'+(item&&!item.installed?' missing':'');chip.textContent=item?.name||code;el('selectedLanguages').append(chip);}
  el('languageHelp').textContent=!loaded?'Preparing language packs…':!selected.length?'Choose at least one document language.':missing().length?`${missing().length} selected pack(s) need a download · ${size(missing().reduce((sum,item)=>sum+item.size,0))}`:'Selected languages are ready · Works offline';
  el('downloadLanguages').hidden=!missing().length;
}
function render(){
  if(!state)return;
  const busy=state.running||pending;
  for(const id of ['addFiles','emptyAdd','chooseOutput','clearFiles','profile','downloadLanguages'])el(id).disabled=busy;
  el('chooseLanguages').disabled=busy||!loaded;
  el('startOCR').hidden=state.running;el('startOCR').disabled=busy||!loaded||!selected.length||!!missing().length||!state.files.length||state.files.some(file=>!file.pages);
  el('cancel').hidden=!state.running;el('cancel').disabled=pending||state.cancelling;
  el('cancel').textContent=state.cancelling?'Cancelling…':'Cancel';
  el('openOutput').hidden=state.running||!state.files.some(file=>file.output);
  el('outputPath').value=state.output;el('outputPath').title=state.output;
  el('fileCount').textContent=state.files.length;el('emptyState').hidden=!!state.files.length;
  el('fileList').hidden=!state.files.length;el('clearFiles').hidden=!state.files.length;
  el('progress').hidden=!state.running;el('progress').value=state.progress;
  el('status').textContent=actionError||state.message;el('warning').textContent=state.warning||'';
  el('summary').textContent=state.operation==='download'&&state.running?'Downloading language packs':state.files.length?`${state.files.length} PDF${state.files.length===1?'':'s'} · ${state.files.reduce((sum,file)=>sum+file.pages,0)} pages`:'No files added';
  renderLanguages();
  showCompletion();
  const next=JSON.stringify([state.files,busy]);if(next===signature)return;signature=next;
  el('fileList').replaceChildren();
  for(const file of state.files){
    const row=document.createElement('div');row.className='file-row '+file.status;
    const icon=document.createElement('span');icon.className='file-icon';icon.textContent='PDF';
    const content=document.createElement('div');
    const name=document.createElement('div');name.className='file-name';name.textContent=file.name;
    const meta=document.createElement('div');meta.className='file-meta';meta.textContent=`${file.pages} pages · ${size(file.size)}`;
    const detail=document.createElement('div');detail.className='file-detail';detail.textContent=file.detail;
    content.append(name,meta,detail);
    if(file.output){const badge=document.createElement('div');badge.className='ocr-text-badge';badge.textContent=file.text_pages?'Searchable PDF saved':'PDF saved · Review recognition';content.append(badge);}
    const remove=document.createElement('button');remove.className='remove';remove.textContent='×';remove.setAttribute('aria-label','Remove '+file.name);remove.disabled=busy;remove.onclick=()=>action('remove_file',file.id);
    row.append(icon,content,remove);el('fileList').append(row);
  }
}
function showCompletion(){
  const result=state.result;
  if(state.running||!result||result.operation!=='ocr'||result.id===lastCompletion||window.frameElement?.hidden||el('languageDialog').open)return;
  const saved=result.paths.length,failed=state.failed||0;
  const noText=state.files.filter(file=>file.output&&file.text_pages===0).length;
  const warning=result.cancelled||failed||noText;
  el('completionTitle').textContent=result.cancelled?'OCR cancelled':failed?(saved?'Completed with errors':'Could not create searchable PDFs'):noText?'OCR complete · Review needed':'Searchable PDFs created';
  el('completionIcon').textContent=result.cancelled?'−':warning?'!':'✓';
  el('completionDialog').classList.toggle('has-warning',!!warning);
  el('completionSummary').textContent=`Saved ${saved} PDF${saved===1?'':'s'}${failed?` · ${failed} failed`:''}.`;
  el('completionPaths').replaceChildren();
  for(const path of result.paths){const line=document.createElement('div');line.textContent=path;el('completionPaths').append(line);}
  el('completionPaths').hidden=!saved;
  el('completionNote').textContent=result.cancelled?'Completed files have been kept. No incomplete PDF was saved.':failed?'Check the file list for error details. Original files are unchanged.':noText?`No text was detected in ${noText} file(s). Review the scan quality and selected languages.`:'Original files are unchanged. Review important names and numbers after OCR.';
  el('completionOpenOutput').hidden=!saved;
  el('completionMessage').hidden=true;el('completionMessage').textContent='';
  el('completionDialog').showModal();lastCompletion=result.id;
}
function renderLanguageList(){
  const query=el('languageSearch').value.trim().toLowerCase();el('languageList').replaceChildren();
  for(const item of catalog.filter(item=>(item.name+' '+item.code).toLowerCase().includes(query))){
    const label=document.createElement('label');label.className='language-option';
    const input=document.createElement('input');input.type='checkbox';input.value=item.code;input.checked=selected.includes(item.code);
    input.onchange=()=>{if(input.checked&&selected.length>=5){input.checked=false;el('languageSelectionStatus').textContent='Choose up to 5 languages.';return;}selected=input.checked?[...selected,item.code]:selected.filter(code=>code!==item.code);renderLanguages();el('languageSelectionStatus').textContent=`${selected.length} of 5 selected`;};
    const text=document.createElement('span'),name=document.createElement('strong'),status=document.createElement('small');name.textContent=item.name;status.textContent=item.installed?'Ready offline':`Download · ${size(item.size)}`;status.className=item.installed?'ready':'';text.append(name,status);label.append(input,text);el('languageList').append(label);
  }
  if(!el('languageList').childElementCount){const empty=document.createElement('p');empty.className='help';empty.textContent='No languages found.';el('languageList').append(empty);}
  el('languageSelectionStatus').textContent=`${selected.length} of 5 selected`;
}
el('chooseLanguages').onclick=()=>{el('languageSearch').value='';renderLanguageList();el('languageDialog').showModal();el('languageSearch').focus();};
el('closeLanguages').onclick=()=>el('languageDialog').close();el('languageDialog').addEventListener('close',()=>{render();el('chooseLanguages').focus();});
el('languageSearch').oninput=renderLanguageList;
el('profile').onchange=()=>{el('profileHelp').textContent=el('profile').value==='light'?'Lower memory use and shorter processing. Small text may be missed.':el('profile').value==='detailed'?'For small text in clear scans. More detail cannot restore a blurred original.':'For general documents. Try Detailed when small text is missed.';};
el('addFiles').onclick=el('emptyAdd').onclick=()=>action('choose_files');
el('chooseOutput').onclick=()=>action('choose_output');el('clearFiles').onclick=()=>action('clear_files');
el('startOCR').onclick=()=>action('start',selected,el('profile').value);
el('downloadLanguages').onclick=()=>action('install_languages',selected);
el('cancel').onclick=()=>action('cancel_conversion');
async function openOutput(){
  try{const result=await window.pywebview.api.open_output();if(result.error)throw new Error(result.error);}
  catch(error){actionError=error.message;if(el('completionDialog').open){el('completionMessage').textContent=error.message;el('completionMessage').hidden=false;}render();}
}
el('openOutput').onclick=el('completionOpenOutput').onclick=openOutput;
el('completionDone').onclick=()=>el('completionDialog').close();
el('completionDialog').addEventListener('close',()=>{(el('startOCR').disabled?el('addFiles'):el('startOCR')).focus();});
document.addEventListener('dragover',event=>event.preventDefault());document.addEventListener('drop',event=>{event.preventDefault();parent.forwardPDFDrop(event.dataTransfer);});
window.addEventListener('pywebviewready',async()=>{
  if(connected)return;connected=true;
  try{
    await action('get_state');const options=await window.pywebview.api.get_languages();if(options.error)throw new Error(options.error);
    catalog=options.languages;selected=options.selected;el('profile').value=options.profile;el('profile').onchange();loaded=true;render();
    setInterval(async()=>{
      if(polling||pending||window.frameElement?.hidden)return;polling=true;
      try{
        state=await window.pywebview.api.get_state();
        if(state.result?.operation==='download'&&state.result.id!==lastDownload){const options=await window.pywebview.api.get_languages();catalog=options.languages;lastDownload=state.result.id;}
        render();
      }catch(error){actionError=error.message;render();}finally{polling=false;}
    },400);
  }catch(error){actionError=error.message;render();}
});
