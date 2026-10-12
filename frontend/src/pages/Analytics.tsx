import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from "recharts";
import { api, downloadCsv, qs } from "../api/client";
import type { CatalogueRow, Encounter, Finding, Paged } from "../api/types";
import { useProjectId } from "../components/Layout";
import VersionPicker from "../components/VersionPicker";
import { ChartMeta, Empty, Explain, PageHead, Panel, PcBadge } from "../components/ui";
import { useDatasets, useEncounters, useJobs, versionsOf } from "../lib/hooks";
import { km, kms, parseUtc, utc } from "../lib/format";

const tip = { contentStyle: { background: "var(--s1)", border: "1px solid var(--hair)", fontSize: 12 } };
const axis = { stroke: "var(--muted)", fontSize: 11 };

interface Bench { environment: Record<string, string | number>; results: { objects: number; runtime_s: number; pairs_total: number; pairs_flagged: number; peak_traced_memory_mb: number; window_h: number; step_s: number }[] }

export default function Analytics() {
  const pid = useProjectId();
  const jobs = useJobs(pid);
  const ds = useDatasets(pid);
  const screenJobs = (jobs.data?.items ?? []).filter((j) => j.status === "succeeded");
  const [jobId, setJobId] = useState<number | null>(null);
  const jid = jobId ?? (screenJobs.find((j) => j.kind === "screening") ?? screenJobs[0])?.id;
  const enc = useEncounters(pid, { job_id: jid, limit: 500 });
  const [sel, setSel] = useState<Encounter | null>(null);
  const [vid, setVid] = useState<number | null>(null);
  const v = vid ?? versionsOf(ds.data?.items)[0]?.v.id ?? null;
  const cat = useQuery({ queryKey: ["cat-all", pid, v], enabled: v !== null, queryFn: () => api.get<Paged<CatalogueRow>>(`/projects/${pid}/catalogue${qs({ vid: v, limit: 500 })}`) });
  const findings = useQuery({ queryKey: ["findings-all", pid, v], enabled: v !== null, queryFn: () => api.get<Paged<Finding>>(`/projects/${pid}/dataset-versions/${v}/findings${qs({ limit: 500 })}`) });
  const covs = useQuery({ queryKey: ["covs", pid, v], enabled: v !== null, queryFn: () => api.get<{ items: { object_id: string; frame: string; eigenvalues: number[]; valid: boolean; matrix_km: number[][] }[] }>(`/projects/${pid}/dataset-versions/${v}/covariances`) });
  const sys = useQuery({ queryKey: ["sys"], queryFn: () => api.get<{ benchmark: Bench | null }>("/system/info") });

  const pts = useMemo(() => (enc.data?.items ?? []).map((e) => ({ t: Date.parse(e.tca_utc), miss: e.miss_km, speed: e.rel_speed_km_s, id: e.id, e })), [enc.data]);
  const refTime = Date.now();
  const ages = useMemo(() => {
    const bins = [0, 1, 2, 3, 5, 7, 14, 30, 90, Infinity];
    const counts = bins.slice(0, -1).map((b, i) => ({ bin: `${b}–${bins[i + 1] === Infinity ? "∞" : bins[i + 1]} d`, n: 0 }));
    for (const r of cat.data?.items ?? []) {
      const a = (refTime - parseUtc(r.epoch)) / 86400000;
      const i = bins.findIndex((b, k) => a >= b && a < bins[k + 1]!);
      if (i >= 0) counts[i]!.n++;
    }
    return counts;
  }, [cat.data, refTime]);
  const fcounts = useMemo(() => {
    const m = new Map<string, { code: string; error: number; warning: number; info: number }>();
    for (const f of findings.data?.items ?? []) {
      const r = m.get(f.code) ?? { code: f.code, error: 0, warning: 0, info: 0 };
      r[f.severity]++;
      m.set(f.code, r);
    }
    return [...m.values()].sort((a, b) => b.error + b.warning - (a.error + a.warning));
  }, [findings.data]);
  const covRows = (covs.data?.items ?? []).map((c) => {
    const pos = [c.matrix_km[0]![0]!, c.matrix_km[1]![1]!, c.matrix_km[2]![2]!].map((x) => Math.sqrt(Math.max(x, 0)) * 1000);
    return { object: c.object_id, frame: c.frame, s1: pos[0], s2: pos[1], s3: pos[2], cond: Math.max(...c.eigenvalues) / Math.max(Math.min(...c.eigenvalues.map(Math.abs)), 1e-300), valid: c.valid };
  });
  const bench = sys.data?.benchmark;
  const jobKind = "computed";

  return (
    <div className="page">
      <PageHead eyebrow="Charts" title="The results as charts">
        Every chart is drawn from stored results and can be downloaded as CSV. A short note under each one explains how to read it.
      </PageHead>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <label className="field">Analysis run<select value={jid ?? ""} onChange={(e) => { setJobId(Number(e.target.value)); setSel(null); }}>
          {screenJobs.map((j) => <option key={j.id} value={j.id}>#{j.id} · {j.kind.replace("_", " ")}</option>)}
        </select></label>
        <VersionPicker datasets={ds.data?.items} value={v} onChange={setVid} label="Dataset version (quality charts)" />
      </div>
      <div className="grid cols-2">
        <Panel title="When and how close" meta="each dot is one close pass" actions={<button className="btn small" onClick={() => downloadCsv(`timeline-job${jid}.csv`, ["encounter_id", "tca_utc", "miss_km", "rel_speed_km_s"], pts.map((p) => [p.id, p.e.tca_utc, p.miss, p.speed]), [`job ${jid}`])}>CSV</button>}>
          {pts.length === 0 ? <Empty>No encounters in this run.</Empty> : (
            <div className="chart-box">
              <ResponsiveContainer>
                <ScatterChart margin={{ left: 8, right: 20, top: 12, bottom: 20 }}>
                  <CartesianGrid stroke="var(--hair)" />
                  <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} {...axis} tickFormatter={(t: number) => new Date(t).toISOString().slice(5, 16).replace("T", " ")} name="TCA (UTC)" />
                  <YAxis dataKey="miss" {...axis} name="miss" unit=" km" />
                  <ZAxis range={[40, 40]} />
                  <Tooltip {...tip} formatter={(val, name) => [name === "TCA (UTC)" ? new Date(Number(val)).toISOString() : Number(val).toFixed(3), name]} />
                  <Scatter data={pts} fill="var(--acc)" onClick={(d: { payload?: { e: Encounter } }) => d.payload && setSel(d.payload.e)} cursor="pointer" isAnimationActive={false} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
          <ChartMeta units="km vs TCA" time="UTC" source={`job #${jid ?? "—"}`} kind={jobKind} />
          <Explain>Left to right is time; lower dots are closer passes. Clusters show busy periods. Click a dot to open that close pass.</Explain>
        </Panel>
        <Panel title="Distance vs impact speed" meta="each dot is one close pass" actions={<button className="btn small" onClick={() => downloadCsv(`miss-speed-job${jid}.csv`, ["encounter_id", "rel_speed_km_s", "miss_km"], pts.map((p) => [p.id, p.speed, p.miss]))}>CSV</button>}>
          {pts.length > 0 && (
            <div className="chart-box">
              <ResponsiveContainer>
                <ScatterChart margin={{ left: 8, right: 20, top: 12, bottom: 20 }}>
                  <CartesianGrid stroke="var(--hair)" />
                  <XAxis dataKey="speed" type="number" {...axis} name="relative speed" unit=" km/s" />
                  <YAxis dataKey="miss" {...axis} name="miss" unit=" km" />
                  <ZAxis range={[40, 40]} />
                  <Tooltip {...tip} />
                  <Scatter data={pts} fill="var(--accT)" onClick={(d: { payload?: { e: Encounter } }) => d.payload && setSel(d.payload.e)} cursor="pointer" isAnimationActive={false} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
          <ChartMeta units="km, km/s" source={`job #${jid ?? "—"}`} kind={jobKind} />
          <Explain>How fast the two objects would hit each other (right = faster) against how close they pass (down = closer). Dots low and to the right are the most serious: close and very fast.</Explain>
        </Panel>
      </div>
      {sel && (
        <div className="notice info" style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap" }}>
          <strong>Selected:</strong> EVT-{String(sel.id).padStart(4, "0")} · {sel.primary_id} × {sel.secondary_id} · {utc(sel.tca_utc)} · {km(sel.miss_km)} · {kms(sel.rel_speed_km_s)} <PcBadge status={sel.pc_status} value={sel.pc_value} />
          <Link to={`/p/${pid}/encounters/${sel.id}`}>Investigate</Link><Link to={`/p/${pid}/environment?encounter=${sel.id}`}>3D</Link>
        </div>
      )}
      <div className="grid cols-2">
        <Panel title="How fresh is the data" meta="age of each object's last orbit update" actions={<button className="btn small" onClick={() => downloadCsv(`freshness-v${v}.csv`, ["age_bin", "records"], ages.map((a) => [a.bin, a.n]))}>CSV</button>}>
          <div className="chart-box" style={{ height: 240 }}>
            <ResponsiveContainer>
              <BarChart data={ages} margin={{ left: 8, right: 20, top: 12, bottom: 12 }}>
                <CartesianGrid stroke="var(--hair)" vertical={false} />
                <XAxis dataKey="bin" {...axis} /><YAxis {...axis} allowDecimals={false} />
                <Tooltip {...tip} /><Bar dataKey="n" name="records" fill="var(--acc)" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ChartMeta units="record count per age bin (days)" time="UTC epochs vs browser clock" source={`dataset version #${v ?? "—"} (first 500 records)`} kind="supplied" />
          <Explain>Orbit data gets less accurate as it ages. Most bars should sit on the left (recent). Objects older than about 3 days are flagged as stale.</Explain>
        </Panel>
        <Panel title="Data quality checks" meta="problems found when the data was loaded" actions={<button className="btn small" onClick={() => downloadCsv(`findings-v${v}.csv`, ["code", "errors", "warnings", "info"], fcounts.map((f) => [f.code, f.error, f.warning, f.info]))}>CSV</button>}>
          {fcounts.length === 0 ? <Empty>No findings for this version.</Empty> : (
            <div className="chart-box" style={{ height: 240 }}>
              <ResponsiveContainer>
                <BarChart data={fcounts.slice(0, 10)} layout="vertical" margin={{ left: 30, right: 20, top: 8, bottom: 8 }}>
                  <CartesianGrid stroke="var(--hair)" horizontal={false} />
                  <XAxis type="number" {...axis} allowDecimals={false} /><YAxis type="category" dataKey="code" width={190} {...axis} />
                  <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="error" stackId="a" fill="var(--alert)" name="errors" isAnimationActive={false} />
                  <Bar dataKey="warning" stackId="a" fill="var(--warn)" name="warnings" isAnimationActive={false} />
                  <Bar dataKey="info" stackId="a" fill="var(--muted)" name="info" isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
          <ChartMeta units="finding count" source={`dataset version #${v ?? "—"} validation`} kind="computed" />
          <Explain>Every record is checked on upload. Red bars are errors (that record is not used); yellow bars are warnings to be aware of, such as stale or duplicate entries.</Explain>
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Position uncertainty" meta="how well each object's position is known (1σ)">
          {covRows.length === 0 ? <Empty>This dataset version contains no covariance (e.g. TLE/OMM). Choose a CDM or OEM dataset.</Empty> : (
            <div className="table-wrap"><table className="data">
              <thead><tr><th>Object</th><th>Frame</th><th className="num">σ₁ m</th><th className="num">σ₂ m</th><th className="num">σ₃ m</th><th className="num">Condition no.</th><th>Valid</th></tr></thead>
              <tbody>{covRows.map((c, i) => <tr key={i}><td className="mono">{c.object}</td><td className="mono">{c.frame}</td><td className="num">{c.s1?.toFixed(1)}</td><td className="num">{c.s2?.toFixed(1)}</td><td className="num">{c.s3?.toFixed(1)}</td><td className="num">{c.cond.toExponential(1)}</td><td>{c.valid ? "yes" : <span className="badge alert">no</span>}</td></tr>)}</tbody>
            </table></div>
          )}
          <ChartMeta units="metres; condition number dimensionless (6×6)" source={`dataset version #${v ?? "—"}`} kind="supplied" />
        </Panel>
        <Panel title="Speed of the search" meta="time taken as the number of objects grows">
          {!bench ? <Empty>No benchmark stored. Run <span className="mono">python -m astral.cli benchmark</span> on this host.</Empty> : (<>
            <div className="chart-box" style={{ height: 230 }}>
              <ResponsiveContainer>
                <LineChart data={bench.results} margin={{ left: 8, right: 20, top: 12, bottom: 18 }}>
                  <CartesianGrid stroke="var(--hair)" />
                  <XAxis dataKey="objects" type="number" scale="log" domain={["dataMin", "dataMax"]} {...axis} label={{ value: "objects", position: "insideBottom", offset: -8, fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis {...axis} unit=" s" />
                  <Tooltip {...tip} />
                  <Line dataKey="runtime_s" name="runtime" stroke="var(--acc)" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="chart-meta">{Object.entries(bench.environment).map(([k, val]) => <span key={k}>{k}: {String(val)}</span>)}</div>
          </>)}
        </Panel>
      </div>
    </div>
  );
}
