"use strict";
const $ = id => document.getElementById(id);
let state = {files: [], running: false}, selectedId = null, currentPage = 0, pageCount = 0;
let previewSequence = 0, fileSignature = "", zoom = 1, fitted = true, bridgeBusy = false, polling = false;
let toastTimer, lastWarning = "";
let settingsInitialized = false, lastCompletionId = null;
let settingsSaveQueue = Promise.resolve();
let fitWidth = 0;
let startupAcknowledged = false;
let selectionQueue = Promise.resolve(), selectionOwner = null;
const pageDrafts = new Map();

function syncPageSelection() {
  const file = state.files.find(file => file.id === selectedId);
  if (selectionOwner !== selectedId) {
    selectionOwner = selectedId;
    const draft = file && pageDrafts.get(file.id);
    $("pageMode").value = draft?.mode ?? file?.page_mode ?? "all";
    $("pageSelection").value = draft?.selection ?? (file?.page_mode === "custom" ? file.page_selection : "") ?? "";
  }
  const mode = $("pageMode").value;
  $("pageMode").disabled = state.running || bridgeBusy || !file?.pages;
  $("pageSelection").disabled = state.running || bridgeBusy || !file?.pages;
  $("pageSelection").hidden = mode !== "custom";
  $("pageSelectionHint").textContent = mode === "current" && file ? `Page ${currentPage + 1}` : "";
}

function pageChoice() {
  return {selection: $("pageSelection").value, mode: $("pageMode").value, currentPage: currentPage + 1};
}

function savePageSelection() {
  const fileId = selectedId, value = pageChoice();
  if (!fileId || state.running || !state.files.find(file => file.id === fileId)?.pages) return selectionQueue;
  pageDrafts.set(fileId, value);
  selectionQueue = selectionQueue.catch(() => {}).then(async () => {
    const result = await call("set_page_selection", fileId, value.selection, value.mode, value.currentPage);
    if (result.error) throw new Error(result.error);
    if (pageDrafts.get(fileId) === value) pageDrafts.delete(fileId);
    applyState(result);
  });
  return selectionQueue;
}

function setMenuExpanded(expanded) {
  document.body.classList.toggle("nav-expanded", expanded);
  $("navToggle").setAttribute("aria-expanded", String(expanded));
  $("navToggle").setAttribute("aria-label", expanded ? "Collapse menu" : "Expand menu");
  $("navToggle").title = expanded ? "Collapse menu" : "Expand menu";
}

function notify(message) {
  if ($("completionDialog").open) {
    $("completionNote").textContent = message;
    return;
  }
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 6500);
}

async function call(method, ...args) {
  if (!window.pywebview?.api) throw new Error("The desktop connection is not ready yet.");
  return window.pywebview.api[method](...args);
}

async function action(method, ...args) {
  if (bridgeBusy) return;
  bridgeBusy = true;
  syncButtons();
  try {
    const result = await call(method, ...args);
    if (result.error) notify(result.error);
    else if (result.files) applyState(result);
  } catch (error) { notify(String(error)); }
  finally { bridgeBusy = false; syncButtons(); }
}

function syncButtons() {
  const locked = state.running || bridgeBusy;
  syncPageSelection();
  $("cancelBtn").hidden = !state.running;
  $("cancelBtn").disabled = !!state.cancelling;
  $("cancelBtn").textContent = state.cancelling ? "Cancelling…" : "Cancel conversion";
  for (const id of ["addBtn", "emptyAddBtn", "clearBtn", "browseBtn", "dpi", "quality", "imageFormat"]) $(id).disabled = locked;
  const imageFormat = $("imageFormat").value;
  const formatLabel = imageFormat === "webp" ? "WebP" : imageFormat.toUpperCase();
  $("quality").disabled = locked || imageFormat === "png";
  $("qualityField").classList.toggle("is-lossless", imageFormat === "png");
  $("qualityField").title = imageFormat === "png" ? "PNG is lossless; quality does not apply." : "Compression quality (1–100)";
  $("formatBadge").textContent = formatLabel;
  $("previewFormat").textContent = "PDF → " + formatLabel;
  $("clearBtn").disabled = locked || !state.files.length;
  $("convertBtn").disabled = locked || !state.files.length;
  $("convertBtn").firstChild.textContent = state.running ? "Converting… " : "Convert to " + formatLabel + " ";
  for (const button of document.querySelectorAll(".remove-file")) button.disabled = locked;
  $("prevPage").disabled = !pageCount || currentPage <= 0;
  $("nextPage").disabled = !pageCount || currentPage >= pageCount - 1;
  for (const id of ["zoomIn", "zoomOut", "fitBtn"]) $(id).disabled = !pageCount;
}

