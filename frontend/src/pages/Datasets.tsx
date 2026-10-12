import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, download, qs } from "../api/client";
import type { DatasetVersion, DatasetVersionDetail, Finding, Paged } from "../api/types";
import { useProjectId } from "../components/Layout";
import { Empty, ErrorView, Kv, Loading, PageHead, Panel, Seg } from "../components/ui";
import { useDatasets, versionsOf } from "../lib/hooks";
import { utc } from "../lib/format";

const FORMATS = ["", "TLE", "OMM_KVN", "OMM_XML", "OMM_JSON", "OMM_CSV", "OEM_KVN", "CDM_KVN", "STATES_CSV", "STATES_JSON"];

function Upload({ pid, onDone }: { pid: number; onDone: (v: DatasetVersion) => void }) {
  const [over, setOver] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [fmt, setFmt] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const up = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("file", file!);
      if (name) fd.append("name", name);
      if (fmt) fd.append("fmt", fmt);
      return api.post<DatasetVersion>(`/projects/${pid}/datasets`, fd);
    },
    onSuccess: (v) => { setFile(null); setName(""); onDone(v); },
  });
  return (
    <Panel title="Upload orbital data" meta="TLE · OMM (KVN/XML/JSON/CSV) · OEM · CDM · astral-states CSV/JSON">
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div
          className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0} aria-label="Choose a file to upload"
          onClick={() => input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
          onDrop={(e) => { e.preventDefault(); setOver(false); setFile(e.dataTransfer.files[0] ?? null); }}
        >
          {file ? <span className="mono">{file.name} · {(file.size / 1024).toFixed(1)} KiB</span> : <span>Drop a file here or click to choose</span>}
          <input ref={input} type="file" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <label className="field" style={{ flex: 1, minWidth: 200 }}>Dataset name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="defaults to file name" /></label>
          <label className="field">Format<select value={fmt} onChange={(e) => setFmt(e.target.value)}>{FORMATS.map((f) => <option key={f} value={f}>{f || "Detect automatically"}</option>)}</select></label>
          <button className="btn primary" disabled={!file || up.isPending} onClick={() => up.mutate()}>{up.isPending ? "Validating…" : "Upload & validate →"}</button>
        </div>
        {up.error && <ErrorView error={up.error} />}
        <span className="muted" style={{ fontSize: 12 }}>The original file is stored unchanged with its SHA-256. Records are never silently repaired; corrections appear below as proposals that need explicit approval.</span>
      </div>
    </Panel>
  );
}

function Provider({ pid, onDone }: { pid: number; onDone: (v: DatasetVersion) => void }) {
  const [group, setGroup] = useState("stations");
  const f = useMutation({ mutationFn: () => api.post<DatasetVersion>(`/projects/${pid}/provider-fetch`, { provider: "celestrak", group }), onSuccess: onDone });
  return (
    <Panel title="Fetch from CelesTrak" meta="public GP data · optional · cached">
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="field">GP group<input value={group} onChange={(e) => setGroup(e.target.value)} className="mono" /></label>
          <button className="btn" onClick={() => f.mutate()} disabled={f.isPending}>{f.isPending ? "Fetching…" : "Fetch & validate"}</button>
        </div>
        {f.error && <ErrorView error={f.error} />}
        <span className="muted" style={{ fontSize: 12 }}>Downloaded data is recorded with fetch time, query and HTTP status. It is public data, not an operationally authoritative source. Works offline-first: analysis never requires this.</span>
      </div>
    </Panel>
  );
}

