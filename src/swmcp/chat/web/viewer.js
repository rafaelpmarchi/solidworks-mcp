// Visualizador 3D do painel Scan 3D (fases 2-5 do plano de paridade com o
// QuickSurface): render da malha, pincel/varinha de seleção, 3D sketch sobre
// o scan e editor da malha de controle do freeform. Tudo local (three.js
// servido pelo backend; malha via binário compacto).

import * as THREE from "three";
import { OrbitControls } from "/vendor/OrbitControls.js";

const $ = id => document.getElementById(id);
const container = $("viewer3d");

// ------------------------------------------------------------------ cena
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf0f0f0);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100000);
camera.position.set(120, -120, 90);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 0.9);
key.position.set(1, -1, 2);
scene.add(key);
const fill = new THREE.DirectionalLight(0xffffff, 0.35);
fill.position.set(-2, 1, -1);
scene.add(fill);

function resize() {
  const w = container.clientWidth, h = container.clientHeight;
  if (w && h) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
}
new ResizeObserver(resize).observe(container);

renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });

// ------------------------------------------------------------------ malha
let mesh = null, geo = null, positions = null, labels = null,
    selection = null, adjacency = null;
const PALETA = [0x9aa0a8, 0x4a90d9, 0x2e8b2e, 0xd9902f, 0x8e5bc0,
                0xc05b5b, 0x2fa8a0, 0xb0b02f];

async function api(route, body) {
  const r = await fetch("/mesh/" + route, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}) });
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

export async function refreshViewer() {
  const info = await api("viewerpack", { target_faces: 80000 });
  const buf = await (await fetch("/mesh/file?path=" +
    encodeURIComponent(info.bin) + "&t=" + Date.now())).arrayBuffer();
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== 0x314D5753) throw new Error("bin inválido");
  const nv = dv.getUint32(4, true), nf = dv.getUint32(8, true);
  let off = 12;
  positions = new Float32Array(buf, off, nv * 3); off += nv * 12;
  const faces = new Uint32Array(buf, off, nf * 3); off += nf * 12;
  labels = new Int32Array(buf, off, nv);
  selection = new Uint8Array(nv);
  adjacency = null;
  clearSketch(); exitCtrlEditor();

  if (mesh) { scene.remove(mesh); geo.dispose(); }
  geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setIndex(new THREE.BufferAttribute(faces, 1));
  geo.computeVertexNormals();
  geo.setAttribute("color",
    new THREE.BufferAttribute(new Float32Array(nv * 3), 3));
  colorize();
  mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({
    vertexColors: true, side: THREE.DoubleSide }));
  scene.add(mesh);
  fitCamera();
  $("v-info").textContent = `${nv.toLocaleString("pt-BR")} vtx`;
}

function fitCamera() {
  geo.computeBoundingSphere();
  const s = geo.boundingSphere;
  controls.target.copy(s.center);
  const d = s.radius * 2.4;
  camera.position.set(s.center.x + d * 0.6, s.center.y - d * 0.8,
                      s.center.z + d * 0.5);
  camera.near = s.radius / 100; camera.far = s.radius * 20;
  camera.updateProjectionMatrix();
}

function colorize() {
  const c = geo.getAttribute("color");
  const tmp = new THREE.Color();
  for (let i = 0; i < c.count; i++) {
    if (selection[i]) tmp.setHex(0xe23a3a);
    else tmp.setHex(labels[i] > 0 ? PALETA[labels[i] % PALETA.length] : 0xb9bec4);
    c.setXYZ(i, tmp.r, tmp.g, tmp.b);
  }
  c.needsUpdate = true;
}

// ------------------------------------------------------------------ modos
let mode = "orbit";   // orbit | brush | erase | wand | sketch | ctrl
export function setMode(m) {
  mode = m;
  controls.enabled = (m === "orbit" || m === "ctrl");
  for (const b of document.querySelectorAll("#v-tools .vbtn"))
    b.classList.toggle("on", b.dataset.mode === m);
  renderer.domElement.style.cursor =
    m === "orbit" ? "grab" : m === "ctrl" ? "default" : "crosshair";
}

const ray = new THREE.Raycaster();
function pick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(
    ((ev.clientX - r.left) / r.width) * 2 - 1,
    -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  const hits = ray.intersectObject(mesh, false);
  return hits.length ? hits[0] : null;
}

// ------------------------------------------------------- pincel e varinha
function paint(hit, value) {
  const raio = +$("v-raio").value;
  const p = hit.point, r2 = raio * raio;
  for (let i = 0; i < selection.length; i++) {
    const dx = positions[3 * i] - p.x, dy = positions[3 * i + 1] - p.y,
          dz = positions[3 * i + 2] - p.z;
    if (dx * dx + dy * dy + dz * dz <= r2) selection[i] = value;
  }
  colorize();
}