function applyState(next) {
  state = next;
  if (!settingsInitialized) {
    $("dpi").value = state.dpi;
    $("quality").value = state.quality;
    $("imageFormat").value = state.image_format;
    setMenuExpanded(state.sidebar_expanded);
    settingsInitialized = true;
  }
  $("fileCount").textContent = state.files.length;
  $("outputPath").value = state.output;
  $("outputPath").title = state.output;
  $("inputPath").textContent = state.input;
  $("inputPath").title = "Last input folder: " + state.input;
  $("statusText").textContent = state.message;
  $("statusText").title = state.message;
  const progress = Math.min(100, Math.max(0, state.progress));
  $("progressBar").style.width = progress + "%";
  $("progressTrack").setAttribute("aria-valuenow", Math.round(progress));
  $("progressLabel").textContent = progress > 0 || state.running ? Math.round(progress) + "%" : "";
  if (state.warning && state.warning !== lastWarning) { lastWarning = state.warning; notify(state.warning); }
  if (!state.files.some(file => file.id === selectedId)) {
    selectedId = state.files[0]?.id || null;
    currentPage = 0;
    loadPreview();
  }
  const signature = JSON.stringify(state.files) + selectedId;
  if (signature !== fileSignature) { fileSignature = signature; renderFiles(); }
  syncButtons();
  if (state.result && state.result.id !== lastCompletionId) {
    lastCompletionId = state.result.id;
    showCompletion(state.result);
  }
}

function showCompletion(result) {
  $("toast").hidden = true;
  clearTimeout(toastTimer);
  const hasErrors = result.failed > 0;
  $("completionTitle").textContent = hasErrors ? (result.completed ? "Completed with errors" : "Conversion failed") : "Conversion complete";
  $("completionIcon").textContent = hasErrors ? "!" : "✓";
  $("completionIcon").classList.toggle("has-errors", hasErrors);
  $("completionSummary").textContent = hasErrors ? (result.completed ? "Some documents could not be converted." : "No documents could be converted.") : "Your document images are ready.";
  $("resultImages").textContent = result.images;
  $("resultCompleted").textContent = result.completed;
  $("resultFailed").textContent = result.failed;
  $("completionNote").textContent = hasErrors ? "Check the document list for error details. Partially converted files may also have images in the output folder." : "Each PDF has its own folder. Your original files are unchanged.";
  if (result.cancelled) {
    $("completionTitle").textContent = "Conversion cancelled";
    $("completionIcon").textContent = "−";
    $("completionSummary").textContent = `${result.cancelled} PDF(s) cancelled. ${result.images} images saved.`;
    $("completionNote").textContent = "Images already saved are kept. You can change pages or settings and convert again.";
  }
  $("completionPath").textContent = result.output;
  if (!$("completionDialog").open) $("completionDialog").showModal();
}

function renderFiles() {
  $("fileList").replaceChildren();
  $("queueEmpty").hidden = state.files.length > 0;
  for (const file of state.files) {
    const row = document.createElement("div");
    row.className = "file-row" + (file.id === selectedId ? " selected" : "");
    row.setAttribute("role", "button"); row.tabIndex = 0;
    row.setAttribute("aria-label", "Preview " + file.name);
    row.title = file.path;
    const icon = document.createElement("span"); icon.className = "pdf-icon"; icon.textContent = "PDF";
    const info = document.createElement("div"); info.className = "file-info";
    const name = document.createElement("div"); name.className = "file-name"; name.textContent = file.name;
    const meta = document.createElement("div"); meta.className = "file-meta";
    const pageLabels = {all: "All pages", current: `Page ${file.current_page}`, even: "Even pages", odd: "Odd pages"};
    meta.textContent = `${file.pages} ${file.pages === 1 ? "page" : "pages"} · ${formatSize(file.size)} · ${pageLabels[file.page_mode] ?? file.page_selection}`;
    const status = document.createElement("div"); status.className = "file-status " + file.status;
    status.textContent = file.detail; status.title = file.detail;
    info.append(name, meta, status);
    const remove = document.createElement("button"); remove.className = "remove-file";
    remove.setAttribute("aria-label", "Remove " + file.name); remove.title = "Remove file";
    remove.innerHTML = '<svg aria-hidden="true"><use href="#i-close"/></svg>';
    remove.addEventListener("click", event => { event.stopPropagation(); action("remove_file", file.id); });
    const choose = () => { if (selectedId !== file.id) { selectedId = file.id; currentPage = 0; renderFiles(); syncButtons(); loadPreview(); } };
    row.addEventListener("click", choose);
    row.addEventListener("keydown", event => { if (event.target === row && ["Enter", " "].includes(event.key)) { event.preventDefault(); choose(); } });
    row.append(icon, info, remove); $("fileList").append(row);
  }
}