function VersionDetail({ pid, vid }: { pid: number; vid: number }) {
  const qc = useQueryClient();
  const [sev, setSev] = useState<"" | "error" | "warning" | "info">("");
  const d = useQuery({ queryKey: ["dv", pid, vid], queryFn: () => api.get<DatasetVersionDetail>(`/projects/${pid}/dataset-versions/${vid}`) });
  const f = useQuery({ queryKey: ["findings", pid, vid, sev], queryFn: () => api.get<Paged<Finding>>(`/projects/${pid}/dataset-versions/${vid}/findings${qs({ severity: sev, limit: 200 })}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["datasets", pid] }); qc.invalidateQueries({ queryKey: ["dv", pid] }); };
  const approve = useMutation({ mutationFn: () => api.post(`/projects/${pid}/dataset-versions/${vid}/approve`), onSuccess: refresh });
  const tr = useMutation({ mutationFn: ({ id, act }: { id: number; act: "approve" | "reject" }) => api.post(`/projects/${pid}/transformations/${id}/${act}`), onSuccess: refresh });
  if (d.isLoading) return <Loading />;
  if (d.error) return <ErrorView error={d.error} />;
  const v = d.data!;
  return (
    <Panel title={`${v.dataset.name} · v${v.version}`} meta={v.format} actions={<>
      <button className="btn small" onClick={() => download(`/projects/${pid}/dataset-versions/${vid}/validation-report.csv`, "validation.csv")}>Validation report CSV</button>
      <button className="btn small" onClick={() => download(`/projects/${pid}/dataset-versions/${vid}/raw`, "original.txt")}>Original file</button>
    </>}>
      <div className="panel-body grid cols-2">
        <Kv items={[
          ["Status", v.status.replace("_", " ")],
          ["File", `${v.file.name} (${v.file.size_bytes} B, ${v.file.origin})`],
          ["File SHA-256", v.file.sha256],
          ["Snapshot SHA-256", v.snapshot_sha256],
          ["Validated at", utc(v.reference_time)],
          ["Records / objects", `${v.stats.records} / ${v.stats.objects}`],
          ["With covariance", String(v.stats.with_covariance)],
          ["Findings", Object.entries(v.finding_counts).map(([k, n]) => `${n} ${k}`).join(" · ") || "none"],
        ]} />
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {v.status === "needs_review" && (
            <div className="notice">
              This version has validation errors. Records with errors are excluded from analysis. Approve to proceed with the remaining records.
              <div style={{ marginTop: 8 }}><button className="btn small primary" onClick={() => approve.mutate()} disabled={approve.isPending}>Approve for analysis</button></div>
            </div>
          )}
          {v.transformations.length > 0 && (
            <div className="card">
              <span className="label">Proposed corrections (require approval; create a new version)</span>
              {v.transformations.map((t) => (
                <div key={t.id} style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", fontSize: 13 }}>
                  <span style={{ flex: 1 }}>{t.description}</span>
                  {t.status === "proposed" ? (<>
                    <button className="btn small" onClick={() => tr.mutate({ id: t.id, act: "approve" })}>Approve</button>
                    <button className="btn small ghost" onClick={() => tr.mutate({ id: t.id, act: "reject" })}>Reject</button>
                  </>) : <span className="badge">{t.status}{t.result_version_id ? ` → version id ${t.result_version_id}` : ""}</span>}
                </div>
              ))}
              {tr.error && <ErrorView error={tr.error} />}
            </div>
          )}
        </div>
      </div>
      <div className="panel-head" style={{ borderTop: "1px solid var(--hair)" }}>
        <h3>Validation findings</h3>
        <Seg label="Severity filter" value={sev} onChange={setSev} options={[{ value: "", label: "All" }, { value: "error", label: "Errors" }, { value: "warning", label: "Warnings" }, { value: "info", label: "Info" }]} />
      </div>
      {f.data?.total === 0 && <Empty>No findings.</Empty>}
      <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
        <table className="data">
          <thead><tr><th>Severity</th><th>Code</th><th>Record</th><th>Message</th><th>Suggestion</th></tr></thead>
          <tbody>
            {f.data?.items.map((x) => (
              <tr key={x.id}>
                <td><span className={`badge ${x.severity === "error" ? "alert" : x.severity === "warning" ? "warn" : ""}`}>{x.severity}</span></td>
                <td className="mono">{x.code}</td>
                <td className="mono muted">{x.record ?? "—"}</td>
                <td>{x.message}</td>
                <td className="muted">{x.suggestion ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function Datasets() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const ds = useDatasets(pid);
  const [sel, setSel] = useState<number | null>(null);
  const done = (v: DatasetVersion) => { qc.invalidateQueries({ queryKey: ["datasets", pid] }); setSel(v.id); };
  const versions = versionsOf(ds.data?.items);
  const current = sel ?? versions[0]?.v.id ?? null;
  return (
    <div className="page">
      <PageHead eyebrow="Data sources" title="Where the orbit data comes from">Load public data or upload your own; every file is checked before use. Every analysis references one immutable dataset version.</PageHead>
      <div className="grid cols-2">
        <Upload pid={pid} onDone={done} />
        <Provider pid={pid} onDone={done} />
      </div>
      <Panel title="Versions">
        {ds.isLoading && <Loading />}
        {versions.length === 0 && !ds.isLoading && <Empty>No datasets yet.</Empty>}
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Dataset</th><th>Version</th><th>Format</th><th>Status</th><th className="num">Records</th><th className="num">Errors</th><th className="num">Warnings</th><th>Origin</th><th>Created</th></tr></thead>
            <tbody>
              {versions.map(({ ds: d, v }) => (
                <tr key={v.id} className={`clickable ${v.id === current ? "selected" : ""}`} onClick={() => setSel(v.id)} aria-selected={v.id === current}>
                  <td>{d.name}</td>
                  <td className="mono">v{v.version}</td>
                  <td className="mono">{v.format}</td>
                  <td><span className={`badge ${v.status === "needs_review" ? "warn" : "ok"}`}>{v.status.replace("_", " ")}</span></td>
                  <td className="num">{v.stats.records}</td>
                  <td className="num">{v.stats.errors}</td>
                  <td className="num">{v.stats.warnings}</td>
                  <td className="muted">{String(v.provenance.origin ?? "")}</td>
                  <td className="muted">{utc(v.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {current !== null && <VersionDetail pid={pid} vid={current} />}
    </div>
  );
}
