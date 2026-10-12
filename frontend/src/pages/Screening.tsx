import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { useProjectId } from "../components/Layout";
import VersionPicker from "../components/VersionPicker";
import { ChartMeta, Empty, ErrorView, Explain, JobStatus, Kv, PageHead, Panel, Seg } from "../components/ui";
import { useDatasets, useJobs, versionsOf } from "../lib/hooks";
import { utc } from "../lib/format";

function nowIso(): string {
  const d = new Date();
  d.setUTCMinutes(0, 0, 0);
  return d.toISOString().slice(0, 19);
}

function ScreeningForm({ pid }: { pid: number }) {
  const qc = useQueryClient();
  const ds = useDatasets(pid);
  const [vid, setVid] = useState<number | null>(null);
  const [start, setStart] = useState(nowIso());
  const [hours, setHours] = useState(72);
  const [step, setStep] = useState(30);
  const [thr, setThr] = useState(5);
  const [primaries, setPrimaries] = useState("");
  const isProp = (f: string) => !f.startsWith("CDM") && !f.startsWith("STATES");
  useEffect(() => {
    if (vid === null && ds.data) setVid(versionsOf(ds.data.items).find((x) => isProp(x.v.format))?.v.id ?? null);
  }, [ds.data, vid]);
  const submit = useMutation({
    mutationFn: () => api.post<Job>(`/projects/${pid}/jobs`, {
      dataset_version_id: vid,
      config: { kind: "screening", start_utc: `${start}Z`, duration_hours: hours, step_s: step, threshold_km: thr,
                primary_ids: primaries.trim() ? primaries.split(/[\s,]+/).filter(Boolean) : null },
    }, { "Idempotency-Key": crypto.randomUUID() }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", pid] }),
  });
  return (
    <Panel title="New search" meta="uses every object in the chosen data">
      <form className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 14 }} onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
        <VersionPicker datasets={ds.data?.items} value={vid} onChange={setVid} filter={isProp} label="Dataset version (GP elements or ephemerides)" />
        <div className="grid cols-4">
          <label className="field">Window start (UTC)<input className="mono" type="datetime-local" step={1} value={start} onChange={(e) => setStart(e.target.value)} required /></label>
          <label className="field">Duration (h)<input className="mono" type="number" min={0.1} max={336} step={0.1} value={hours} onChange={(e) => setHours(Number(e.target.value))} /></label>
          <label className="field">Grid step (s)<input className="mono" type="number" min={0.5} max={600} step={0.5} value={step} onChange={(e) => setStep(Number(e.target.value))} />
            <span className="hint">Must be ≤ P_min/20; completeness guaranteed by a conservative proximity bound.</span></label>
          <label className="field">Screening threshold (km)<input className="mono" type="number" min={0.01} max={200} step={0.1} value={thr} onChange={(e) => setThr(Number(e.target.value))} /></label>
        </div>
        <label className="field">Primary objects (optional)<input className="mono" value={primaries} onChange={(e) => setPrimaries(e.target.value)} placeholder="ids separated by commas; empty = all pairs" /></label>
        {submit.error && <ErrorView error={submit.error} />}
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn primary" disabled={vid === null || submit.isPending}>Run screening →</button>
          <span className="muted" style={{ fontSize: 12 }}>Runs as a background job. Encounters meeting the threshold are geometric results; probability requires covariance.</span>
        </div>
      </form>
    </Panel>
  );
}

