// The key map in 3D: an 88-key keyboard on the felt strip, with a column of felt
// rising from each key as high as you played it. The flat key map below stays the
// exact, accessible view; this one is for the feel of it. three.js is bundled in
// /vendor (MIT), nothing is loaded from the internet.
import { THREE, LOW, HIGH, WW, WL, BW, KH, isBlack, span, pos, css, renderer as makeRenderer, fitWidth, lights, keyboard, onTheme } from "/piano3d.js";

const TOP = 3, MAXH = 7;

// Mount the view in `box`. Returns {update(hist)} or null when WebGL is missing.
export function mount(box, { noteName, fmtNum }) {
  const renderer = makeRenderer(box);
  if (!renderer) return null;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const tip = document.createElement("div");
  tip.className = "k3-tip";
  box.appendChild(tip);

  const scene = new THREE.Scene();
  lights(scene);
  const kb = keyboard(scene);
  const brass = new THREE.MeshStandardMaterial({ roughness: 0.3, metalness: 0.6 });

  const keys = Object.values(kb.keys), cols = [];
  const unit = new THREE.BoxGeometry(1, 1, 1);
  unit.translate(0, 0.5, 0);
  for (let p = LOW; p <= HIGH; p++) {
    const b = isBlack(p), key = kb.keys[p];
    // The column stands on the back of the key, so the front stays a keyboard.
    const col = new THREE.Mesh(unit, new THREE.MeshStandardMaterial({ roughness: 0.8 }));
    col.scale.set(b ? BW * 0.8 : WW * 0.62, 0.001, 1.4);
    col.position.set(pos[p], key.position.y + KH / 2, -WL / 2 + 1.0);
    col.userData = { p, from: 0, to: 0 };
    col.visible = false;
    scene.add(col); cols.push(col);
  }

  const camera = new THREE.PerspectiveCamera(28, 2, 0.1, 400);
  const look = new THREE.Vector3(0, 3.4, -1.5);
  let hist = new Array(88).fill(0), total = 1, panX = 0, panTo = 0, fit = 1;

  function paint() {
    kb.paint(); brass.color = css("--good");
    const lo = css("--seq-1"), hi = css("--seq-3"), max = Math.max(...hist) || 1;
    const top = hist.map((c, i) => [c, i]).filter(([c]) => c).sort((a, b) => b[0] - a[0]).slice(0, TOP).map(([, i]) => i);
    cols.forEach((c, i) => {
      if (top.includes(i)) c.material.color.copy(brass.color);
      else c.material.color.copy(lo).lerp(hi, Math.sqrt(hist[i] / max));
    });
    need();
  }

  // Phones see about two and a half octaves at a time and slide along the keys;
  // wider screens see the whole keyboard.
  function resize() {
    const want = box.clientWidth < 700 ? 22 : span + 2;
    const dist = fitWidth(renderer, camera, box, want);
    if (!dist) return;
    fit = want / span;
    camera.position.set(0, dist * 0.55, dist * 0.85);
    clampPan();
    need();
  }
  function clampPan() {
    const lim = Math.max(0, (span - span * fit) / 2);
    panTo = Math.max(-lim, Math.min(lim, panTo));
  }

  // Frames are drawn only while something moves: the columns rising, a drag, or a
  // few seconds of sway after you arrive or touch it, so an idle page costs nothing.
  let t0 = performance.now(), raf = 0, onScreen = true, growing = 0, swayUntil = 0;
  function need() { if (!raf && onScreen && !document.hidden) raf = requestAnimationFrame(frame); }
  function stir() { swayUntil = performance.now() + 8000; need(); }
  function frame(now) {
    raf = 0;
    let busy = false;
    if (growing) {
      // A glissando: columns rise left to right.
      const t = (now - growing) / 1000;
      cols.forEach((c, i) => {
        const k = still ? 1 : Math.min(1, Math.max(0, (t - i * 0.006) / 0.9));
        const e = 1 - Math.pow(1 - k, 3);
        const h = c.userData.from + (c.userData.to - c.userData.from) * e;
        c.scale.y = Math.max(0.001, h);
        c.visible = h > 0.01;
        if (k < 1) busy = true;
      });
      if (!busy) growing = 0;
    }
    panX += (panTo - panX) * (still ? 1 : 0.18);
    if (Math.abs(panTo - panX) > 0.01) busy = true;
    const fade = still ? 0 : Math.max(0, Math.min(1, (swayUntil - now) / 1500));
    const sway = Math.sin((now - t0) / 2600) * 0.9 * fade;
    if (fade > 0) busy = true;
    camera.position.x = panX + sway;
    camera.lookAt(look.x + panX, look.y, look.z);
    renderer.render(scene, camera);
    if (busy) need();
  }

  // Drag slides along the keyboard; a tap names the key.
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  let drag = null;
  const el = renderer.domElement;
  el.style.touchAction = "pan-y";
  el.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, pan: panTo, moved: false }; stir(); });
  el.addEventListener("pointercancel", () => { drag = null; });
  el.addEventListener("pointermove", (e) => {
    if (drag) {
      const dx = e.clientX - drag.x;
      if (Math.abs(dx) > 4) drag.moved = true;
      panTo = drag.pan - dx * (span * fit) / box.clientWidth;
      clampPan(); need();
    } else if (e.pointerType === "mouse") pick(e);
  });
  addEventListener("pointerup", (e) => {
    if (drag && !drag.moved && e.target === el) pick(e);
    drag = null;
  });
  el.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") tip.style.opacity = 0; });
  function pick(e) {
    const r = el.getBoundingClientRect();
    ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects([...cols.filter((c) => c.visible), ...keys])[0];
    if (!hit) { tip.style.opacity = 0; return; }
    const p = hit.object.userData.p, c = hist[p - LOW];
    tip.textContent = `${noteName(p)}: ${fmtNum(c)} notes${c ? `, ${(100 * c / total).toFixed(1)}%` : ""}`;
    tip.style.left = `${Math.min(r.width - 150, Math.max(0, e.clientX - r.left - 60))}px`;
    tip.style.opacity = 1;
  }

  new ResizeObserver(resize).observe(box);
  new IntersectionObserver(([en]) => { onScreen = en.isIntersecting; need(); }).observe(box);
  document.addEventListener("visibilitychange", need);
  onTheme(paint);

  return {
    update(h) {
      hist = h.slice(); total = hist.reduce((a, b) => a + b, 0) || 1;
      const max = Math.max(...hist) || 1;
      cols.forEach((c, i) => {
        c.userData.from = c.visible ? c.scale.y : 0;
        c.userData.to = hist[i] ? 0.25 + MAXH * Math.sqrt(hist[i] / max) : 0;
      });
      // Start where you play most, so a phone opens on your part of the keyboard.
      let best = 0, at = 0;
      for (let i = 0; i < 88; i++) {
        let s = 0;
        for (let j = Math.max(0, i - 15); j <= Math.min(87, i + 15); j++) s += hist[j];
        if (s > best) { best = s; at = i; }
      }
      panTo = pos[at + LOW]; clampPan();
      tip.style.opacity = 0;
      growing = performance.now();
      paint(); stir();
    },
  };
}