function formatSize(size) { return size >= 1048576 ? (size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(size / 1024)) + " KB"; }

async function loadPreview() {
  const sequence = ++previewSequence;
  pageCount = 0; zoom = 1; fitted = true; fitWidth = 0;
  $("previewImage").hidden = true; $("previewImage").removeAttribute("src");
  $("previewEmpty").hidden = !!selectedId;
  $("previewMessage").hidden = !selectedId;
  $("previewMessage").textContent = "Preparing your preview…";
  $("pageLabel").textContent = "— / —";
  $("fitBtn").textContent = "Fit";
  $("previewName").textContent = state.files.find(file => file.id === selectedId)?.name || "No document selected";
  syncButtons();
  if (!selectedId) return;
  try {
    const result = await call("preview", selectedId, currentPage);
    if (sequence !== previewSequence) return;
    if (result.error) { $("previewMessage").textContent = result.error; return; }
    currentPage = result.page; pageCount = result.pages;
    const image = $("previewImage");
    image.onload = () => { if (sequence === previewSequence) { $("previewMessage").hidden = true; image.hidden = false; applyZoom(); } };
    image.onerror = () => { if (sequence === previewSequence) { $("previewMessage").hidden = false; $("previewMessage").textContent = "The page image could not be displayed."; } };
    image.src = result.image;
    $("pageLabel").textContent = `${currentPage + 1} / ${pageCount}`;
    $("previewHint").textContent = "Page preview";
    syncButtons();
  } catch (error) { if (sequence === previewSequence) $("previewMessage").textContent = String(error); }
}

function applyZoom() {
  const image = $("previewImage");
  image.style.maxHeight = fitted ? "100%" : "none";
  image.style.maxWidth = fitted ? "100%" : "none";
  image.style.width = fitted ? "auto" : fitWidth * zoom + "px";
  if (fitted && !image.hidden) fitWidth = image.getBoundingClientRect().width;
  $("fitBtn").textContent = fitted ? "Fit" : Math.round(zoom * 100) + "%";
}

function zoomPreview(nextZoom, clientX, clientY) {
  const stage = $("previewStage"), image = $("previewImage");
  if (!pageCount || image.hidden) return;
  const before = image.getBoundingClientRect(), viewport = stage.getBoundingClientRect();
  const x = clientX ?? viewport.left + stage.clientWidth / 2;
  const y = clientY ?? viewport.top + stage.clientHeight / 2;
  const fractionX = Math.max(0, Math.min(1, (x - before.left) / before.width));
  const fractionY = Math.max(0, Math.min(1, (y - before.top) / before.height));
  if (fitted) fitWidth = before.width;
  zoom = Math.max(.25, Math.min(4, nextZoom));
  fitted = false;
  applyZoom();
  const after = image.getBoundingClientRect();
  stage.scrollLeft += after.left + fractionX * after.width - x;
  stage.scrollTop += after.top + fractionY * after.height - y;
}

$("previewStage").addEventListener("wheel", event => {
  // Chromium sends precision-touchpad pinch as Ctrl+wheel, without holding Ctrl.
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? $("previewStage").clientHeight : 1;
  const delta = Math.max(-100, Math.min(100, event.deltaY * units));
  zoomPreview(zoom * Math.exp(-delta * .008), event.clientX, event.clientY);
}, {passive: false});

async function poll() {
  if (polling || bridgeBusy) return;
  polling = true;
  try {
    applyState(await call("get_state"));
    if (!startupAcknowledged) {
      // Give the browser a frame to lay out the restored workspace before showing it.
      await new Promise(resolve => setTimeout(resolve, 0));
      await call("ready");
      startupAcknowledged = true;
    }
  }
  catch (error) { $("statusText").textContent = "Connection interrupted. " + String(error); }
  finally { polling = false; }
}