function CdmForm({ pid }: { pid: number }) {
  const qc = useQueryClient();
  const ds = useDatasets(pid);
  const [vid, setVid] = useState<number | null>(null);
  const [hbr, setHbr] = useState<string>("");
  const [method, setMethod] = useState<"2d" | "mc" | "3d">("2d");
  const [samples, setSamples] = useState(500000);
  const isCdm = (f: string) => f === "CDM_KVN";
  useEffect(() => { if (vid === null && ds.data) setVid(versionsOf(ds.data.items).find((x) => isCdm(x.v.format))?.v.id ?? null); }, [ds.data, vid]);
  const submit = useMutation({
    mutationFn: () => api.post<Job>(`/projects/${pid}/jobs`, {
      dataset_version_id: vid,
      config: { kind: "cdm_assessment", hbr_m: hbr ? Number(hbr) : null, monte_carlo_samples: method === "mc" ? samples : 0, seed: 0 },
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", pid] }),
  });
  return (
    <Panel title="Check a conjunction message" meta="computes the chance of collision">
      <form className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 14 }} onSubmit={(e) => { e.preventDefault(); submit.mutate(); }}>
        <VersionPicker datasets={ds.data?.items} value={vid} onChange={setVid} filter={isCdm} label="CDM dataset version" />
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field">Combined hard-body radius (m)<input className="mono" type="number" min={0.01} max={1000} step={0.01} value={hbr} onChange={(e) => setHbr(e.target.value)} placeholder="required for Pc" />
            <span className="hint">Without it, Pc is reported as INSUFFICIENT_DATA_FOR_PC.</span></label>
          <div className="field">Pc method
            <Seg label="Pc method" value={method} onChange={setMethod} options={[
              { value: "2d", label: "2D" },
              { value: "3d", label: "3D", disabled: true, title: "Not implemented. ASTRAL does not substitute another method." },
              { value: "mc", label: "Monte Carlo", title: "2D Foster plus a rectilinear Monte Carlo cross-check" },
            ]} />
          </div>
          {method === "mc" && <label className="field">Samples<input className="mono" type="number" min={10000} max={5000000} step={10000} value={samples} onChange={(e) => setSamples(Number(e.target.value))} /></label>}
        </div>
        {submit.error && <ErrorView error={submit.error} />}
        <div><button className="btn primary" disabled={vid === null || submit.isPending}>Assess →</button></div>
      </form>
    </Panel>
  );
}

function Funnel({ job }: { job: Job }) {
  const s = job.stats as Record<string, number | null>;
  const data = useMemo(() => [
    { stage: "All pairs", n: s.pairs_total ?? 0 },
    { stage: "Radial-band overlap", n: s.pairs_radial_band_overlap ?? null },
    { stage: "Flagged (proximity bound)", n: s.pairs_flagged ?? 0 },
    { stage: "Encounters ≤ threshold", n: s.encounters ?? 0 },
  ].filter((d) => d.n !== null), [s]);
  return (
    <>
      <div className="chart-box" style={{ height: 220 }}>
        <ResponsiveContainer>
          <BarChart data={data} layout="vertical" margin={{ left: 40, right: 24, top: 8, bottom: 8 }}>
            <CartesianGrid stroke="var(--hair)" horizontal={false} />
            <XAxis type="number" scale="log" domain={[0.8, "auto"]} allowDataOverflow stroke="var(--muted)" fontSize={11} tickFormatter={(v: number) => String(Math.round(v))} />
            <YAxis type="category" dataKey="stage" width={170} stroke="var(--muted)" fontSize={12} />
            <Tooltip contentStyle={{ background: "var(--s1)", border: "1px solid var(--hair)" }} formatter={(v) => [`${v} pairs`, "count"]} />
            <Bar dataKey="n" fill="var(--acc)" isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ChartMeta units="object pairs (log scale)" source={`job #${job.id} statistics`} kind="computed" />
          <Explain>The funnel shows how millions of possible pairs are narrowed down: pairs whose altitudes never overlap are dropped, then pairs that never get near each other, leaving the real close passes at the bottom.</Explain>
    </>
  );
}

