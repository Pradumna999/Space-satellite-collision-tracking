import { useEffect, useMemo, useRef, type MutableRefObject } from "react";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";
import { BufferAttribute, BufferGeometry, Color, Sphere, Vector3, type Group, type Mesh } from "three";
import type { Tracks } from "../api/types";
import { makeEarthTexture } from "./earthTexture";

const RE = 6378.137;
/** GCRF km -> scene units (Earth radius = 1), three.js y-up: (x, z, -y). */
export const toScene = (r: number[]): [number, number, number] => [r[0]! / RE, r[2]! / RE, -r[1]! / RE];

/** Earth Rotation Angle (IAU 2000) with UT1 approximated by UTC — visual use only. */
export function eraRad(ms: number): number {
  const du = ms / 86400000 + 2440587.5 - 2451545.0;
  const turns = 0.779057273264 + 1.0027378119113546 * du;
  return 2 * Math.PI * (turns - Math.floor(turns));
}

export interface SimClock { t: number; playing: boolean; speed: number }

/** Linear interpolation of an object's samples at time ms; false if outside data. */
function sample(r: (number | null)[], startMs: number, stepMs: number, n: number, ms: number, out: number[]): boolean {
  const f = (ms - startMs) / stepMs;
  if (f < 0 || f > n - 1) return false;
  const k = Math.min(Math.floor(f), n - 2);
  const a = f - k;
  for (let c = 0; c < 3; c++) {
    const x0 = r[k * 3 + c], x1 = r[(k + 1) * 3 + c];
    if (x0 === null || x0 === undefined || x1 === null || x1 === undefined) return false;
    out[c] = x0 + (x1 - x0) * a;
  }
  return true;
}

function Earth({ clock }: { clock: MutableRefObject<SimClock> }) {
  const ref = useRef<Mesh>(null);
  const tex = useMemo(() => makeEarthTexture(true), []);
  useEffect(() => () => tex.dispose(), [tex]);
  useFrame(() => { if (ref.current) ref.current.rotation.y = eraRad(clock.current.t); });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[1, 64, 48]} />
      <meshStandardMaterial map={tex} roughness={1} metalness={0} />
    </mesh>
  );
}

function Swarm({ data, clock, selected, highlight, onSelect, onTick, end }: {
  data: Tracks; clock: MutableRefObject<SimClock>; selected: string | null; highlight: Set<string>;
  onSelect: (id: string) => void; onTick: (ms: number) => void; end: number;
}) {
  const n = data.objects.length;
  const startMs = Date.parse(data.start_utc);
  const stepMs = data.step_s * 1000;
  const lastTick = useRef(0);
  const labelRef = useRef<Group>(null);
  const tmp = useMemo(() => [0, 0, 0], []);
  const geom = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute("position", new BufferAttribute(new Float32Array(n * 3), 3));
    g.setAttribute("color", new BufferAttribute(new Float32Array(n * 3), 3));
    g.boundingSphere = new Sphere(new Vector3(0, 0, 0), 20); // fixed: no per-frame recomputation
    return g;
  }, [n]);
  useEffect(() => () => geom.dispose(), [geom]);
  useEffect(() => {
    const col = geom.getAttribute("color") as BufferAttribute;
    const base = new Color("#e8e2d8"), deb = new Color("#8f8a84"), hi = new Color("#ffc500"), sel = new Color("#ff5a36");
    data.objects.forEach((o, i) => {
      const c = o.object_id === selected ? sel : highlight.has(o.object_id) ? hi : (o.name ?? "").toUpperCase().includes("DEB") ? deb : base;
      col.setXYZ(i, c.r, c.g, c.b);
    });
    col.needsUpdate = true;
  }, [data, selected, highlight, geom]);
  const selIndex = useMemo(() => data.objects.findIndex((o) => o.object_id === selected), [data, selected]);

  useFrame((_, delta) => {
    const ck = clock.current;
    // Cap the step at 1 s of wall time so returning to a backgrounded tab does not jump far ahead.
    if (ck.playing) ck.t = Math.min(ck.t + Math.min(delta, 1) * 1000 * ck.speed, end);
    const pos = geom.getAttribute("position") as BufferAttribute;
    const arr = pos.array as Float32Array;
    for (let i = 0; i < n; i++) {
      if (sample(data.objects[i]!.r, startMs, stepMs, data.samples, ck.t, tmp)) {
        arr[i * 3] = tmp[0]! / RE; arr[i * 3 + 1] = tmp[2]! / RE; arr[i * 3 + 2] = -tmp[1]! / RE;
      } else {
        arr[i * 3] = arr[i * 3 + 1] = arr[i * 3 + 2] = 0; // hidden inside the Earth
      }
    }
    pos.needsUpdate = true;
    if (labelRef.current && selIndex >= 0) labelRef.current.position.set(arr[selIndex * 3]!, arr[selIndex * 3 + 1]!, arr[selIndex * 3 + 2]!);
    // Report the clock to React a few times per second only.
    const now = performance.now();
    if (now - lastTick.current > 250) {
      lastTick.current = now;
      onTick(ck.t);
    }
  });

  const size = n > 1500 ? 2.5 : n > 600 ? 3 : 4;
  return (
    <>
      <points geometry={geom} onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); if (e.index !== undefined && data.objects[e.index]) onSelect(data.objects[e.index]!.object_id); }}>
        <pointsMaterial size={size} sizeAttenuation={false} vertexColors />
      </points>
      {selIndex >= 0 && (
        <group ref={labelRef}>
          <Html style={{ color: "#f5f0e8", fontSize: 11, fontFamily: "var(--fm)", whiteSpace: "nowrap", transform: "translate(8px,-6px)", pointerEvents: "none" }}>
            {data.objects[selIndex]!.name ?? data.objects[selIndex]!.object_id}
          </Html>
        </group>
      )}
    </>
  );
}

