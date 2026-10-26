// Falling notes for the session replay: the notes you played travel down a lane
// towards a 3D keyboard and press its keys as they sound, like a piano roll seen
// from the bench. The replay player (replay.js) drives it: setNotes() on load,
// draw(t) whenever its position changes, so nothing renders while it is paused.
import { THREE, LOW, HIGH, WW, WL, BW, KH, isBlack, pos, css, renderer as makeRenderer, fitWidth, lights, keyboard, onTheme } from "/piano3d.js";

const AHEAD = 4;      // seconds of music shown above the keys
const Z = 5;          // lane length per second
const PRESS = 0.16;   // how far a key goes down

export function mount(box) {
  const renderer = makeRenderer(box);
  if (!renderer) return null;
  const scene = new THREE.Scene();
  lights(scene);
  const kb = keyboard(scene);
  kb.felt.visible = false;  // it would hide notes as they reach the keys
  const back = -WL / 2, far = back - AHEAD * Z;

  // The lane: a dark board with a line at every C so you can read the octaves.
  const laneMat = new THREE.MeshStandardMaterial({ roughness: 1 });
  const lane = new THREE.Mesh(new THREE.PlaneGeometry(1, AHEAD * Z), laneMat);
  lane.rotation.x = -Math.PI / 2;
  lane.position.set(0, 0.02, (back + far) / 2);
  scene.add(lane);
  const lineMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.5 });
  const lines = new THREE.LineSegments(new THREE.BufferGeometry(), lineMat);
  scene.add(lines);
  // Octave lines only across the framed keys, the same length as the lane.
  function octaveLines(a, z) {
    const pts = [];
    for (let p = LOW; p <= HIGH; p++) if (p % 12 === 0 && pos[p] - WW / 2 > a && pos[p] - WW / 2 < z) {
      const x = pos[p] - WW / 2;
      pts.push(new THREE.Vector3(x, 0.03, back), new THREE.Vector3(x, 0.03, far));
    }
    lines.geometry.dispose();
    lines.geometry = new THREE.BufferGeometry().setFromPoints(pts);
  }

  // Notes are instances of one box, drawn only while inside the lane.
  const unit = new THREE.BoxGeometry(1, 1, 1);
  const noteMat = new THREE.MeshStandardMaterial({ roughness: 0.5 });
  let cap = 256, bars = makeBars(cap);
  function makeBars(n) {
    const m = new THREE.InstancedMesh(unit, noteMat, n);
    m.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    m.count = 0; m.frustumCulled = false;
    scene.add(m);
    return m;
  }

  const camera = new THREE.PerspectiveCamera(34, 2, 0.1, 400);
  const colour = {};
  let notes = [], first = () => 0, maxHold = 0, t = 0, centre = 0, width = 30, down = new Set();
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), v = new THREE.Vector3(), sc = new THREE.Vector3();
  const tint = new THREE.Color();

  function paint() {
    kb.paint();
    colour.white = css("--accent"); colour.black = css("--accent").lerp(css("--text"), 0.4); colour.hit = css("--good");
    laneMat.color = css("--key-black").lerp(css("--accent"), 0.12);
    lineMat.color = css("--key-white");
    // The far end of the lane fades into the card, so notes arrive out of the mist.
    if (scene.fog) scene.fog.color = css("--surface");
    else scene.fog = new THREE.Fog(css("--surface"), 1000, 1001);
    frame();
  }

  // Frame the keys this session used (at least two octaves), so a phone shows
  // the music rather than 88 thin keys.
  function frame() {
    const dist = fitWidth(renderer, camera, box, width + 1);
    if (!dist) return;
    camera.position.set(centre, dist * 0.8, WL / 2 + dist * 0.42);
    camera.lookAt(centre, 0, back - AHEAD * Z * 0.3);
    lane.scale.x = width + 2; lane.position.x = centre;
    if (scene.fog) {
      const toKeys = camera.position.distanceTo(v.set(centre, 0, back));
      scene.fog.near = toKeys + AHEAD * Z * 0.35;
      scene.fog.far = camera.position.distanceTo(v.set(centre, 0, far)) + 1;
    }
    render();
  }

  function render() {
    // Notes that may still sound at t start no earlier than t - maxHold.
    let i = first(t - maxHold), n = 0;
    const end = first(t + AHEAD), now = new Set();
    for (; i < end; i++) {
      const x = notes[i];
      if (x.off <= t || !(x.pitch in pos)) continue;
      const b = isBlack(x.pitch);
      if (x.on <= t) now.add(x.pitch);
      const near = back - Math.max(0, x.on - t) * Z;
      const farEnd = back - Math.min(AHEAD, x.off - t) * Z;
      const len = Math.max(0.12, near - farEnd);
      const hgt = 0.18 + 0.32 * x.vel / 127;
      if (n >= cap) { scene.remove(bars); bars.dispose(); cap *= 2; bars = makeBars(cap); return render(); }
      v.set(pos[x.pitch], (b ? 0.08 : 0.04) + hgt / 2, near - len / 2);
      sc.set(b ? BW * 0.9 : WW * 0.78, hgt, len);
      bars.setMatrixAt(n, m4.compose(v, q, sc));
      // Brighter while it sounds, so you can see what the hands are holding.
      tint.copy(b ? colour.black : colour.white);
      if (x.on <= t) tint.lerp(colour.hit, 0.55);
      bars.setColorAt(n, tint);
      n++;
    }
    bars.count = n;
    bars.instanceMatrix.needsUpdate = true;
    if (bars.instanceColor) bars.instanceColor.needsUpdate = true;
    for (const p of new Set([...down, ...now])) {
      const k = kb.keys[p], on = now.has(p);
      k.position.y = (isBlack(p) ? KH * 0.95 : KH / 2) - (on ? PRESS : 0);
      k.material = on ? hitMat(p) : (isBlack(p) ? kb.mat.black : kb.mat.white);
    }
    down = now;
    renderer.render(scene, camera);
  }
  const hits = {};
  function hitMat(p) {
    const key = isBlack(p) ? "black" : "white";
    if (!hits[key]) hits[key] = new THREE.MeshStandardMaterial({ roughness: 0.4 });
    hits[key].color.copy(kb.mat[key].color).lerp(colour.white, 0.6);
    return hits[key];
  }

  new ResizeObserver(frame).observe(box);
  onTheme(paint);
  paint();

  return {
    // `firstFrom(t)` is the player's search for the first note starting at or after t.
    setNotes(prep, firstFrom) {
      notes = prep.notes; first = firstFrom; maxHold = prep.maxHold; t = 0;
      let lo = HIGH, hi = LOW;
      for (const x of notes) if (x.pitch in pos) { lo = Math.min(lo, x.pitch); hi = Math.max(hi, x.pitch); }
      if (lo > hi) { lo = 48; hi = 72; }
      const a = pos[lo] - WW, z = pos[hi] + WW;
      width = Math.max(14 * WW, z - a); centre = (a + z) / 2;
      octaveLines(centre - width / 2 - 1, centre + width / 2 + 1);
      frame();
    },
    draw(time) { t = time; render(); },
  };
}
