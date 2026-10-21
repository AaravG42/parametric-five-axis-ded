const form = document.querySelector("#parameter-form");
const output = document.querySelector("#gcode");
const statusBox = document.querySelector("#status");
const metrics = document.querySelector("#metrics");
const warnings = document.querySelector("#warnings");
const downloadNc = document.querySelector("#download-nc");
const downloadRep5x = document.querySelector("#download-rep5x");
const downloadPenta = document.querySelector("#download-penta");
const downloadJson = document.querySelector("#download-json");
const copyButton = document.querySelector("#copy");

let defaults = {};
let lastParameters = {};
let lastGcode = "";
let lastRep5xGcode = "";
let lastPentaGcode = "";

const integerFields = new Set([
  "program_number", "inner_wall_passes", "inner_fin_count",
  "inner_fin_radial_layers", "outer_wall_passes", "outer_fin_count",
  "outer_fin_radial_layers", "tilt_sign", "rotary_sign",
]);

const textFields = new Set([
  "material_1", "material_2", "tilt_axis", "rotary_axis", "work_offset",
  "laser_on_code", "laser_off_code",
]);

function setStatus(message, kind = "ok") {
  statusBox.textContent = message;
  statusBox.style.color = kind === "error" ? "#efb18f" : "#76b28c";
}

function fillForm(values) {
  for (const [key, value] of Object.entries(values)) {
    const field = form.elements.namedItem(key);
    if (field) field.value = value;
  }
}

function readForm() {
  const values = {};
  for (const element of form.elements) {
    if (!element.name) continue;
    if (textFields.has(element.name)) values[element.name] = element.value.trim();
    else if (integerFields.has(element.name)) values[element.name] = Number.parseInt(element.value, 10);
    else values[element.name] = Number.parseFloat(element.value);
  }
  return values;
}

function updateSummary(summary) {
  const boxes = metrics.querySelectorAll("strong");
  boxes[0].textContent = summary.move_count.toLocaleString();
  boxes[1].textContent = summary.line_count.toLocaleString();
  boxes[2].textContent = `${summary.path_length_mm.toLocaleString()} mm`;
  boxes[3].textContent = `${summary.bounds.z[0]} to ${summary.bounds.z[1]} mm`;
  warnings.innerHTML = summary.warnings.map(item => `<div>• ${item}</div>`).join("");
}

function download(filename, contents, type) {
  const blob = new Blob([contents], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function generate(event) {
  event?.preventDefault();
  setStatus("Generating…");
  try {
    lastParameters = readForm();
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(lastParameters),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Generation failed.");
    lastGcode = payload.gcode;
    lastRep5xGcode = payload.rep5x_gcode;
    lastPentaGcode = payload.penta_gcode;
    output.value = lastGcode;
    updateSummary(payload.summary);
    downloadNc.disabled = false;
    downloadRep5x.disabled = false;
    downloadPenta.disabled = false;
    downloadJson.disabled = false;
    copyButton.disabled = false;
    setStatus("Generated");
  } catch (error) {
    setStatus(error.message, "error");
    warnings.textContent = error.message;
  }
}

form.addEventListener("submit", generate);
document.querySelector("#reset").addEventListener("click", () => {
  fillForm(defaults);
  generate();
});
downloadNc.addEventListener("click", () => download(
  "parametric_two_material_nozzle.nc", lastGcode, "text/plain",
));
downloadRep5x.addEventListener("click", () => download(
  "parametric_two_material_nozzle_rep5x_preview.gcode",
  lastRep5xGcode,
  "text/plain",
));
downloadPenta.addEventListener("click", () => download(
  "parametric_two_material_nozzle_penta_preview.ngc",
  lastPentaGcode,
  "text/plain",
));
downloadJson.addEventListener("click", () => download(
  "parametric_two_material_nozzle_parameters.json",
  JSON.stringify(lastParameters, null, 2), "application/json",
));
copyButton.addEventListener("click", async () => {
  await navigator.clipboard.writeText(lastGcode);
  setStatus("Copied");
});

fetch("/api/defaults")
  .then(response => response.json())
  .then(values => {
    defaults = values;
    fillForm(defaults);
    generate();
  })
  .catch(error => setStatus(error.message, "error"));
