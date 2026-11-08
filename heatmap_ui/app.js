"use strict";
let currentSettings = null;
window.heatmapBusy = false;
const byId = id => document.getElementById(id);
const fields = ["title", "x_axis_title", "y_axis_title", "color_min", "color_max", "grid_rows", "grid_cols", "dpi", "figure_width", "figure_height", "output_path", "show_sensor_labels", "show_sensor_markers", "area_width", "area_height", "area_unit", "estimation_method", "idw_power", "layout_grid_visible", "layout_snap", "layout_grid_spacing"];
const numbers = new Set(["color_min", "color_max", "grid_rows", "grid_cols", "dpi", "figure_width", "figure_height", "area_width", "area_height", "idw_power", "layout_grid_spacing"]);
for (let index = 0; index < 6; index++) {
  const label = document.createElement("div");
  label.className = "sensor-row";
  label.innerHTML = `<div class="sensor-main"><input id="name${index + 1}" type="text" maxlength="32" required aria-label="Point ${index + 1} name"><input id="t${index + 1}" type="number" step="any" required aria-label="Point ${index + 1} temperature in Celsius"><button type="button" class="coordinate-toggle" aria-expanded="false" aria-controls="coordinates${index+1}" aria-label="Edit point ${index+1} coordinates"><span aria-hidden="true">›</span>Position</button></div><div id="coordinates${index+1}" class="coordinate-fields" hidden><label>X<input id="x${index + 1}" type="number" min="0" step="any" required aria-label="Point ${index + 1} X position"></label><label>Y<input id="y${index + 1}" type="number" min="0" step="any" required aria-label="Point ${index + 1} Y position"></label></div>`;
  label.querySelector(".coordinate-toggle").addEventListener("click",event=>{
    const button=event.currentTarget, panel=byId(button.getAttribute("aria-controls"));
    panel.hidden=!panel.hidden; button.setAttribute("aria-expanded",String(!panel.hidden));
  });
  byId("sensorGrid").append(label);
}
function status(message, kind = "") { byId("status").textContent = message; byId("status").className = kind; }
let layout = null, draggingPoint = null, gridSignature = "", selectedLayoutPoint = 0;
let layoutZoom = 1, layoutPan = null;
const svgNS = "http://www.w3.org/2000/svg";
function layoutPixelScale() {
  const svg=byId("pointLayout");
  return Math.min(svg.clientWidth/320,svg.clientHeight/200)||1;
}
function updateModel() {
  const idw = byId("estimation_method").value === "idw";
  byId("powerField").hidden = !idw;
  byId("idw_power").disabled = window.heatmapBusy || !idw;
  byId("idw_power").required = idw;
  byId("modelHelp").textContent = idw ? "IDW: T = Σ(Ti / diᵖ) / Σ(1 / diᵖ). Nearer points have more influence. Power 2 is the default." : byId("estimation_method").value==="smooth" ? "Smooth cubic interpolation removes abrupt slope changes within the measured region. Estimates can exceed measured min/max. The outer coverage still follows the sensor boundary." : "Linear interpolation has straight-sided color transitions. Choose Smooth for gentler transitions. Outside the measured region stays blank.";
  for (const point of byId("pointLayout").querySelectorAll(".layout-point")) {
    point.setAttribute("tabindex", window.heatmapBusy ? "-1" : "0");
    point.setAttribute("aria-disabled", String(window.heatmapBusy));
  }
}
function renderLayout() {
  const width = Number(byId("area_width").value), height = Number(byId("area_height").value);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return;
  const scale = Math.min(276 / width, 148 / height);
  layout = {x: (320 - width * scale) / 2, y: (184 - height * scale) / 2, w: width * scale, h: height * scale, width, height};
  const svg = byId("pointLayout");
  if (!svg.childElementCount) {
    svg.innerHTML = '<rect id="layoutArea" fill="#eaf3fc" stroke="#bfd5eb" rx="3"/><g id="placementGrid" class="placement-grid" aria-hidden="true"></g><text id="layoutOrigin" class="layout-axis">0, 0</text><text id="layoutSize" class="layout-axis" text-anchor="middle" x="160" y="195"></text>';
    for (let index=0; index<6; index++) {
      const group = document.createElementNS(svgNS,"g"); group.classList.add("layout-point"); group.dataset.point=index; group.setAttribute("role","button"); group.setAttribute("tabindex","0");
      const circle=document.createElementNS(svgNS,"circle"); circle.setAttribute("r","9");circle.setAttribute("vector-effect","non-scaling-stroke");
      const hit=document.createElementNS(svgNS,"circle");hit.classList.add("point-hit");
      const label=document.createElementNS(svgNS,"text"); label.setAttribute("text-anchor","middle"); label.setAttribute("y","3"); label.textContent=index+1;
      const title=document.createElementNS(svgNS,"title"); group.append(circle,hit,label,title); svg.append(group);
    }
  }
  for (const [key,value] of Object.entries({x:layout.x,y:layout.y,width:layout.w,height:layout.h})) byId("layoutArea").setAttribute(key,value);
  byId("layoutOrigin").setAttribute("x",layout.x); byId("layoutOrigin").setAttribute("y",Math.max(10,layout.y-7));
  byId("layoutSize").textContent=`${width} × ${height} ${byId("area_unit").value}`;
  const pixelScale=layoutPixelScale();
  for(const axis of svg.querySelectorAll(".layout-axis")) axis.style.fontSize=`${10/pixelScale}px`;
  byId("layoutArea").setAttribute("vector-effect","non-scaling-stroke");
  renderGrid();
  for (let index=0;index<6;index++) {
    const inputX=byId(`x${index+1}`),inputY=byId(`y${index+1}`);
    inputX.max=width; inputY.max=height;
    const x=inputX.valueAsNumber,y=inputY.valueAsNumber;
    const point=svg.querySelector(`[data-point="${index}"]`);
    point.querySelector("circle").setAttribute("r",9/pixelScale);
    point.querySelector(".point-hit").setAttribute("r",14/pixelScale);
    point.querySelector("text").style.fontSize=`${11/pixelScale}px`;
    point.querySelector("text").setAttribute("y",3.5/pixelScale);
    const valid=Number.isFinite(x)&&Number.isFinite(y)&&x>=0&&x<=width&&y>=0&&y<=height;
    point.classList.toggle("invalid",!valid);
    point.setAttribute("transform",`translate(${layout.x+Math.max(0,Math.min(width,Number.isFinite(x)?x:0))/width*layout.w},${layout.y+Math.max(0,Math.min(height,Number.isFinite(y)?y:0))/height*layout.h})`);
    const name=byId(`name${index+1}`).value || `Point ${index+1}`;
    const label=`${name}: X ${inputX.value}, Y ${inputY.value}. Drag or use arrow keys to move.`;
    point.setAttribute("aria-label",label); point.querySelector("title").textContent=label;
  }
  renderLayoutSummary();
  const mini=byId("layoutMini"),clone=svg.cloneNode(true);
  for (const element of clone.querySelectorAll("[id]")) element.removeAttribute("id");
  for (const point of clone.querySelectorAll(".layout-point")) {
    point.querySelector(".point-hit").remove();
    point.querySelector("circle").setAttribute("r","9");
    point.querySelector("text").style.fontSize="10px";
    point.querySelector("text").setAttribute("y","3.5");
    point.classList.remove("layout-point");point.classList.add("layout-preview-point");
    for (const attribute of ["tabindex","role","data-point","aria-disabled"]) point.removeAttribute(attribute);
  }
  mini.replaceChildren(...clone.childNodes);
}
function renderLayoutSummary() {
  const list=byId("layoutPointList");
  if (!list.childElementCount) for(let index=0;index<6;index++) {
    const button=document.createElement("button");button.type="button";button.className="layout-point-item";
    button.append(document.createElement("span"),document.createElement("span"));
    button.onclick=()=>{selectedLayoutPoint=index;renderLayoutSummary();const point=byId("pointLayout").querySelector(`[data-point="${index}"]`);point.scrollIntoView({block:"nearest",inline:"nearest"});point.focus({preventScroll:true});};
    list.append(button);
  }
  for (const [index,button] of [...list.children].entries()) {
    button.children[0].textContent=byId(`name${index+1}`).value||`Point ${index+1}`;
    button.children[1].textContent=`${byId(`t${index+1}`).value} °C`;
    button.classList.toggle("is-selected",index===selectedLayoutPoint);
    byId("pointLayout").querySelector(`[data-point="${index}"]`).classList.toggle("is-selected",index===selectedLayoutPoint);
  }
  byId("layoutPointName").textContent=byId(`name${selectedLayoutPoint+1}`).value||`Point ${selectedLayoutPoint+1}`;
  byId("layoutPointCoordinates").textContent=`X ${byId(`x${selectedLayoutPoint+1}`).value} · Y ${byId(`y${selectedLayoutPoint+1}`).value} ${byId("area_unit").value}`;
}
function openLayout() {
  if (window.heatmapBusy||byId("layoutDialog").open) return;
  byId("layoutDialog").showModal(); fitLayout();
}
byId("openLayout").addEventListener("click",openLayout);
byId("closeLayout").addEventListener("click",()=>byId("layoutDialog").close());
byId("layoutDialog").addEventListener("close",()=>{draggingPoint=null;layoutPan=null;layoutTouches.clear();renderLayout();byId("openLayout").focus();});
byId("layoutDialog").addEventListener("input",()=>markChanged());
byId("layoutDialog").addEventListener("invalid",()=>openLayout(),true);
new ResizeObserver(()=>{if(byId("layoutDialog").open) applyLayoutZoom();}).observe(byId("layoutViewport"));
function applyLayoutZoom() {
  const viewport=byId("layoutViewport"), bounds=viewport.getBoundingClientRect(), canvas=byId("layoutZoomCanvas");
  canvas.style.width=Math.max(1,bounds.width-2)*layoutZoom+"px";
  canvas.style.height=Math.max(1,bounds.height-2)*layoutZoom+"px";
  byId("layoutZoomLabel").textContent=`${Math.round(layoutZoom*100)}%`;
  byId("layoutZoomIn").disabled=layoutZoom>=8;byId("layoutZoomOut").disabled=layoutZoom<=.5;
  byId("layoutFit").classList.toggle("active",layoutZoom===1);
  gridSignature="";renderLayout();
}
function fitLayout(){layoutZoom=1;applyLayoutZoom();byId("layoutViewport").scrollTo(0,0);}
function zoomLayout(factor,clientX,clientY) {
  if(!byId("layoutDialog").open)return;
  const viewport=byId("layoutViewport"),canvas=byId("layoutZoomCanvas"),before=canvas.getBoundingClientRect(),bounds=viewport.getBoundingClientRect();
  const x=clientX??bounds.left+viewport.clientWidth/2,y=clientY??bounds.top+viewport.clientHeight/2;
  const fx=(x-before.left)/before.width,fy=(y-before.top)/before.height;
  layoutZoom=Math.max(.5,Math.min(8,layoutZoom*factor));applyLayoutZoom();
  const after=canvas.getBoundingClientRect();viewport.scrollLeft+=after.left+fx*after.width-x;viewport.scrollTop+=after.top+fy*after.height-y;
}
byId("layoutZoomIn").onclick=()=>zoomLayout(1.25);byId("layoutZoomOut").onclick=()=>zoomLayout(.8);byId("layoutFit").onclick=fitLayout;
byId("layoutViewport").addEventListener("wheel",event=>{event.preventDefault();const units=event.deltaMode===1?16:event.deltaMode===2?byId("layoutViewport").clientHeight:1;zoomLayout(Math.exp(-Math.max(-100,Math.min(100,event.deltaY*units))*.008),event.clientX,event.clientY);},{passive:false});
byId("layoutViewport").addEventListener("pointerdown",event=>{if(event.button!==0||event.target.closest(".layout-point")||layoutTouches.size>1)return;layoutPan={id:event.pointerId,x:event.clientX,y:event.clientY};byId("layoutViewport").setPointerCapture(event.pointerId);byId("layoutViewport").classList.add("is-panning");event.preventDefault();});
byId("layoutViewport").addEventListener("pointermove",event=>{if(!layoutPan||layoutPan.id!==event.pointerId||layoutTouches.size>1)return;byId("layoutViewport").scrollLeft-=event.clientX-layoutPan.x;byId("layoutViewport").scrollTop-=event.clientY-layoutPan.y;layoutPan.x=event.clientX;layoutPan.y=event.clientY;});
const layoutTouches=new Map();
byId("layoutViewport").addEventListener("pointerdown",event=>{if(event.pointerType!=="touch")return;layoutTouches.set(event.pointerId,{x:event.clientX,y:event.clientY});if(layoutTouches.size>1){draggingPoint=null;layoutPan=null;byId("layoutViewport").setPointerCapture(event.pointerId);event.preventDefault();event.stopPropagation();}},true);
byId("layoutViewport").addEventListener("pointermove",event=>{if(!layoutTouches.has(event.pointerId))return;const before=[...layoutTouches.values()];layoutTouches.set(event.pointerId,{x:event.clientX,y:event.clientY});if(layoutTouches.size!==2)return;const after=[...layoutTouches.values()],distance=points=>Math.hypot(points[0].x-points[1].x,points[0].y-points[1].y);if(distance(before)>0)zoomLayout(distance(after)/distance(before),(after[0].x+after[1].x)/2,(after[0].y+after[1].y)/2);event.preventDefault();event.stopPropagation();},true);
for(const name of ["pointerup","pointercancel","lostpointercapture"])byId("layoutViewport").addEventListener(name,event=>{layoutTouches.delete(event.pointerId);if(layoutPan?.id===event.pointerId)layoutPan=null;byId("layoutViewport").classList.remove("is-panning");},true);
function gridSpacing() {
  const spacing=byId("layout_grid_spacing").valueAsNumber;
  return Number.isFinite(spacing)&&spacing>=1e-12&&spacing<=1e9 ? spacing : null;
}
function renderGrid() {
  const grid=byId("placementGrid"), spacing=gridSpacing();
  byId("gridUnit").textContent=byId("area_unit").value;
  if (!spacing) {grid.replaceChildren(); gridSignature=""; byId("gridStatus").textContent="Enter a positive grid spacing before moving points.";return;}
  const nx=Math.floor(layout.width/spacing), ny=Math.floor(layout.height/spacing);
  const pixelScale=layoutPixelScale();
  const dense=nx+ny>160 || Math.min(spacing/layout.width*layout.w,spacing/layout.height*layout.h)*pixelScale<3;
  const signature=[layout.width,layout.height,spacing,byId("layout_grid_visible").checked,dense].join(":");
  if (signature!==gridSignature) {
    gridSignature=signature; grid.replaceChildren();
  if (byId("layout_grid_visible").checked && !dense) {
    for (const [axis,count] of [["x",nx],["y",ny]]) for (let index=1;index<=count;index++) {
      const line=document.createElementNS(svgNS,"line");
      line.setAttribute("vector-effect","non-scaling-stroke");
      const coordinate=axis==="x"?layout.x+index*spacing/layout.width*layout.w:layout.y+index*spacing/layout.height*layout.h;
      for (const [key,value] of Object.entries(axis==="x"?{x1:coordinate,x2:coordinate,y1:layout.y,y2:layout.y+layout.h}:{y1:coordinate,y2:coordinate,x1:layout.x,x2:layout.x+layout.w})) line.setAttribute(key,value);
      grid.append(line);
    }
  }
  }
  const snap=byId("layout_snap").checked;
  byId("gridStatus").textContent=byId("layout_grid_visible").checked&&dense ? `Grid is too dense to display. ${snap?"Snap still uses":"Spacing:"} ${spacing} ${byId("area_unit").value}.` : `Spacing: ${spacing} ${byId("area_unit").value} · Snap ${snap?"on":"off"}. Typed X/Y values stay exact.`;
}
function snapCoordinate(value,bound,spacing) {
  const clamped=Math.max(0,Math.min(bound,value));
  let target=Math.max(0,Math.min(bound,Math.round(clamped/spacing)*spacing));
  if (bound-clamped<Math.abs(target-clamped)) target=bound;
  return target===bound?bound:Math.max(0,Math.min(bound,Number(target.toPrecision(12))));
}
function movePoint(index,x,y) {
  if (!layout || window.heatmapBusy) return;
  const spacing=gridSpacing(), snap=byId("layout_snap").checked;
  if (snap && !spacing) {byId("gridStatus").textContent="Enter a positive grid spacing before snapping.";return;}
  x=snap?snapCoordinate(x,layout.width,spacing):Math.max(0,Math.min(layout.width,Number(x.toPrecision(12))));
  y=snap?snapCoordinate(y,layout.height,spacing):Math.max(0,Math.min(layout.height,Number(y.toPrecision(12))));
  if (snap) for (let other=0;other<6;other++) if (other!==index && Math.abs(byId(`x${other+1}`).valueAsNumber-x)/layout.width<1e-9 && Math.abs(byId(`y${other+1}`).valueAsNumber-y)/layout.height<1e-9) {
    byId("gridStatus").textContent="That grid position is occupied. Choose another intersection."; return;
  }
  byId(`x${index+1}`).value=x;
  byId(`y${index+1}`).value=y;
  markChanged();
}
byId("pointLayout").addEventListener("pointerdown",event=>{
  const point=event.target.closest(".layout-point");
  if (!point||window.heatmapBusy) return;
  draggingPoint=Number(point.dataset.point); selectedLayoutPoint=draggingPoint; renderLayoutSummary(); point.focus({preventScroll:true}); byId("pointLayout").setPointerCapture(event.pointerId); event.preventDefault();event.stopPropagation();
});
byId("pointLayout").addEventListener("pointermove",event=>{
  if (draggingPoint===null||!layout) return;
  const position=new DOMPoint(event.clientX,event.clientY).matrixTransform(byId("pointLayout").getScreenCTM().inverse());
  movePoint(draggingPoint,(position.x-layout.x)/layout.w*layout.width,(position.y-layout.y)/layout.h*layout.height);
});
for (const name of ["pointerup","pointercancel","lostpointercapture"]) byId("pointLayout").addEventListener(name,()=>draggingPoint=null);
byId("pointLayout").addEventListener("keydown",event=>{
  const point=event.target.closest(".layout-point");
  if (!point||!layout||window.heatmapBusy||!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(event.key)) return;
  event.preventDefault(); const index=Number(point.dataset.point),step=event.shiftKey ? 0.05 : 0.01;
  selectedLayoutPoint=index;
  const dx=event.key==="ArrowRight"?1:event.key==="ArrowLeft"?-1:0,dy=event.key==="ArrowDown"?1:event.key==="ArrowUp"?-1:0;
  const next=(value,bound,direction)=>{
    if (!direction) return value;
    const spacing=gridSpacing();
    if (!byId("layout_snap").checked||!spacing) return value+direction*bound*step;
    const start=direction>0?Math.floor(value/spacing+1e-9):Math.ceil(value/spacing-1e-9);
    return (start+direction*(event.shiftKey?5:1))*spacing;
  };
  movePoint(index,next(byId(`x${index+1}`).valueAsNumber,layout.width,dx),next(byId(`y${index+1}`).valueAsNumber,layout.height,dy));
});
function populate(settings) {
  currentSettings = settings;
  fields.forEach(key => { const element = byId(key); if (element.type === "checkbox") element.checked = settings[key]; else element.value = settings[key]; });
  byId("output_path").title=byId("output_path").value;
  settings.temperatures.flat().forEach((value, index) => byId(`t${index + 1}`).value = String(value));
  settings.sensor_names.forEach((name, index) => byId(`name${index + 1}`).value = name);
  settings.sensor_positions.forEach(([x, y], index) => {byId(`x${index + 1}`).value = x; byId(`y${index + 1}`).value = y;});
  updateScale(); renderLayout(); updateModel();
}
function collect() {
  const settings = {...currentSettings};
  fields.forEach(key => { const element = byId(key); settings[key] = element.type === "checkbox" ? element.checked : numbers.has(key) ? (element.value.trim() === "" ? null : Number(element.value)) : element.value; });
  const values = Array.from({length: 6}, (_, index) => byId(`t${index + 1}`).valueAsNumber);
  settings.temperatures = [values.slice(0, 3), values.slice(3)];
  settings.sensor_names = Array.from({length:6}, (_, index) => byId(`name${index + 1}`).value);
  settings.sensor_positions = Array.from({length:6}, (_, index) => [byId(`x${index + 1}`).valueAsNumber, byId(`y${index + 1}`).valueAsNumber]);
  return settings;
}
function updateScale() { byId("scaleLow").textContent = `${byId("color_min").value} °C`; byId("scaleHigh").textContent = `${byId("color_max").value} °C`; }
let previewZoom = 1;
function applyZoom() {
  const image = byId("previewImage"), stage = byId("previewSurface"), canvas = byId("previewCanvas");
  if (image.hidden || !image.naturalWidth) return;
  const availableWidth = Math.max(1, stage.clientWidth - 32), availableHeight = Math.max(1, stage.clientHeight - 32);
  const fit = Math.min(availableWidth / image.naturalWidth, availableHeight / image.naturalHeight);
  const width = image.naturalWidth * fit * previewZoom, height = image.naturalHeight * fit * previewZoom;
  image.style.width = `${width}px`; image.style.height = `${height}px`;
  canvas.style.width = `${Math.max(stage.clientWidth - 1, width + 28)}px`;
  canvas.style.height = `${Math.max(stage.clientHeight - 1, height + 28)}px`;
  byId("zoomLabel").textContent = `${Math.round(previewZoom * 100)}%`;
}
function zoomPreview(nextZoom, clientX, clientY) {
  const image = byId("previewImage"), stage = byId("previewSurface");
  if (image.hidden || !image.naturalWidth) return;
  const before = image.getBoundingClientRect(), viewport = stage.getBoundingClientRect();
  const x = clientX ?? viewport.left + stage.clientWidth / 2, y = clientY ?? viewport.top + stage.clientHeight / 2;
  const fractionX = Math.max(0, Math.min(1, (x - before.left) / before.width));
  const fractionY = Math.max(0, Math.min(1, (y - before.top) / before.height));
  previewZoom = Math.max(.25, Math.min(4, nextZoom));
  applyZoom();
  const after = image.getBoundingClientRect();
  stage.scrollLeft += after.left + fractionX * after.width - x;
  stage.scrollTop += after.top + fractionY * after.height - y;
}
function fitPreview() {
  previewZoom = 1; applyZoom();
  byId("previewSurface").scrollTo(0, 0);
}
byId("previewImage").addEventListener("load", fitPreview);
new ResizeObserver(applyZoom).observe(byId("previewSurface"));
byId("zoomIn").addEventListener("click", () => zoomPreview(previewZoom + .25));
byId("zoomOut").addEventListener("click", () => zoomPreview(previewZoom - .25));
byId("fitBtn").addEventListener("click", fitPreview);
byId("previewSurface").addEventListener("wheel", event => {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  if (window.heatmapBusy) return;
  const units = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? byId("previewSurface").clientHeight : 1;
  const delta = Math.max(-100, Math.min(100, event.deltaY * units));
  zoomPreview(previewZoom * Math.exp(-delta * .008), event.clientX, event.clientY);
}, {passive:false});
function busy(value) {
  window.heatmapBusy = value;
  document.querySelectorAll("input, button, select").forEach(element => { element.disabled = value; });
  byId("previewSurface").classList.toggle("busy", value);
  byId("export").innerHTML = value ? "Working…" : "Export PNG <span>↗</span>";
  updateModel();
}
async function generate(exportImage = false) {
  if (window.heatmapBusy || !currentSettings) return;
  if (!byId("settingsForm").reportValidity()) return;
  const settings = collect();
  let completion = null;
  busy(true); status(exportImage ? "Rendering high-resolution PNG…" : "Updating heatmap…");
  try {
    const result = await window.pywebview.api.generate(settings, exportImage);
    if (result.error) throw new Error(result.error);
    byId("previewImage").src = result.image;
    byId("previewImage").hidden = false;
    byId("loading").hidden = true;
    byId("previewSurface").classList.remove("stale");
    ["minimum", "maximum", "mean", "spread"].forEach(key => byId(key).textContent = `${result[key].toFixed(2)} °C`);
    byId("previewMeta").textContent = `${settings.grid_rows} × ${settings.grid_cols} grid`;
    byId("areaSummary").textContent = `${settings.area_width} × ${settings.area_height} ${settings.area_unit} · ${result.method}`;
    byId("previewState").textContent = "Preview up to date";
    byId("estimateNote").textContent = result.estimated ? "Estimated colors are not additional measurements. IDW is a spatial estimate, not a heat-transfer simulation." : settings.estimation_method==="smooth" ? "Smooth cubic estimates within the measured region. Values can exceed measured min/max; areas beyond the sensor boundary stay blank." : "Colors are interpolated only within the measured region. Areas beyond it are left blank.";
    currentSettings = settings;
    status(result.warning || (result.saved_path ? `Saved PNG: ${result.saved_path}` : "Preview updated. Ready to export."), result.warning ? "error" : "success");
    if (result.saved_path) completion = result;
  } catch (error) { status(error.message, "error"); }
  finally {
    busy(false);
    if (completion) {
      byId("exportSavedPath").textContent = completion.saved_path;
      byId("exportDialogMessage").textContent = completion.warning || "";
      byId("exportDialogMessage").hidden = !completion.warning;
      byId("exportDialog").showModal();
    }
  }
}
byId("completionDone").addEventListener("click", () => byId("exportDialog").close());
byId("exportDialog").addEventListener("close", () => byId("export").focus());
byId("completionOpenOutput").addEventListener("click", async () => {
  const button = byId("completionOpenOutput");
  button.disabled = true;
  try {
    const result = await window.pywebview.api.open_output();
    if (result.error) throw new Error(result.error);
    byId("exportDialog").close();
  } catch (error) {
    byId("exportDialogMessage").textContent = error.message;
    byId("exportDialogMessage").hidden = false;
  } finally { button.disabled = false; }
});
byId("settingsForm").addEventListener("submit", event => { event.preventDefault(); generate(); });
function markChanged() { updateScale(); renderLayout(); updateModel(); byId("previewSurface").classList.add("stale"); byId("previewState").textContent = "Inputs changed - Update preview"; }
byId("settingsForm").addEventListener("input", markChanged);
byId("settingsForm").addEventListener("invalid", event => {
  const coordinates=event.target.closest(".coordinate-fields");
  if (coordinates) {coordinates.hidden=false;coordinates.closest(".sensor-row").querySelector(".coordinate-toggle").setAttribute("aria-expanded","true");}
  for (let parent = event.target.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === "DETAILS") parent.open = true;
  }
}, true);
byId("navToggle").addEventListener("click", () => {
  const expanded=document.body.classList.toggle("nav-expanded");
  byId("navToggle").setAttribute("aria-expanded",String(expanded));
  byId("navToggle").setAttribute("aria-label",expanded?"Collapse menu":"Expand menu");
  byId("navToggle").title=expanded?"Collapse menu":"Expand menu";
});
byId("export").addEventListener("click", () => generate(true));
byId("reset").addEventListener("click", async () => { try { populate((await window.pywebview.api.defaults()).settings); await generate(); } catch (error) { status(error.message, "error"); } });
byId("output_path").addEventListener("input",()=>{byId("output_path").title=byId("output_path").value;});
byId("browse").addEventListener("click", async () => { try { const result = await window.pywebview.api.choose_output(); if (result.output_path) {byId("output_path").value = result.output_path;byId("output_path").title=result.output_path;} } catch (error) { status(error.message, "error"); } });
busy(true);
window.addEventListener("pywebviewready", async () => {
  try { const result = await window.pywebview.api.get_settings(); populate(result.settings); busy(false); await generate(); if (result.warning) status(result.warning, "error"); }
  catch (error) { busy(false); status(error.message, "error"); }
});
