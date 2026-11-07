"use strict";
const $ = id => document.getElementById(id);
let state = {files: [], running: false}, pages = [], selected = new Set(), known = new Set();
let busy = false, polling = false, completion = null, filter = "all", anchor = null, dragged = null, previewSequence = 0;
let signature = "", toastTimer, thumbnailBusy = false, queue = [], generation = 0;
let previewItem = null, previewScale = 1, fitMode = "page", transformTargets = [];
const imageTransform = item => `scale(${item.flip_x ? -1 : 1}, ${item.flip_y ? -1 : 1}) rotate(${item.rotation}deg)`;

function transformMenu(items) {
  if (locked() || !items.length) return;
  transformTargets = items;
  $("transformTitle").textContent = items.length > 1 ? `Rotate / flip ${items.length} pages` : "Rotate / flip page";
  $("transformDialog").showModal();
}
function transformPages(operation) {
  edit(() => {
    for (const item of transformTargets) {
      if (operation === "horizontal") item.flip_x = !item.flip_x;
      else if (operation === "vertical") item.flip_y = !item.flip_y;
      else if (operation === "reset") {item.rotation = 0; item.flip_x = item.flip_y = false;}
      else {
        const angle = operation === "left" ? 270 : operation === "half" ? 180 : 90;
        item.rotation = (item.rotation + angle) % 360;
        if (angle % 180) [item.flip_x, item.flip_y] = [item.flip_y, item.flip_x];
      }
    }
  });
  $("transformDialog").close();
  if ($("previewDialog").open) {fitMode = "page"; drawPreview();}
}
const history = [], cache = new Map();
const hints = {merge: "Combine pages in the order shown.", extract: "Create a PDF per source, using your arranged page order.", split: "Save each page as a separate PDF."};
const keyOf = item => item.file_id + ":" + item.page;
const locked = () => busy || state.running;
const visible = () => pages.filter(item => filter === "all" || item.file_id === filter);
const outputPages = () => pages.filter(item => $("scope").value === "all" || selected.has(keyOf(item)));
const countLabel = (count, noun) => `${count} ${noun}${count === 1 ? "" : "s"}`;
function icon(name) {return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;}
async function call(method, ...args) {
  if (!window.pywebview?.api) throw new Error("Connecting to the desktop app.");
  return window.pywebview.api[method](...args);
}
function notify(message) {
  $("toast").textContent = message; $("toast").hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $("toast").hidden = true, 6500);
}
function remember() {history.push(pages.map(item => ({...item}))); if (history.length > 25) history.shift();}
function edit(change) {if (locked()) return; remember(); change(); render();}
function undo() {if (locked() || !history.length) return; pages = history.pop(); selected.clear(); render();}
function sync() {
  const disabled = locked();
  for (const id of ["add", "emptyAdd", "clear", "browse", "mode", "scope", "selectAll"]) $(id).disabled = disabled;
  $("clear").disabled = disabled || !state.files.length;
  $("export").disabled = disabled || !outputPages().length;
  $("undo").disabled = disabled || !history.length;
  $("rotateSelected").disabled = $("deleteSelected").disabled = disabled || !selected.size;
  $("cancel").hidden = !state.running; $("cancel").disabled = !!state.cancelling;
  $("cancel").textContent = state.cancelling ? "Cancelling…" : "Cancel";
  for (const card of document.querySelectorAll(".page-card")) {
    const checked = selected.has(card.dataset.key);
    card.classList.toggle("selected", checked); card.draggable = !disabled;
    card.querySelector(".page-check").checked = checked;
    card.querySelector(".thumb").setAttribute("aria-pressed", String(checked));
    for (const control of card.querySelectorAll("button,input")) control.disabled = disabled;
  }
  $("pageCount").textContent = countLabel(pages.length, "page");
  $("fileCount").textContent = countLabel(state.files.length, "document");
  $("summary").textContent = countLabel(outputPages().length, "page");
  $("selectionCount").textContent = selected.size ? `${selected.size} selected` : "Select pages to rotate, delete, or move";
  const shown = visible();
  $("selectAll").textContent = shown.length && shown.every(item => selected.has(keyOf(item))) ? "Deselect all" : "Select all";
  $("modeHint").textContent = hints[$("mode").value];
}
async function action(method, ...args) {
  if (busy) return;
  busy = true; sync();
  try {const result = await call(method, ...args); if (result.error) notify(result.error); else if (result.files) apply(result);}
  catch (error) {notify(String(error));}
  finally {busy = false; sync(); pump();}
}
function apply(next) {
  state = next;
  const ids = new Set(state.files.map(file => file.id));
  const changed = ids.size !== known.size || [...ids].some(id => !known.has(id));
  if (changed) {
    pages = pages.filter(item => ids.has(item.file_id));
    for (const file of state.files) if (!known.has(file.id)) {
      for (let page = 1; page <= file.pages; page++) pages.push({file_id: file.id, page, rotation: 0});
    }
    known = ids; history.length = 0;
    if (filter !== "all" && !ids.has(filter)) filter = "all";
    render();
  }
  const nextSignature = JSON.stringify(state.files.map(({id, name, pages}) => ({id, name, pages})));
  if (signature !== nextSignature) {signature = nextSignature; renderFilters();}
  $("output").value = state.output; $("output").title = state.output;
  $("status").textContent = state.message;
  $("progress").style.width = state.progress + "%";
  document.querySelector(".track").setAttribute("aria-valuenow", Math.round(state.progress));
  sync();
  if (state.result && completion !== state.result.id) {
    completion = state.result.id; $("toast").hidden = true;
    $("resultTitle").textContent = state.result.error ? "Could not organize PDFs" : state.result.cancelled ? "Cancelled" : "PDFs saved";
    $("resultSummary").textContent = state.result.error || `Saved ${state.result.paths.length} PDF(s)${state.result.cancelled ? " · Finished files have been kept." : " · Original files are unchanged."}`;
    $("resultPaths").replaceChildren();
    for (const path of state.result.paths) {const line = document.createElement("div"); line.textContent = path; $("resultPaths").append(line);}
    document.querySelector(".result-icon").textContent = state.result.error ? "!" : state.result.cancelled ? "−" : "✓";
    if (!$("resultDialog").open) $("resultDialog").showModal();
  }
}
function renderFilters() {
  $("fileFilters").replaceChildren();
  for (const file of [{id: "all", name: "All documents"}, ...state.files]) {
    const button = document.createElement("button"); button.className = "file-filter" + (filter === file.id ? " active" : "");
    button.textContent = file.name; button.title = file.name; button.setAttribute("aria-pressed", String(filter === file.id));
    button.onclick = () => {filter = file.id; renderFilters(); render(); if (file.pages === 0) notify(file.detail);};
    $("fileFilters").append(button);
  }
}
function choose(item, event) {
  if (locked()) return;
  const key = keyOf(item), shown = visible(), start = shown.findIndex(page => keyOf(page) === anchor), end = shown.indexOf(item);
  if (event.shiftKey && start >= 0) {
    for (const page of shown.slice(Math.min(start, end), Math.max(start, end) + 1)) selected.add(keyOf(page));
  } else if (selected.has(key)) selected.delete(key); else selected.add(key);
  anchor = key; sync();
}
function move(item, offset) {
  const index = pages.indexOf(item), target = index + offset;
  if (target < 0 || target >= pages.length) return;
  edit(() => {[pages[index], pages[target]] = [pages[target], pages[index]];});
}
function dropBefore(target, after=false) {
  if (!dragged || locked()) return;
  const keys = selected.has(dragged) ? new Set(selected) : new Set([dragged]);
  if (keys.has(keyOf(target))) return;
  edit(() => {
    const moving = pages.filter(item => keys.has(keyOf(item)));
    pages = pages.filter(item => !keys.has(keyOf(item)));
    pages.splice(pages.indexOf(target) + (after ? 1 : 0), 0, ...moving);
  });
}
const observer = new IntersectionObserver(entries => {
  for (const entry of entries) {
    const card = entry.target;
    if (entry.isIntersecting) {queue.push({card, generation});}
    else {const image = card.querySelector(".thumb img"); image.removeAttribute("src"); image.hidden = true; card.querySelector(".thumb-loading").hidden = false;}
  }
  pump();
}, {root: $("pageScroll"), rootMargin: "150px"});
async function pump() {
  if (thumbnailBusy || locked() || $("previewDialog").open) return;
  thumbnailBusy = true;
  try {
    while (queue.length && !locked() && !$("previewDialog").open) {
      const task = queue.shift(), card = task.card;
      if (task.generation !== generation || !card.isConnected) continue;
      const bounds = card.getBoundingClientRect(), viewport = $("pageScroll").getBoundingClientRect();
      if (bounds.bottom < viewport.top - 150 || bounds.top > viewport.bottom + 150) continue;
      const key = card.dataset.key;
      let result = cache.get(key);
      if (!result) {
        result = await call("thumbnail", card.dataset.fileId, Number(card.dataset.page) - 1);
        if (!result.error) {cache.set(key, result); if (cache.size > 120) cache.delete(cache.keys().next().value);}
      }
      if (!card.isConnected || task.generation !== generation) continue;
      const image = card.querySelector(".thumb img"), label = card.querySelector(".thumb-loading");
      if (result.error) {label.textContent = "Preview unavailable"; label.title = result.error; continue;}
      image.onload = () => {if (card.isConnected && task.generation === generation) {image.hidden = false; label.hidden = true;}};
      image.src = result.image;
    }
  } catch (error) {notify(String(error));}
  finally {thumbnailBusy = false;}
}
function render() {
  generation++; queue = []; observer.disconnect();
  const allowed = new Set(pages.map(keyOf)); selected = new Set([...selected].filter(key => allowed.has(key)));
  $("pages").replaceChildren(); $("empty").hidden = !!pages.length;
  $("empty").querySelector("h2").textContent = state.files.length ? "No pages left" : "Your pages, all in one place";
  $("empty").querySelector("p").textContent = state.files.length ? "Use Undo to restore removed pages, or add another PDF." : "Add PDFs to see every page. Drag to reorder, rotate, or remove pages.";
  $("pages").hidden = !pages.length;
  const files = new Map(state.files.map(file => [file.id, file]));
  const positions = new Map(pages.map((item, index) => [keyOf(item), index + 1]));
  for (const item of visible()) {
    const file = files.get(item.file_id), key = keyOf(item);
    const card = document.createElement("article"); card.className = "page-card"; card.dataset.key = key; card.dataset.fileId = item.file_id; card.dataset.page = item.page;
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.className = "page-check"; checkbox.setAttribute("aria-label", `Select ${file.name}, page ${item.page}`); checkbox.onclick = event => choose(item, event);
    const badge = document.createElement("span"); badge.className = "order-badge"; badge.textContent = positions.get(key); badge.title = "Position in the exported document";
    const thumb = document.createElement("button"); thumb.className = "thumb"; thumb.setAttribute("aria-label", `Select ${file.name}, page ${item.page}`); thumb.setAttribute("aria-pressed", String(selected.has(key)));
    const image = document.createElement("img"); image.alt = `${file.name}, page ${item.page}`; image.hidden = true; image.draggable = false; image.style.transform = imageTransform(item); image.classList.toggle("quarter-turn", item.rotation % 180 !== 0);
    const loading = document.createElement("span"); loading.className = "thumb-loading"; loading.textContent = "Loading thumbnail…";
    thumb.append(image, loading); thumb.onclick = event => choose(item, event); thumb.ondblclick = () => preview(item); thumb.title = "Click to select · Double-click for a larger preview";
    const meta = document.createElement("div"); meta.className = "page-meta";
    const title = document.createElement("strong"); title.textContent = `Page ${item.page}`;
    const source = document.createElement("span"); source.textContent = file.name; source.title = file.name; meta.append(title, source);
    const actions = document.createElement("div"); actions.className = "page-actions";
    for (const [name, label, handler] of [["left", "Move earlier", () => move(item, -1)], ["right", "Move later", () => move(item, 1)], ["zoom", "Open preview", () => preview(item)], ["rotate", "Rotate / flip page", () => transformMenu([item])], ["trash", "Delete page", () => edit(() => {pages = pages.filter(page => page !== item);})]]) {
      const button = document.createElement("button"); button.className = "icon" + (name === "trash" ? " danger-text" : ""); button.innerHTML = icon(name); button.dataset.action = name; button.title = label; button.setAttribute("aria-label", `${label} ${item.page}`); button.onclick = handler; actions.append(button);
    }
    card.append(checkbox, badge, thumb, meta, actions);
    card.addEventListener("dragstart", event => {if (locked()) {event.preventDefault(); return;} dragged = key; event.dataTransfer.setData("application/x-docspace-page", key); event.dataTransfer.effectAllowed = "move";});
    card.addEventListener("dragover", event => {if (dragged) {event.preventDefault(); event.stopPropagation(); card.classList.add("drag-over");}});
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", event => {if (!dragged) return; event.preventDefault(); event.stopPropagation(); const bounds = card.getBoundingClientRect(); const after = $("pages").classList.contains("list-view") ? event.clientY > bounds.top + bounds.height / 2 : event.clientX > bounds.left + bounds.width / 2; dropBefore(item, after); dragged = null;});
    card.addEventListener("dragend", () => {dragged = null; document.querySelectorAll(".drag-over").forEach(card => card.classList.remove("drag-over"));});
    $("pages").append(card); observer.observe(card);
  }
  sync();
}
async function preview(item) {
  const request = ++previewSequence;
  previewItem = item; fitMode = "page";
  const file = state.files.find(file => file.id === item.file_id);
  $("previewTitle").textContent = `${file.name} · Page ${item.page}`;
  $("previewCanvas").hidden = true; $("previewImage").hidden = true; $("previewMessage").hidden = false; $("previewMessage").textContent = "Preparing preview…";
  $("previewDialog").showModal();
  try {
    const result = await call("preview", item.file_id, item.page - 1);
    if (request !== previewSequence || !$("previewDialog").open) return;
    if (result.error) {$("previewMessage").textContent = result.error; return;}
    $("previewImage").onload = () => {if (request === previewSequence) {$("previewMessage").hidden = true; $("previewImage").hidden = false; $("previewCanvas").hidden = false; drawPreview();}};
    $("previewImage").src = result.image;
  } catch (error) {$("previewMessage").textContent = String(error);}
}
function drawPreview() {
  const image = $("previewImage"), stage = $("previewStage");
  if (!previewItem || !image.naturalWidth || image.hidden) return;
  const quarter = previewItem.rotation % 180 !== 0;
  const width = quarter ? image.naturalHeight : image.naturalWidth, height = quarter ? image.naturalWidth : image.naturalHeight;
  const availableWidth = Math.max(30, stage.clientWidth - 36), availableHeight = Math.max(30, stage.clientHeight - 36);
  if (fitMode) previewScale = fitMode === "width" ? availableWidth / width : Math.min(availableWidth / width, availableHeight / height);
  previewScale = Math.max(.05, Math.min(8, previewScale));
  $("previewCanvas").style.width = width * previewScale + "px"; $("previewCanvas").style.height = height * previewScale + "px";
  image.style.width = image.naturalWidth * previewScale + "px"; image.style.height = image.naturalHeight * previewScale + "px";
  image.style.transform = "translate(-50%, -50%) " + imageTransform(previewItem);
  $("previewZoomLabel").textContent = Math.round(previewScale * 100) + "%";
  $("previewFit").classList.toggle("active", fitMode === "page"); $("previewFitWidth").classList.toggle("active", fitMode === "width");
  if (fitMode) stage.scrollTo(0, 0);
}
function zoomPreview(factor, clientX, clientY) {
  if (!$("previewDialog").open || $("previewImage").hidden) return;
  const stage = $("previewStage"), canvas = $("previewCanvas"), before = canvas.getBoundingClientRect(), viewport = stage.getBoundingClientRect();
  const x = clientX ?? viewport.left + stage.clientWidth / 2, y = clientY ?? viewport.top + stage.clientHeight / 2;
  const fractionX = (x - before.left) / before.width, fractionY = (y - before.top) / before.height;
  fitMode = null; previewScale *= factor; drawPreview();
  const after = canvas.getBoundingClientRect();
  stage.scrollLeft += after.left + fractionX * after.width - x;
  stage.scrollTop += after.top + fractionY * after.height - y;
}
async function poll() {
  if (polling || busy) return;
  polling = true;
  try {apply(await call("get_state"));} catch (error) {$("status").textContent = String(error);}
  finally {polling = false; pump();}
}
$("add").onclick = $("emptyAdd").onclick = () => action("choose_files");
$("clear").onclick = () => action("clear_files"); $("browse").onclick = () => action("choose_output");
$("cancel").onclick = () => action("cancel_conversion");
$("export").onclick = () => action("start_plan", $("mode").value, outputPages().map(item => ({...item})));
$("mode").onchange = $("scope").onchange = sync;
$("selectAll").onclick = () => {const shown = visible(), remove = shown.every(item => selected.has(keyOf(item))); for (const item of shown) {if (remove) selected.delete(keyOf(item)); else selected.add(keyOf(item));} sync();};
$("rotateSelected").onclick = () => transformMenu(pages.filter(item => selected.has(keyOf(item))));
$("deleteSelected").onclick = () => edit(() => {pages = pages.filter(item => !selected.has(keyOf(item))); selected.clear();});
$("undo").onclick = undo;
for (const [id, list] of [["gridView", false], ["listView", true]]) $(id).onclick = () => {$("pages").classList.toggle("list-view", list); for (const name of ["gridView", "listView"]) {$(name).classList.toggle("active", name === id); $(name).setAttribute("aria-pressed", String(name === id));}};
$("closePreview").onclick = () => $("previewDialog").close();
$("previewZoomIn").onclick = () => zoomPreview(1.25); $("previewZoomOut").onclick = () => zoomPreview(.8);
$("previewFit").onclick = () => {fitMode = "page"; drawPreview();}; $("previewFitWidth").onclick = () => {fitMode = "width"; drawPreview();};
$("previewTransform").onclick = () => transformMenu([previewItem]);
$("closeTransform").onclick = () => $("transformDialog").close();
for (const button of document.querySelectorAll("[data-transform]")) button.onclick = () => transformPages(button.dataset.transform);
$("previewStage").addEventListener("wheel", event => {if (!event.ctrlKey && !event.metaKey) return; event.preventDefault(); const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? $("previewStage").clientHeight : 1; zoomPreview(Math.exp(-Math.max(-100, Math.min(100, event.deltaY * units)) * .008), event.clientX, event.clientY);}, {passive:false});
const touches = new Map();
$("previewStage").addEventListener("pointerdown", event => {if (event.pointerType !== 'touch') return; touches.set(event.pointerId, {x:event.clientX,y:event.clientY}); $("previewStage").setPointerCapture(event.pointerId);});
$("previewStage").addEventListener("pointermove", event => {
  if (!touches.has(event.pointerId)) return;
  const before = [...touches.values()], old = touches.get(event.pointerId);
  touches.set(event.pointerId, {x:event.clientX,y:event.clientY});
  const after = [...touches.values()];
  if (after.length === 2) {
    const distance = points => Math.hypot(points[0].x-points[1].x,points[0].y-points[1].y);
    if (distance(before)>0) zoomPreview(distance(after)/distance(before),(after[0].x+after[1].x)/2,(after[0].y+after[1].y)/2);
  } else if (after.length === 1) {$("previewStage").scrollLeft -= event.clientX-old.x; $("previewStage").scrollTop -= event.clientY-old.y;}
});
for (const name of ['pointerup','pointercancel','lostpointercapture']) $("previewStage").addEventListener(name,event=>touches.delete(event.pointerId));
new ResizeObserver(() => {if ($("previewDialog").open && fitMode) drawPreview();}).observe($("previewStage"));
document.addEventListener("wheel", event => {if (event.ctrlKey || event.metaKey) event.preventDefault();}, {passive:false});
document.addEventListener("keydown", event => {if ((event.ctrlKey || event.metaKey) && ['+', '=', '-', '0'].includes(event.key)) {event.preventDefault(); if ($("previewDialog").open && !$("transformDialog").open) {if (event.key === '0') {fitMode='page'; drawPreview();} else zoomPreview(event.key === '-' ? .8 : 1.25);}}});
$("previewDialog").addEventListener("close", () => {previewSequence++; touches.clear(); pump();});
$("done").onclick = () => $("resultDialog").close(); $("openOutput").onclick = () => action("open_output");
document.addEventListener("keydown", event => {if (event.ctrlKey && event.key.toLowerCase() === "z" && !["INPUT", "SELECT"].includes(event.target.tagName) && !document.querySelector("dialog[open]")) {event.preventDefault(); undo();}});
document.addEventListener("dragover", event => {if (dragged) return; event.preventDefault(); event.dataTransfer.dropEffect = locked() ? "none" : "copy"; document.body.classList.toggle("drag-active", !locked());});
document.addEventListener("dragleave", event => {if (!event.relatedTarget) document.body.classList.remove("drag-active");});
document.addEventListener("drop", event => {event.preventDefault(); document.body.classList.remove("drag-active"); if (!locked() && !dragged && event.dataTransfer.files.length) window.parent.forwardPDFDrop(event.dataTransfer);});
window.addEventListener("pywebviewready", () => {poll(); setInterval(poll, 400);});
sync();
