import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { CatalogueRow, Paged } from "../api/types";
import { useProjectId } from "../components/Layout";
import VersionPicker from "../components/VersionPicker";
import { Empty, ErrorView, Loading, PageHead, Panel } from "../components/ui";
import { useDatasets, versionsOf } from "../lib/hooks";
import { utc } from "../lib/format";

const PAGE = 50;

export default function Catalogue() {
  const pid = useProjectId();
  const ds = useDatasets(pid);
  const [vid, setVid] = useState<number | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("object_id");
  const [page, setPage] = useState(0);
  useEffect(() => { if (vid === null && ds.data) setVid(versionsOf(ds.data.items)[0]?.v.id ?? null); }, [ds.data, vid]);
  const cat = useQuery({
    queryKey: ["catalogue", pid, vid, q, sort, page],
    enabled: vid !== null,
    queryFn: () => api.get<Paged<CatalogueRow>>(`/projects/${pid}/catalogue${qs({ vid, q, sort, limit: PAGE, offset: page * PAGE })}`),
  });
  const th = (key: string, label: string, num = false) => (
    <th className={num ? "num" : undefined} aria-sort={sort === key ? "ascending" : "none"}>
      <button onClick={() => { setSort(key); setPage(0); }}>{label}{sort === key ? " ↑" : ""}</button>
    </th>
  );
  return (
    <div className="page">
      <PageHead eyebrow="Tracked objects" title="Everything we track">
        Every satellite and debris object in the chosen data: its lowest and highest altitude, tilt, time per orbit, and how old its data is.
      </PageHead>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <VersionPicker datasets={ds.data?.items} value={vid} onChange={(v) => { setVid(v); setPage(0); }} />
        <label className="field">Search id or name<input value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} placeholder="e.g. 25544" /></label>
      </div>
      <Panel title="Objects" meta={cat.data ? `${cat.data.total} records` : undefined}>
        {cat.isLoading && <Loading />}
        {cat.error && <ErrorView error={cat.error} />}
        {cat.data?.total === 0 && <Empty>No records match.</Empty>}
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                {th("object_id", "Object")}<th>Name</th><th>Kind</th><th>Format</th>{th("epoch", "Epoch (UTC)")}<th>Frame</th>
                {th("perigee", "Perigee alt", true)}<th className="num">Apogee alt</th>{th("inclination", "Incl.", true)}<th className="num">Period</th><th>Covariance</th><th>Usable</th>
              </tr>
            </thead>
            <tbody>
              {cat.data?.items.map((r) => (
                <tr key={`${r.object_id}-${r.source_ref}`}>
                  <td className="mono">{r.object_id}</td>
                  <td>{r.object_name ?? "—"}</td>
                  <td>{r.kind.replace("_", " ")}</td>
                  <td className="mono">{r.format}</td>
                  <td className="mono">{utc(r.epoch)}</td>
                  <td className="mono">{r.frame}</td>
                  <td className="num">{r.perigee_alt_km?.toFixed(1) ?? "—"} km</td>
                  <td className="num">{r.apogee_alt_km?.toFixed(1) ?? "—"} km</td>
                  <td className="num">{r.inclination_deg?.toFixed(3) ?? "—"}°</td>
                  <td className="num">{r.period_min?.toFixed(2) ?? "—"} min</td>
                  <td>{r.has_covariance ? <span className="badge ok">present</span> : <span className="badge">none</span>}</td>
                  <td>{r.usable ? "yes" : <span className="badge warn" title="Duplicate or conflicting record; excluded from propagation">excluded</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {cat.data && cat.data.total > PAGE && (
          <div className="panel-body" style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button className="btn small" disabled={page === 0} onClick={() => setPage(page - 1)}>← Previous</button>
            <span className="muted mono">{page * PAGE + 1}–{Math.min((page + 1) * PAGE, cat.data.total)} of {cat.data.total}</span>
            <button className="btn small" disabled={(page + 1) * PAGE >= cat.data.total} onClick={() => setPage(page + 1)}>Next →</button>
          </div>
        )}
      </Panel>
    </div>
  );
}
