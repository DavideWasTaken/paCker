// Fit world bounds in the camera's projected horizontal and vertical extents.
export function fitPackingCamera(THREE, camera, bounds, direction, margin=.9) {
  const center=bounds.getCenter(new THREE.Vector3());
  const size=bounds.getSize(new THREE.Vector3());
  const extent=Math.max(size.x,size.y,size.z,1e-6);
  const eye=direction.lengthSq() ? direction.clone().normalize() : new THREE.Vector3(.8,-1,.78).normalize();
  const right=new THREE.Vector3().crossVectors(camera.up,eye).normalize();
  const up=new THREE.Vector3().crossVectors(eye,right).normalize();
  const tanY=Math.tan(THREE.MathUtils.degToRad(camera.fov/2))*margin;
  const tanX=tanY*camera.aspect;
  let distance=extent*.01;
  for (const x of [bounds.min.x,bounds.max.x]) for (const y of [bounds.min.y,bounds.max.y]) for (const z of [bounds.min.z,bounds.max.z]) {
    const p=new THREE.Vector3(x,y,z).sub(center);
    distance=Math.max(distance,p.dot(eye)+Math.abs(p.dot(right))/tanX,p.dot(eye)+Math.abs(p.dot(up))/tanY);
  }
  camera.position.copy(center).addScaledVector(eye,distance);
  camera.near=Math.max(1e-10,distance/10000);
  camera.far=distance+extent*10;
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
  return {center,extent,distance};
}