/** Orbit line; points are already in scene units (see toScene). */
export interface TrackLine { id: string; points: [number, number, number][]; color: string }

export default function EarthScene({ data, clock, end, selected, highlight, tracks, showAxes, onSelect, onTick, marker }: {
  data: Tracks; clock: MutableRefObject<SimClock>; end: number; selected: string | null; highlight: Set<string>; tracks: TrackLine[];
  showAxes: boolean; onSelect: (id: string) => void; onTick: (ms: number) => void; marker?: { at: number[]; label: string } | null;
}) {
  return (
    <Canvas camera={{ position: [0, 1.6, 4.2], fov: 45, near: 0.01, far: 200 }} dpr={[1, 1.5]} raycaster={{ params: { Points: { threshold: 0.03 } } as never }}>
      <color attach="background" args={["#05070a"]} />
      <ambientLight intensity={0.9} />
      <directionalLight position={[5, 3, 5]} intensity={1.1} />
      <Earth clock={clock} />
      {showAxes && (<>
        <Line points={[[0, 0, 0], [1.8, 0, 0]]} color="#a33" lineWidth={1} />
        <Line points={[[0, 0, 0], [0, 1.8, 0]]} color="#36a" lineWidth={1} />
        <Html position={[1.85, 0, 0]} style={{ color: "#c66", fontSize: 10, fontFamily: "var(--fm)" }}>X (GCRF)</Html>
        <Html position={[0, 1.85, 0]} style={{ color: "#69c", fontSize: 10, fontFamily: "var(--fm)" }}>Z</Html>
      </>)}
      <Swarm data={data} clock={clock} selected={selected} highlight={highlight} onSelect={onSelect} onTick={onTick} end={end} />
      {tracks.map((t) => t.points.length > 1 && <Line key={t.id} points={t.points} color={t.color} lineWidth={1.5} transparent opacity={0.85} />)}
      {marker && (<>
        <mesh position={toScene(marker.at)}><sphereGeometry args={[0.015, 12, 12]} /><meshBasicMaterial color="#ffc500" /></mesh>
        <Html position={toScene(marker.at)} style={{ color: "#ffc500", fontSize: 11, fontFamily: "var(--fm)", whiteSpace: "nowrap", transform: "translate(8px,-8px)" }}>{marker.label}</Html>
      </>)}
      <OrbitControls enablePan={false} enableZoom minDistance={1.3} maxDistance={20} />
    </Canvas>
  );
}
