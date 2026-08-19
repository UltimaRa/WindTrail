// Local ENU-ish projection: x = east (m), z = south (m), y = up.
// Centered on the data bbox; north is -z.

let C = null;

export function initGeo(bbox) {
  const lat0 = (bbox.minLat + bbox.maxLat) / 2;
  const lon0 = (bbox.minLon + bbox.maxLon) / 2;
  C = {
    bbox,
    lat0,
    lon0,
    mPerDegLat: 111320,
    mPerDegLon: 111320 * Math.cos((lat0 * Math.PI) / 180),
  };
}

export function lonToX(lon) { return (lon - C.lon0) * C.mPerDegLon; }
export function latToZ(lat) { return (C.lat0 - lat) * C.mPerDegLat; }
export function xToLon(x) { return C.lon0 + x / C.mPerDegLon; }
export function zToLat(z) { return C.lat0 - z / C.mPerDegLat; }
export function widthM() { return (C.bbox.maxLon - C.bbox.minLon) * C.mPerDegLon; }
export function heightM() { return (C.bbox.maxLat - C.bbox.minLat) * C.mPerDegLat; }
export function getBbox() { return C.bbox; }