export default function Screening() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const jobs = useJobs(pid);
  const [sel, setSel] = useState<number | null>(null);
  const job = jobs.data?.items.find((j) => j.id === sel) ?? jobs.data?.items[0];
  const act = useMutation({
    mutationFn: ({ id, a }: { id: number; a: "cancel" | "rerun" }) => api.post(`/projects/${pid}/jobs/${id}/${a}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs", pid] }),
  });
  return (
    <div className="page">
      <PageHead eyebrow="Run a search" title="Search for close approaches">
        Pick the data, a time window and a distance. ASTRAL predicts every object's path and lists every pair that comes closer than that distance, then pins down the exact moment of closest approach.
      </PageHead>
      <div className="grid cols-2">
        <ScreeningForm pid={pid} />
        <CdmForm pid={pid} />
      </div>
      <div className="grid cols-2">
        <Panel title="Searches" meta={jobs.data ? `${jobs.data.total} total` : undefined}>
          {jobs.data?.items.length === 0 && <Empty>No jobs yet.</Empty>}
          {jobs.error && <ErrorView error={jobs.error} />}
          <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
            <table className="data">
              <thead><tr><th>Job</th><th>Kind</th><th>Status</th><th>Progress</th><th>Created</th></tr></thead>
              <tbody>
                {jobs.data?.items.map((j) => (
                  <tr key={j.id} className={`clickable ${j.id === job?.id ? "selected" : ""}`} onClick={() => setSel(j.id)}>
                    <td className="mono">#{j.id}{j.rerun_of ? ` ↺${j.rerun_of}` : ""}</td>
                    <td>{j.kind.replace("_", " ")}</td>
                    <td><JobStatus status={j.status} /></td>
                    <td style={{ minWidth: 140 }}>
                      <div className="progress" aria-label={`progress ${Math.round(j.progress * 100)}%`}><div style={{ width: `${j.progress * 100}%` }} /></div>
                      <span className="muted" style={{ fontSize: 11 }}>{j.progress_message}</span>
                    </td>
                    <td className="muted">{utc(j.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
        {job && (
          <Panel title={`Job #${job.id}`} meta={job.kind.replace("_", " ")} actions={<>
            {(job.status === "queued" || job.status === "running") && <button className="btn small" onClick={() => act.mutate({ id: job.id, a: "cancel" })}>Cancel</button>}
            {job.status !== "queued" && job.status !== "running" && <button className="btn small" onClick={() => act.mutate({ id: job.id, a: "rerun" })}>Rerun same inputs</button>}
            {job.status === "succeeded" && <Link className="btn small primary" to={`/p/${pid}/encounters?job=${job.id}`}>Encounters →</Link>}
          </>}>
            <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {job.status === "failed" && <div className="notice error"><strong>{job.error_category}</strong> — {job.error_message}</div>}
              {job.cancel_requested && job.status === "running" && <div className="notice">Cancellation requested; the job stops at the next safe point.</div>}
              <Kv items={[
                ["Configuration", JSON.stringify(job.config)],
                ["Config SHA-256", job.config_sha256],
                ["Dataset version", `#${job.dataset_version_id}`],
                ["Started / finished", `${utc(job.started_at)} → ${utc(job.finished_at)}`],
                ["Runtime", job.stats?.runtime_s ? `${Number(job.stats.runtime_s).toFixed(2)} s` : "—"],
                ["Propagation evaluations", String(job.stats?.propagation_evaluations ?? "—")],
                ["Search radius", job.stats?.search_radius_km ? `${Number(job.stats.search_radius_km).toFixed(1)} km` : "—"],
                ["Frame", String(job.stats?.frame ?? "—")],
                ["Software", JSON.stringify({ astral: job.software.astral, sgp4: job.software.sgp4, astropy: job.software.astropy })],
              ]} />
              {job.kind === "screening" && job.status === "succeeded" && <Funnel job={job} />}
              {job.warnings.length > 0 && (
                <details>
                  <summary>{job.warnings.length} warnings</summary>
                  <ul style={{ fontSize: 12 }}>{job.warnings.slice(0, 100).map((w, i) => <li key={i}>{w}</li>)}</ul>
                </details>
              )}
              {act.error && <ErrorView error={act.error} />}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}
