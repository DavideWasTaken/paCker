// A small Three.js stage for one packing result: a "composing" animation while the
// answer is on its way, then the real layout with products dropping into place.
import * as THREE from 'three';

const PALETTE = ['#4fae90', '#f4b860', '#6c8ef5', '#e5786d', '#9b7fe0', '#5cc0d6', '#c6d65a', '#e78fc0', '#7fb56b', '#f19a4a'];
const ease = t => 1 - Math.pow(1 - t, 3);
const dark = () => matchMedia('(prefers-color-scheme: dark)').matches;

function colour(id) {
  let h = 0;
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

export class Stage {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    container.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(35, 1, 1, 100000);
    this.scene.add(new THREE.HemisphereLight('#ffffff', '#b9c8c2', 2.2));
    const sun = new THREE.DirectionalLight('#ffffff', 1.6);
    sun.position.set(1, 2, 1.4);
    this.scene.add(sun);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.angle = 0.75;
    this.target = new THREE.Vector3();
    this.radius = 1000;
    this.frame = this.frame.bind(this);
    this.resize = new ResizeObserver(() => this.fit());
    this.resize.observe(container);
    this.fit();
    requestAnimationFrame(this.frame);
  }

  fit() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  clear() {
    for (const child of [...this.group.children]) {
      this.group.remove(child);
      child.traverse(o => { o.geometry?.dispose(); o.material?.dispose?.(); });
    }
    this.pieces = [];
  }

  frameOn(width, height, depth) {
    this.target.set(0, height * 0.35, 0);
    this.radius = Math.max(width, height * 1.6, depth) * 1.9;
  }

  boxFrame(w, l, h, x) {
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, l)),
      new THREE.LineBasicMaterial({ color: dark() ? '#a9d8c6' : '#2f5a50', transparent: true, opacity: dark() ? 0.7 : 0.6 }));
    edges.position.set(x, h / 2, 0);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(w, l),
      new THREE.MeshBasicMaterial({ color: dark() ? '#c6f279' : '#134a41', transparent: true, opacity: dark() ? 0.06 : 0.07 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(x, 0.5, 0);
    this.group.add(edges, floor);
  }

  piece(w, h, l, colourValue) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(w, h, l),
      new THREE.MeshStandardMaterial({ color: colourValue, roughness: 0.55, metalness: 0.05, transparent: true }));
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry),
      new THREE.LineBasicMaterial({ color: '#0d2b26', transparent: true, opacity: 0.35 }));
    mesh.add(outline);
    this.group.add(mesh);
    return mesh;
  }

  // Placeholder: products shuffle inside an empty carton until the result arrives.
  compose() {
    this.clear();
    this.mode = 'compose';
    const size = 300;
    this.boxFrame(size, size * 0.75, size * 0.6, 0);
    this.frameOn(size, size * 0.6, size * 0.75);
    for (let i = 0; i < 9; i++) {
      const w = 50 + Math.random() * 70, h = 30 + Math.random() * 50, l = 40 + Math.random() * 60;
      const mesh = this.piece(w, h, l, PALETTE[i % PALETTE.length]);
      mesh.userData = { w, h, l, seed: Math.random() * 10, slot: i };
      this.pieces.push(mesh);
    }
  }

  // The real layout: boxes side by side, products drop in from above in packing order.
  show(result) {
    this.clear();
    this.mode = 'result';
    const bins = result.bins || [];
    const gap = Math.max(...bins.map(b => b.width), 1) * 0.18;
    let cursor = 0, maxH = 1, maxL = 1;
    const placed = [];
    bins.forEach(bin => {
      const x0 = cursor + bin.width / 2;
      this.boxFrame(bin.width, bin.length, bin.height, x0);
      for (const p of bin.items) placed.push({ p, bin, x0 });
      cursor += bin.width + gap;
      maxH = Math.max(maxH, bin.height);
      maxL = Math.max(maxL, bin.length);
    });
    const total = Math.max(cursor - gap, 1);
    this.group.position.x = -total / 2;
    this.frameOn(total, maxH, maxL);
    placed.sort((a, b) => a.p.z - b.p.z || a.p.y - b.p.y || a.p.x - b.p.x);
    const stagger = Math.min(90, 2200 / Math.max(placed.length, 1));
    const start = performance.now() + 150;
    placed.forEach(({ p, bin, x0 }, i) => {
      const mesh = this.piece(p.width, p.height, p.length, colour(p.id));
      const x = x0 - bin.width / 2 + p.x, z = p.y - bin.length / 2, y = p.z + p.height / 2;
      mesh.rotation.y = -(p.angle || 0) * Math.PI / 180;
      mesh.position.set(x, y + maxH * 0.9, z);
      mesh.material.opacity = 0;
      mesh.userData = { x, y, z, lift: maxH * 0.9, start: start + i * stagger };
      this.pieces.push(mesh);
    });
  }

  frame(now) {
    if (this.disposed) return;
    this.angle += this.mode === 'compose' ? 0.004 : 0.0015;
    const r = this.radius;
    this.camera.position.set(this.target.x + Math.cos(this.angle) * r, this.target.y + r * 0.62, this.target.z + Math.sin(this.angle) * r);
    this.camera.lookAt(this.target);
    const t = now / 1000;
    for (const mesh of this.pieces || []) {
      const d = mesh.userData;
      if (this.mode === 'compose') {
        // Each product tries a few spots in turn, as if the search were testing positions.
        const step = Math.floor(t * 1.2 + d.seed), phase = (t * 1.2 + d.seed) % 1;
        const spot = k => [((k * 73 + d.slot * 31) % 5 - 2) * 45, ((k * 37 + d.slot * 17) % 3) * 40 + d.h / 2, ((k * 53 + d.slot * 11) % 4 - 1.5) * 40];
        const a = spot(step), b = spot(step + 1), e = ease(Math.min(phase * 1.6, 1));
        mesh.position.set(a[0] + (b[0] - a[0]) * e, a[1] + (b[1] - a[1]) * e + Math.sin(phase * Math.PI) * 25, a[2] + (b[2] - a[2]) * e);
        mesh.material.opacity = 0.85;
      } else {
        const k = Math.min(Math.max((now - d.start) / 520, 0), 1), e = ease(k);
        mesh.position.y = d.y + d.lift * (1 - e);
        mesh.material.opacity = Math.min(k * 2.5, 1);
      }
    }
    this.renderer.render(this.scene, this.camera);
    requestAnimationFrame(this.frame);
  }

  dispose() {
    this.disposed = true;
    this.resize.disconnect();
    this.clear();
    this.renderer.dispose();
  }
}
