import {itemPose, normalizedQuaternion} from './pose.js';

export const COLORS = [0x36a58a, 0xe4ad58, 0x709dcc, 0xa591cf, 0xdc887f, 0x84ad65];

// Inspection only: expand centers uniformly, leaving every solid's shape intact.
// Uniform expansion preserves a separating plane between disjoint convex solids.
export function inspectionCenter(center, bin, amount) {
  if (!amount) return [...center];
  return center.map((value,axis) => {
    const origin=[bin.width,bin.length,bin.height][axis]/2;
    return origin+(value-origin)*(1+2.5*amount);
  });
}

function numberLabel(THREE, number, size) {
  const canvas=document.createElement('canvas');canvas.width=128;canvas.height=128;
  const context=canvas.getContext('2d');
  context.fillStyle='#ffffff';context.beginPath();context.arc(64,64,53,0,Math.PI*2);context.fill();
  context.strokeStyle='#184c41';context.lineWidth=8;context.stroke();
  context.fillStyle='#173b34';context.font='bold 60px system-ui, sans-serif';
  context.textAlign='center';context.textBaseline='middle';context.fillText(String(number),64,68);
  const texture=new THREE.CanvasTexture(canvas);
  const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:texture,transparent:true,depthTest:false}));
  sprite.scale.set(size,size,1);sprite.renderOrder=10;sprite.userData.number=number;
  return sprite;
}

export function createItemMesh(THREE, pose, color) {
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(pose.width, pose.length, pose.height),
    new THREE.MeshStandardMaterial({color, roughness: .55, metalness: .02})
  );
  mesh.position.fromArray(pose.center);
  mesh.quaternion.fromArray(normalizedQuaternion(pose.orientation));
  const edge = new THREE.LineSegments(
    new THREE.EdgesGeometry(mesh.geometry),
    new THREE.LineBasicMaterial({color: 0x173a34, transparent: true, opacity: .42})
  );
  mesh.add(edge);
  return mesh;
}

export function buildPackingScene(THREE, result) {
  const root = new THREE.Group();
  const boxes = [];
  const items = [];
  const schema = result.schema_version || 1;
  const widest = Math.max(1, ...result.bins.map(b => Math.max(b.width, b.length, b.height)));
  const maxWidth = Math.max(1, ...result.bins.map(b => b.width));
  const maxLength = Math.max(1, ...result.bins.map(b => b.length));
  const columns = Math.max(1,Math.ceil(Math.sqrt(result.bins.length * 1.6)));
  result.bins.forEach((bin, boxIndex) => {
    const group = new THREE.Group();
    // Container origin is its lower, left, near corner. Keep every item pose intact.
    const offset=[(boxIndex%columns)*(maxWidth+widest*.35),Math.floor(boxIndex/columns)*(maxLength+widest*.35)];
    group.position.set(offset[0],offset[1],0);
    const geometry = new THREE.BoxGeometry(bin.width, bin.length, bin.height);
    const shell = new THREE.Mesh(geometry, new THREE.MeshPhysicalMaterial({
      color: 0xb4cad4, transparent: true, opacity: .085, depthWrite: false,
      side: THREE.DoubleSide, roughness: .85
    }));
    shell.position.set(bin.width / 2, bin.length / 2, bin.height / 2);
    group.add(shell);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry),
      new THREE.LineBasicMaterial({color: 0x5c7883, transparent: true, opacity: .7}));
    edges.position.copy(shell.position);
    group.add(edges);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(bin.width, bin.length),
      new THREE.MeshStandardMaterial({color: 0xe0e8ec, side: THREE.DoubleSide, roughness: 1}));
    floor.position.set(bin.width / 2, bin.length / 2, -.001 * widest);
    group.add(floor);
    bin.items.forEach((item, itemIndex) => {
      const pose = itemPose(item, schema);
      const mesh = createItemMesh(THREE, pose, COLORS[items.length % COLORS.length]);
      mesh.userData = {boxIndex, itemIndex, base: mesh.position.clone(), pose};
      group.add(mesh);
      const label=numberLabel(THREE, items.length+1, Math.max(2.5,Math.min(14,widest*.13)));
      label.position.copy(mesh.position);label.position.z+=Math.max(item.height*.15,widest*.025);
      group.add(label);
      items.push({mesh, label, pose, item, boxIndex, itemIndex, color: COLORS[items.length % COLORS.length]});
    });
    root.add(group);
    boxes.push({group, bin, offset});
  });
  return {root, boxes, items};
}

export function disposePackingScene(scene) {
  scene?.root.traverse(object => {
    object.geometry?.dispose();
    if (Array.isArray(object.material)) object.material.forEach(material => material.dispose());
    else {object.material?.map?.dispose();object.material?.dispose();}
  });
}