function buildAdjacency() {
  const idx = geo.getIndex().array;
  const adj = Array.from({ length: selection.length }, () => []);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t], b = idx[t + 1], c = idx[t + 2];
    adj[a].push(b, c); adj[b].push(a, c); adj[c].push(a, b);
  }
  return adj;
}

function wand(hit) {
  if (!adjacency) adjacency = buildAdjacency();
  const nrm = geo.getAttribute("normal");
  const face = hit.face;
  const seed = face.a;
  const cosLim = Math.cos((+$("v-raio").value + 2) * Math.PI / 180); // sens.
  const sx = nrm.getX(seed), sy = nrm.getY(seed), sz = nrm.getZ(seed);
  const fila = [seed], visto = new Uint8Array(selection.length);
  visto[seed] = 1;
  while (fila.length) {
    const v = fila.pop();
    selection[v] = 1;
    for (const w of adjacency[v]) {
      if (visto[w]) continue;
      visto[w] = 1;
      const dot = nrm.getX(w) * sx + nrm.getY(w) * sy + nrm.getZ(w) * sz;
      if (dot >= cosLim) fila.push(w);
    }
  }
  colorize();
}

export function clearSelection() {
  if (selection) { selection.fill(0); colorize(); }
  window.viewerSelectionMask = null;
  $("v-sel-info").textContent = "";
}

export async function useSelection() {
  const idx = [];
  for (let i = 0; i < selection.length; i++) if (selection[i]) idx.push(i);
  if (!idx.length) throw new Error("nada selecionado — pinte com o pincel ou varinha");
  const r = await api("savemask", { indices: idx });
  window.viewerSelectionMask = r.mask;   // regiaoAtiva() do painel usa isso
  $("v-sel-info").textContent =
    `região: ${r.vertices_na_mascara.toLocaleString("pt-BR")} vtx da malha cheia`;
  return r;
}

// --------------------------------------------------------------- 3D sketch
let curves = [], curveObjs = [];
function sketchClick(hit) {
  if (!curves.length) curves.push([]);
  curves[curves.length - 1].push([hit.point.x, hit.point.y, hit.point.z]);
  drawCurves();
}
function drawCurves() {
  for (const o of curveObjs) scene.remove(o);
  curveObjs = [];
  for (const c of curves) {
    if (!c.length) continue;
    const pts = c.map(p => new THREE.Vector3(...p));
    if (pts.length > 1) {
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(
          pts.length > 2 ? new THREE.CatmullRomCurve3(pts).getPoints(pts.length * 8)
                         : pts),
        new THREE.LineBasicMaterial({ color: 0xd97757, linewidth: 2 }));
      curveObjs.push(line); scene.add(line);
    }
    for (const p of pts) {
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.8, 8, 8),
        new THREE.MeshBasicMaterial({ color: 0xd97757 }));
      s.position.copy(p); curveObjs.push(s); scene.add(s);
    }
  }
  $("v-sk-info").textContent = curves.filter(c => c.length > 1).length
    ? `${curves.filter(c => c.length > 1).length} curva(s)` : "";
}
export function newCurve() { if (curves.length && curves[curves.length-1].length) curves.push([]); }
export function clearSketch() { curves = []; drawCurves(); }
export async function sendSketch() {
  const boas = curves.filter(c => c.length >= 2);
  if (!boas.length) throw new Error("nenhuma curva com 2+ pontos");
  const r = await api("sketch3d", { curves: boas });
  return r;
}

// ------------------------------------------- editor da malha de controle
let ctrl = null, ctrlGroup = null, surfMesh = null, samples = null,
    dragging = null;
const dragPlane = new THREE.Plane();

