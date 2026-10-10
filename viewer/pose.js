// Solver coordinates are right-handed, Z up. All mesh positions are centers.
export function itemPose(item, schemaVersion = 1) {
  if (schemaVersion === 2) {
    return {
      width: item.width, length: item.length, height: item.height,
      center: [...item.center], orientation: [...item.orientation]
    };
  }
  const half = item.angle * Math.PI / 360;
  return {
    width: item.width, length: item.length, height: item.height,
    center: [item.x, item.y, item.z + item.height / 2],
    orientation: [0, 0, Math.sin(half), Math.cos(half)]
  };
}

export function normalizedQuaternion(q) {
  const norm = Math.hypot(...q);
  if (!Number.isFinite(norm) || norm === 0) throw new Error('Invalid product orientation.');
  return q.map(component => component / norm);
}