$("addBtn").onclick = $("emptyAddBtn").onclick = () => action("choose_files");
$("navToggle").onclick = () => {
  const expanded = !document.body.classList.contains("nav-expanded");
  setMenuExpanded(expanded);
  settingsSaveQueue = settingsSaveQueue.then(async () => {
    const result = await call("set_sidebar_expanded", expanded);
    if (result.error) notify(result.error);
    else state.sidebar_expanded = result.sidebar_expanded;
  }).catch(error => notify(String(error)));
};
$("clearBtn").onclick = () => action("clear_files");
$("browseBtn").onclick = () => action("choose_output");
$("pageSelection").addEventListener("input", () => {if (selectedId) pageDrafts.set(selectedId, pageChoice());});
$("pageMode").addEventListener("change", () => {
  if (selectedId) pageDrafts.set(selectedId, pageChoice());
  syncButtons();
  if ($("pageMode").value === "custom" && !$("pageSelection").value.trim()) {$("pageSelection").focus(); return;}
  savePageSelection().catch(error => notify(error.message));
});
$("pageSelection").addEventListener("change", () => {savePageSelection().catch(error => notify(error.message));});
$("cancelBtn").onclick = () => action("cancel_conversion");
$("completionDone").onclick = () => $("completionDialog").close();
$("completionOpen").onclick = () => action("open_output");
for (const id of ["dpi", "quality", "imageFormat"]) {
  $(id).addEventListener("change", () => {
    const dpi = Number($("dpi").value), quality = Number($("quality").value);
    const imageFormat = $("imageFormat").value;
    syncButtons();
    if (Number.isInteger(dpi) && dpi >= 36 && dpi <= 600 && Number.isInteger(quality) && quality >= 1 && quality <= 100) {
      // Save without disabling Convert when a field loses focus onto that button.
      settingsSaveQueue = settingsSaveQueue.then(async () => {
        const result = await call("update_settings", dpi, quality, imageFormat);
        if (result.error) notify(result.error);
        else { state.dpi = result.dpi; state.quality = result.quality; state.image_format = result.image_format; }
      }).catch(error => notify(String(error)));
    } else notify("Use DPI 36–600 and quality 1–100 (whole numbers).");
  });
}
$("convertBtn").onclick = async () => {
  const dpi = Number($("dpi").value), quality = Number($("quality").value);
  const imageFormat = $("imageFormat").value;
  if (!Number.isInteger(dpi) || dpi < 36 || dpi > 600 || !Number.isInteger(quality) || quality < 1 || quality > 100) {
    notify("Use DPI 36–600 and quality 1–100 (whole numbers)."); return;
  }
  await settingsSaveQueue;
  try {
    await savePageSelection();
    for (const [fileId, value] of pageDrafts) {
      if (!state.files.some(file => file.id === fileId)) {pageDrafts.delete(fileId); continue;}
      const result = await call("set_page_selection", fileId, value.selection, value.mode, value.currentPage);
      if (result.error) throw new Error(result.error);
      pageDrafts.delete(fileId);
    }
  } catch (error) {notify(error.message); return;}
  action("start_conversion", dpi, quality, imageFormat);
};
$("prevPage").onclick = () => { if (currentPage > 0) { currentPage--; loadPreview(); } };
$("nextPage").onclick = () => { if (currentPage < pageCount - 1) { currentPage++; loadPreview(); } };
$("fitBtn").onclick = () => { fitted = true; zoom = 1; applyZoom(); $("previewStage").scrollTo(0, 0); };
$("zoomIn").onclick = () => zoomPreview(zoom + .25);
$("zoomOut").onclick = () => zoomPreview(zoom - .25);
document.addEventListener("keydown", event => { if (event.ctrlKey && event.key.toLowerCase() === "o") { event.preventDefault(); if (!state.running) action("choose_files"); } });
window.addEventListener("pywebviewready", () => { poll(); setInterval(poll, 400); });
document.addEventListener("dragover", event => {
  event.preventDefault();
  event.dataTransfer.dropEffect = state.running ? "none" : "copy";
  document.body.classList.toggle("drag-active", !state.running);
});
document.addEventListener("dragleave", event => {if (!event.relatedTarget) document.body.classList.remove("drag-active");});
document.addEventListener("drop", event => {
  event.preventDefault(); document.body.classList.remove("drag-active");
  if (state.running) {notify("Wait for conversion to finish before adding PDFs."); return;}
  if (window.parent !== window) window.parent.forwardPDFDrop(event.dataTransfer);
});
syncButtons();
