"use strict";
let currentSettings = null;
window.heatmapBusy = false;
const byId = id => document.getElementById(id);
const fields = ["title", "x_axis_title", "y_axis_title", "color_min", "color_max", "grid_rows", "grid_cols", "dpi", "figure_width", "figure_height", "output_path", "show_sensor_labels", "show_sensor_markers", "area_width", "area_height", "area_unit"];
const numbers = new Set(["color_min", "color_max", "grid_rows", "grid_cols", "dpi", "figure_width", "figure_height", "area_width", "area_height"]);
for (let index = 0; index < 6; index++) {
  const label = document.createElement("div");
  label.className = "sensor-row";
  label.innerHTML = `<input id="name${index + 1}" type="text" maxlength="32" required aria-label="Point ${index + 1} name"><input id="t${index + 1}" type="number" step="any" required aria-label="Point ${index + 1} temperature in Celsius">`;
  byId("sensorGrid").append(label);
}
function status(message, kind = "") { byId("status").textContent = message; byId("status").className = kind; }
function populate(settings) {
  currentSettings = settings;
  fields.forEach(key => { const element = byId(key); if (element.type === "checkbox") element.checked = settings[key]; else element.value = settings[key]; });
  settings.temperatures.flat().forEach((value, index) => byId(`t${index + 1}`).value = String(value));
  settings.sensor_names.forEach((name, index) => byId(`name${index + 1}`).value = name);
  updateScale();
}
function collect() {
  const settings = {...currentSettings};
  fields.forEach(key => { const element = byId(key); settings[key] = element.type === "checkbox" ? element.checked : numbers.has(key) ? (element.value.trim() === "" ? null : Number(element.value)) : element.value; });
  const values = Array.from({length: 6}, (_, index) => byId(`t${index + 1}`).valueAsNumber);
  settings.temperatures = [values.slice(0, 3), values.slice(3)];
  settings.sensor_names = Array.from({length:6}, (_, index) => byId(`name${index + 1}`).value);
  settings.sensor_positions = Array.from({length:6}, (_, index) => [(index % 3) / 2 * settings.area_width, Math.floor(index / 3) * settings.area_height]);
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
function markChanged() { updateScale(); byId("previewSurface").classList.add("stale"); byId("previewState").textContent = "Inputs changed - Update preview"; }
byId("settingsForm").addEventListener("input", markChanged);
byId("settingsForm").addEventListener("invalid", event => {
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
byId("browse").addEventListener("click", async () => { try { const result = await window.pywebview.api.choose_output(); if (result.output_path) byId("output_path").value = result.output_path; } catch (error) { status(error.message, "error"); } });
busy(true);
window.addEventListener("pywebviewready", async () => {
  try { const result = await window.pywebview.api.get_settings(); populate(result.settings); busy(false); await generate(); if (result.warning) status(result.warning, "error"); }
  catch (error) { busy(false); status(error.message, "error"); }
});