function knotVector(knots, mults) {
  const kv = [];
  for (let i = 0; i < knots.length; i++)
    for (let m = 0; m < mults[i]; m++) kv.push(knots[i]);
  return kv;
}
function findSpan(kv, deg, n, t) {
  if (t >= kv[n + 1]) return n;
  let lo = deg, hi = n + 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; (t < kv[mid]) ? hi = mid : lo = mid; }
  return lo;
}
function basis(kv, deg, span, t) {
  const N = [1], left = [], right = [];
  for (let j = 1; j <= deg; j++) {
    left[j] = t - kv[span + 1 - j]; right[j] = kv[span + j] - t;
    let saved = 0;
    for (let r = 0; r < j; r++) {
      const tmp = N[r] / (right[r + 1] + left[j - r]);
      N[r] = saved + right[r + 1] * tmp;
      saved = left[j - r] * tmp;
    }
    N[j] = saved;
  }
  return N;
}
function surfPoint(u, v, out) {
  const { poles, udeg, vdeg } = ctrl;
  const nu = poles.length, nvp = poles[0].length;
  const su = findSpan(ctrl._ukv, udeg, nu - 1, u);
  const sv = findSpan(ctrl._vkv, vdeg, nvp - 1, v);
  const Nu = basis(ctrl._ukv, udeg, su, u), Nv = basis(ctrl._vkv, vdeg, sv, v);
  out[0] = out[1] = out[2] = 0;
  for (let i = 0; i <= udeg; i++)
    for (let j = 0; j <= vdeg; j++) {
      const w = Nu[i] * Nv[j], p = poles[su - udeg + i][sv - vdeg + j];
      out[0] += w * p[0]; out[1] += w * p[1]; out[2] += w * p[2];
    }
}

const SURF_N = 36;
function rebuildSurface(first) {
  const u0 = ctrl._ukv[ctrl.udeg], u1 = ctrl._ukv[ctrl._ukv.length - 1 - ctrl.udeg];
  const v0 = ctrl._vkv[ctrl.vdeg], v1 = ctrl._vkv[ctrl._vkv.length - 1 - ctrl.vdeg];
  const pos = surfMesh.geometry.getAttribute("position");
  const col = surfMesh.geometry.getAttribute("color");
  const p = [0, 0, 0], tmp = new THREE.Color();
  const tol = +$("v-ff-tol").value || 0.1;
  let k = 0;
  for (let i = 0; i <= SURF_N; i++)
    for (let j = 0; j <= SURF_N; j++, k++) {
      surfPoint(u0 + (u1 - u0) * i / SURF_N, v0 + (v1 - v0) * j / SURF_N, p);
      pos.setXYZ(k, p[0], p[1], p[2]);
      const d = samples ? sampleDist(p) : 0;
      if (d <= tol) tmp.setHex(0x2e9e2e);
      else if (d <= 5 * tol) tmp.setHSL(0.12 - 0.12 * Math.min(1, (d - tol) / (4 * tol)), 0.9, 0.5);
      else tmp.setHex(0x8c1a1a);
      col.setXYZ(k, tmp.r, tmp.g, tmp.b);
    }
  pos.needsUpdate = true; col.needsUpdate = true;
  if (first) surfMesh.geometry.computeVertexNormals();
}

// grade hash simples para distância aproximada aos pontos do scan
let grid = null, cell = 4;
function buildSamples() {
  samples = positions;
  grid = new Map();
  for (let i = 0; i < samples.length; i += 3) {
    const kx = Math.floor(samples[i] / cell), ky = Math.floor(samples[i + 1] / cell),
          kz = Math.floor(samples[i + 2] / cell);
    const key = kx + "," + ky + "," + kz;
    if (!grid.has(key)) grid.set(key, []);
    grid.get(key).push(i);
  }
}
function sampleDist(p) {
  const kx = Math.floor(p[0] / cell), ky = Math.floor(p[1] / cell),
        kz = Math.floor(p[2] / cell);
  let best = Infinity;
  for (let dx = -1; dx <= 1; dx++)
    for (let dy = -1; dy <= 1; dy++)
      for (let dz = -1; dz <= 1; dz++) {
        const b = grid.get((kx + dx) + "," + (ky + dy) + "," + (kz + dz));
        if (!b) continue;
        for (const i of b) {
          const ex = samples[i] - p[0], ey = samples[i + 1] - p[1],
                ez = samples[i + 2] - p[2];
          const d2 = ex * ex + ey * ey + ez * ez;
          if (d2 < best) best = d2;
        }
      }
  return Math.sqrt(best);
}

