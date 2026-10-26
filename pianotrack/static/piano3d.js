// Shared pieces of the 3D views (keys3d.js, falling3d.js): the 88-key layout,
// the keyboard itself, the theme colours and a renderer that fails quietly.
import * as THREE from "/vendor/three-0.180.0/three.module.min.js";

export { THREE };
export const LOW = 21, HIGH = 108, WW = 1, WL = 6, BW = 0.58, BL = 3.8, KH = 0.7;
export const isBlack = (p) => [1, 3, 6, 8, 10].includes(p % 12);

// White keys side by side, centred on x = 0; black keys between their neighbours.
const whites = [];
for (let p = LOW; p <= HIGH; p++) if (!isBlack(p)) whites.push(p);
export const span = whites.length * WW;
export const pos = {};
whites.forEach((p, i) => pos[p] = -span / 2 + i * WW + WW / 2);
for (let p = LOW; p <= HIGH; p++) if (isBlack(p)) pos[p] = pos[p - 1] + WW / 2;

export function css(name) {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#999");
}

// A WebGL renderer appended to `box`, or null where WebGL is missing.
export function renderer(box) {
  let r;
  try {
    r = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (e) {
    return null;
  }
  r.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  r.domElement.setAttribute("aria-hidden", "true");
  box.appendChild(r.domElement);
  return r;
}

// Size the renderer to `box` and return how far a camera must stand to see
// `width` units across, or 0 while the box has no size.
export function fitWidth(renderer, camera, box, width) {
  const w = box.clientWidth, h = box.clientHeight;
  if (!w || !h) return 0;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  const hfov = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.aspect);
  return (width / 2) / Math.tan(hfov / 2);
}

export function lights(scene) {
  scene.add(new THREE.HemisphereLight(0xffffff, 0x443033, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-8, 20, 14);
  scene.add(sun);
}

// The keyboard with the felt strip behind it. `paint()` takes the theme colours.
export function keyboard(scene) {
  const mat = {
    white: new THREE.MeshStandardMaterial({ roughness: 0.45 }),
    black: new THREE.MeshStandardMaterial({ roughness: 0.35 }),
    felt: new THREE.MeshStandardMaterial({ roughness: 1 }),
  };
  const felt = new THREE.Mesh(new THREE.BoxGeometry(span + 1, 0.3, 1.2), mat.felt);
  felt.position.set(0, KH * 0.9, -WL / 2 - 0.6);
  scene.add(felt);
  const keys = {};
  for (let p = LOW; p <= HIGH; p++) {
    const b = isBlack(p);
    const key = new THREE.Mesh(new THREE.BoxGeometry(b ? BW : WW * 0.94, KH, b ? BL : WL), b ? mat.black : mat.white);
    key.position.set(pos[p], b ? KH * 0.95 : KH / 2, b ? -(WL - BL) / 2 : 0);
    key.userData.p = p;
    scene.add(key); keys[p] = key;
  }
  const paint = () => {
    mat.white.color = css("--key-white"); mat.black.color = css("--key-black"); mat.felt.color = css("--accent");
  };
  paint();
  return { keys, mat, felt, paint };
}

// Call `paint` when the theme changes, by toggle or by the system.
export function onTheme(paint) {
  new MutationObserver(paint).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", paint);
}
