import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, Line, OrbitControls } from "@react-three/drei";

/** Secondary's nominal path relative to the primary (origin), axes R/T/N. */
export default function RelativeScene({ rtn, t }: { rtn: number[][]; t: number[] }) {
  const { pts, scale, closest } = useMemo(() => {
    const maxAbs = Math.max(...rtn.flat().map(Math.abs), 1e-3);
    const s = 4 / maxAbs;
    let ci = 0, cd = Infinity;
    rtn.forEach((p, i) => { const d = Math.hypot(p[0]!, p[1]!, p[2]!); if (d < cd) { cd = d; ci = i; } });
    // three.js: x=T (in-track), y=R (radial), z=N
    const pts = rtn.map((p) => [p[1]! * s, p[0]! * s, p[2]! * s] as [number, number, number]);
    return { pts, scale: s, closest: ci };
  }, [rtn]);
  const c = pts[closest]!;
  const axis = (to: [number, number, number], label: string) => (
    <>
      <Line points={[[0, 0, 0], to]} color="#888" lineWidth={1} />
      <Html position={to} style={{ color: "#aaa", fontSize: 11, fontFamily: "var(--fm)" }}>{label}</Html>
    </>
  );
  return (
    <Canvas camera={{ position: [6, 4, 7], fov: 45 }} style={{ background: "var(--s1)" }} aria-label="3D relative trajectory">
      <ambientLight intensity={0.8} />
      {axis([5, 0, 0], "T")}{axis([0, 5, 0], "R")}{axis([0, 0, 5], "N")}
      <Line points={pts} color="#ff5a36" lineWidth={2} />
      <mesh position={[0, 0, 0]}><sphereGeometry args={[0.12, 16, 16]} /><meshBasicMaterial color="#f5f0e8" /></mesh>
      <mesh position={c}><sphereGeometry args={[0.12, 16, 16]} /><meshBasicMaterial color="#ffc500" /></mesh>
      <Html position={c} style={{ color: "#ffc500", fontSize: 11, fontFamily: "var(--fm)", whiteSpace: "nowrap" }}>TCA {t[closest]?.toFixed(1)} s</Html>
      <Html position={[-4.5, -4, 0]} style={{ color: "#999", fontSize: 10, fontFamily: "var(--fm)", whiteSpace: "nowrap" }}>scale {(1 / scale).toFixed(3)} km/unit · nominal (no uncertainty)</Html>
      <OrbitControls enablePan enableZoom />
    </Canvas>
  );
}
