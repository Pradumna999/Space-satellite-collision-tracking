import { CanvasTexture, SRGBColorSpace } from "three";
import { feature, mesh } from "topojson-client";
import type { Topology, GeometryCollection } from "topojson-specification";
import land110 from "world-atlas/land-110m.json";
import countries110 from "world-atlas/countries-110m.json";

/**
 * Equirectangular Earth texture drawn locally from Natural Earth 1:110m data
 * (world-atlas, public domain). No imagery is downloaded at run time.
 */
export function makeEarthTexture(dark = true): CanvasTexture {
  const W = 2048, H = 1024;
  const c = document.createElement("canvas");
  c.width = W;
  c.height = H;
  const g = c.getContext("2d")!;
  g.fillStyle = dark ? "#16304a" : "#c9d6e2";
  g.fillRect(0, 0, W, H);
  const px = (lon: number, lat: number): [number, number] => [((lon + 180) / 360) * W, ((90 - lat) / 180) * H];
  const draw = (rings: number[][][]) => {
    for (const ring of rings) {
      g.beginPath();
      ring.forEach(([lon, lat], i) => {
        const [x, y] = px(lon!, lat!);
        if (i === 0) g.moveTo(x, y);
        else g.lineTo(x, y);
      });
      g.closePath();
    }
  };
  const land = feature(land110 as unknown as Topology, (land110 as unknown as Topology).objects.land as GeometryCollection);
  g.fillStyle = dark ? "#5a5f58" : "#f2efe8";
  for (const f of land.features) {
    const geom = f.geometry;
    const polys = geom.type === "Polygon" ? [geom.coordinates] : geom.type === "MultiPolygon" ? geom.coordinates : [];
    for (const p of polys) {
      draw(p as number[][][]);
      g.fill("evenodd");
    }
  }
  const borders = mesh(countries110 as unknown as Topology, (countries110 as unknown as Topology).objects.countries as GeometryCollection, (a, b) => a !== b);
  g.strokeStyle = dark ? "rgba(255,255,255,0.22)" : "rgba(0,0,0,0.15)";
  g.lineWidth = 1;
  for (const line of borders.coordinates) {
    g.beginPath();
    line.forEach(([lon, lat], i) => {
      const [x, y] = px(lon!, lat!);
      if (i === 0) g.moveTo(x, y);
      else g.lineTo(x, y);
    });
    g.stroke();
  }
  g.strokeStyle = dark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.08)";
  for (let lon = -180; lon <= 180; lon += 30) { const [x] = px(lon, 0); g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H); g.stroke(); }
  for (let lat = -60; lat <= 60; lat += 30) { const [, y] = px(0, lat); g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  const t = new CanvasTexture(c);
  t.colorSpace = SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}
