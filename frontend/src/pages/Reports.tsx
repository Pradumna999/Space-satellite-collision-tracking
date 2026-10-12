import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download } from "../api/client";
import type { Job, Report } from "../api/types";
import { useProjectId } from "../components/Layout";
import { Empty, ErrorView, PageHead, Panel } from "../components/ui";
import { useJobs } from "../lib/hooks";
import { km, utc } from "../lib/format";

interface CompareRow { pair: string[]; a: number | null; b: number | null; tca_shift_s?: number; miss_a_km?: number; miss_b_km?: number; miss_change_km?: number }
interface Compare { a: Job; b: Job; same_dataset_version: boolean; same_config: boolean; software_changed: boolean; rows: CompareRow[] }

export default function Reports() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const jobs = useJobs(pid);
  const done = jobs.data?.items.filter((j) => j.status === "succeeded") ?? [];
  const [jid, setJid] = useState<number | null>(null);
  const job = jid ?? done[0]?.id ?? null;
  const reports = useQuery({ queryKey: ["reports", pid], queryFn: () => api.get<{ items: Report[] }>(`/projects/${pid}/reports`) });
  const gen = useMutation({
    mutationFn: (fmt: string) => api.post<Report>(`/projects/${pid}/jobs/${job}/reports?fmt=${fmt}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports", pid] }),
  });
  const [a, setA] = useState<number | null>(null);
  const [b, setB] = useState<number | null>(null);
  const cmp = useQuery({ queryKey: ["cmp", pid, a, b], enabled: !!a && !!b && a !== b, queryFn: () => api.get<Compare>(`/projects/${pid}/jobs/${a}/compare/${b}`) });
  const [dlErr, setDlErr] = useState<unknown>(null);
  return (
    <div className="page">
      <PageHead eyebrow="Reports" title="Reports you can hand over">
        Reproducible reports: analysis id, input hashes, configuration, software and algorithm versions, results, data quality and limitations. Files are stored with their SHA-256 and verified on download.
      </PageHead>
      <div className="grid cols-2">
        <Panel title="Generate">
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <label className="field">Analysis<select value={job ?? ""} onChange={(e) => setJid(Number(e.target.value))}>
              {done.map((j) => <option key={j.id} value={j.id}>#{j.id} · {j.kind.replace("_", " ")} · {utc(j.finished_at)}</option>)}
            </select></label>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <button className="btn primary" disabled={!job || gen.isPending} onClick={() => gen.mutate("pdf")}>Export report (PDF)</button>
              <button className="btn" disabled={!job || gen.isPending} onClick={() => gen.mutate("csv")}>Encounters CSV</button>
              <button className="btn" disabled={!job || gen.isPending} onClick={() => gen.mutate("json")}>Full JSON</button>
            </div>
            {gen.error && <ErrorView error={gen.error} />}
            {done.length === 0 && <Empty>No completed analyses.</Empty>}
          </div>
        </Panel>
        <Panel title="Compare runs" meta="match encounters by object pair and TCA (±60 s)">
          <div className="panel-body" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {[["Run A", a, setA], ["Run B", b, setB]].map(([label, val, set]) => (
              <label key={label as string} className="field">{label as string}<select value={(val as number | null) ?? ""} onChange={(e) => (set as (v: number) => void)(Number(e.target.value))}>
                <option value="">Select…</option>{done.map((j) => <option key={j.id} value={j.id}>#{j.id} · {j.kind.replace("_", " ")}</option>)}
              </select></label>
            ))}
          </div>
          {cmp.data && (<>
            <div className="panel-body" style={{ display: "flex", gap: 8, flexWrap: "wrap", paddingTop: 0 }}>
              <span className={`badge ${cmp.data.same_dataset_version ? "ok" : "warn"}`}>{cmp.data.same_dataset_version ? "same inputs" : "different inputs"}</span>
              <span className={`badge ${cmp.data.same_config ? "ok" : "warn"}`}>{cmp.data.same_config ? "same configuration" : "different configuration"}</span>
              <span className={`badge ${cmp.data.software_changed ? "warn" : "ok"}`}>{cmp.data.software_changed ? "software changed" : "same software"}</span>
            </div>
            <div className="table-wrap" style={{ maxHeight: 320, overflowY: "auto" }}>
              <table className="data"><thead><tr><th>Pair</th><th className="num">Miss A</th><th className="num">Miss B</th><th className="num">Δ miss</th><th className="num">TCA shift</th></tr></thead>
                <tbody>{cmp.data.rows.map((r, i) => (
                  <tr key={i}><td className="mono">{r.pair.join(" × ")}</td><td className="num">{km(r.miss_a_km)}</td><td className="num">{km(r.miss_b_km)}</td>
                    <td className="num">{r.miss_change_km === undefined ? (r.a ? "only in A" : "only in B") : `${(r.miss_change_km * 1000).toFixed(3)} m`}</td>
                    <td className="num">{r.tca_shift_s === undefined ? "—" : `${r.tca_shift_s.toFixed(3)} s`}</td></tr>))}</tbody></table>
            </div>
          </>)}
          {cmp.error && <div className="panel-body"><ErrorView error={cmp.error} /></div>}
        </Panel>
      </div>
      <Panel title="Generated reports">
        {dlErr !== null && <div className="panel-body"><ErrorView error={dlErr} /></div>}
        {reports.data?.items.length === 0 && <Empty>No reports yet.</Empty>}
        <table className="data">
          <thead><tr><th>Report</th><th>Job</th><th>Format</th><th>SHA-256</th><th>Generator</th><th>Created</th><th></th></tr></thead>
          <tbody>{reports.data?.items.map((r) => (
            <tr key={r.id}>
              <td className="mono">#{r.id}</td><td className="mono">#{r.job_id}</td><td>{r.format.toUpperCase()}</td>
              <td className="mono muted" title={r.sha256}>{r.sha256.slice(0, 16)}…</td><td className="mono">{r.generator_version}</td><td className="muted">{utc(r.created_at)}</td>
              <td><button className="btn small" onClick={() => download(`/projects/${pid}/reports/${r.id}/download`, `report-${r.id}.${r.format}`).catch(setDlErr)}>Download</button></td>
            </tr>))}</tbody>
        </table>
      </Panel>
    </div>
  );
}