export function enterCtrlEditor(ctrlData) {
  exitCtrlEditor();
  ctrl = ctrlData;
  ctrl._ukv = knotVector(ctrl.uknots, ctrl.umults);
  ctrl._vkv = knotVector(ctrl.vknots, ctrl.vmults);
  buildSamples();
  ctrlGroup = new THREE.Group();
  const nu = ctrl.poles.length, nvp = ctrl.poles[0].length;
  const sgeo = new THREE.SphereGeometry(1.2, 10, 10);
  for (let i = 0; i < nu; i++)
    for (let j = 0; j < nvp; j++) {
      const s = new THREE.Mesh(sgeo,
        new THREE.MeshBasicMaterial({ color: 0x2f6db5 }));
      s.position.set(...ctrl.poles[i][j]);
      s.userData = { i, j };
      ctrlGroup.add(s);
    }
  scene.add(ctrlGroup);
  const g = new THREE.BufferGeometry();
  const n = (SURF_N + 1) * (SURF_N + 1);
  g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
  const idx = [];
  for (let i = 0; i < SURF_N; i++)
    for (let j = 0; j < SURF_N; j++) {
      const a = i * (SURF_N + 1) + j, b = a + SURF_N + 1;
      idx.push(a, b, a + 1, b, b + 1, a + 1);
    }
  g.setIndex(idx);
  surfMesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({
    vertexColors: true, side: THREE.DoubleSide, transparent: true, opacity: 0.95 }));
  scene.add(surfMesh);
  rebuildSurface(true);
  if (mesh) mesh.material.opacity = 0.35, mesh.material.transparent = true,
            mesh.material.needsUpdate = true;
  setMode("ctrl");
  $("v-ff-bar").style.display = "flex";
}
export function exitCtrlEditor() {
  if (ctrlGroup) { scene.remove(ctrlGroup); ctrlGroup = null; }
  if (surfMesh) { scene.remove(surfMesh); surfMesh = null; }
  ctrl = null; dragging = null;
  if (mesh) mesh.material.opacity = 1, mesh.material.transparent = false,
            mesh.material.needsUpdate = true;
  const bar = $("v-ff-bar");
  if (bar) bar.style.display = "none";
}
export function getCtrl() {
  if (!ctrl) return null;
  const { _ukv, _vkv, ...limpo } = ctrl;
  return limpo;
}

// ------------------------------------------------------------------ input
let painting = false;
renderer.domElement.addEventListener("pointerdown", ev => {
  if (!mesh || ev.button !== 0) return;
  if (mode === "ctrl" && ctrlGroup) {
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(
      ((ev.clientX - r.left) / r.width) * 2 - 1,
      -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = ray.intersectObjects(ctrlGroup.children, false)[0];
    if (hit) {
      dragging = hit.object;
      controls.enabled = false;
      dragPlane.setFromNormalAndCoplanarPoint(
        camera.getWorldDirection(new THREE.Vector3()), dragging.position);
    }
    return;
  }
  const hit = pick(ev);
  if (!hit) return;
  if (mode === "brush") { painting = true; paint(hit, 1); }
  else if (mode === "erase") { painting = true; paint(hit, 0); }
  else if (mode === "wand") wand(hit);
  else if (mode === "sketch") sketchClick(hit);
});
renderer.domElement.addEventListener("pointermove", ev => {
  if (dragging) {
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(
      ((ev.clientX - r.left) / r.width) * 2 - 1,
      -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
    const p = new THREE.Vector3();
    if (ray.ray.intersectPlane(dragPlane, p)) {
      dragging.position.copy(p);
      const { i, j } = dragging.userData;
      ctrl.poles[i][j] = [p.x, p.y, p.z];
      rebuildSurface(false);
    }
    return;
  }
  if (!painting) return;
  const hit = pick(ev);
  if (hit) paint(hit, mode === "brush" ? 1 : 0);
});
window.addEventListener("pointerup", () => {
  painting = false;
  if (dragging) { dragging = null; if (mode === "ctrl") controls.enabled = true; }
});

// ------------------------------------------------------------- toolbar
for (const b of document.querySelectorAll("#v-tools .vbtn[data-mode]"))
  b.addEventListener("click", () => setMode(b.dataset.mode));
$("v-usar").addEventListener("click", () =>
  useSelection().then(() => {}, e => alert(e.message)));
$("v-limpar").addEventListener("click", () => { clearSelection(); clearSketch(); });
$("v-nova").addEventListener("click", newCurve);
$("v-enviar").addEventListener("click", () =>
  sendSketch().then(r => { $("v-sk-info").textContent =
    "no SolidWorks: " + r.sketch3d; }, e => alert(e.message)));
$("v-ff-gravar").addEventListener("click", async () => {
  try {
    const r = await api("freeform-commit", { ctrl: getCtrl() });
    $("v-sel-info").textContent = "STEP: " + r.step;
    exitCtrlEditor(); setMode("orbit");
  } catch (e) { alert(e.message); }
});
$("v-ff-sair").addEventListener("click", () => { exitCtrlEditor(); setMode("orbit"); });

// exporta para o script do painel
window.viewer = { refreshViewer, setMode, clearSelection, useSelection,
                  newCurve, clearSketch, sendSketch,
                  enterCtrlEditor, exitCtrlEditor, getCtrl, fitCamera };
setMode("orbit");
resize();
