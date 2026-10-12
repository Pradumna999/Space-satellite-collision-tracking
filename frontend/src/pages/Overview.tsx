import { Link } from "react-router-dom";
import { useProjectId } from "../components/Layout";
import { Empty, ErrorView, Loading, Panel } from "../components/ui";
import { useDatasets, useEncounters, useJobs, versionsOf } from "../lib/hooks";
import { km, kms, parseUtc } from "../lib/format";

function inWords(iso: string): string {
  const ms = parseUtc(iso) - Date.now();
  const h = Math.abs(ms) / 3600000;
  const txt = h < 1 ? `${Math.round(h * 60)} min` : `${h.toFixed(h < 10 ? 1 : 0)} h`;
  return ms >= 0 ? `in ${txt}` : `${txt} ago`;
}

function Card({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div className="card" style={{ gap: 6 }}>
      <span className="label">{label}</span>
      <span className="big-number">{value}</span>
      {sub && <span className="muted" style={{ fontSize: 13 }}>{sub}</span>}
    </div>
  );
}

/** One-screen summary for a first-time viewer. Every number is read from stored results. */
export default function Overview() {
  const pid = useProjectId();
  const ds = useDatasets(pid);
  const jobs = useJobs(pid);
  const latestVersion = versionsOf(ds.data?.items).find((x) => !x.v.format.startsWith("CDM"))?.v ?? versionsOf(ds.data?.items)[0]?.v;
  const lastSearch = jobs.data?.items.find((j) => j.status === "succeeded" && j.kind === "screening");
  // Closest passes from the latest search only (older searches may cover past windows).
  const closest = useEncounters(pid, { sort: "miss", limit: 5, job_id: lastSearch?.id ?? -1 });
  const top = closest.data?.items[0];
  if (ds.error) return <div className="page"><ErrorView error={ds.error} /></div>;
  if (ds.isLoading || jobs.isLoading) return <div className="page"><Loading /></div>;
  const updatedH = latestVersion ? (Date.now() - parseUtc(latestVersion.created_at)) / 3600000 : null;

  return (
    <div className="page">
      <header>
        <div className="eyebrow">At a glance</div>
        <h1 style={{ fontSize: 44 }}>Who is about to pass too close — and what could be done about it.</h1>
        <p className="muted" style={{ maxWidth: "70ch", fontSize: 16 }}>
          ASTRAL follows satellites and space debris, predicts their paths, finds pairs that will pass close to each other, and lets you test small avoidance manoeuvres.
        </p>
      </header>

      <div className="grid cols-4">
        <Card value={latestVersion ? latestVersion.stats.objects.toLocaleString() : "—"} label="Objects tracked" sub="satellites and debris in the latest data" />
        <Card value={lastSearch ? String(lastSearch.stats.encounters ?? 0) : "—"} label="Close approaches found"
          sub={lastSearch ? `closer than ${String(lastSearch.config.threshold_km)} km over the next ${String(lastSearch.config.duration_hours)} h` : "run a search to find them"} />
        <Card value={top ? km(top.miss_km, 2) : "—"} label="Closest predicted pass" sub={top ? `${top.primary_name ?? top.primary_id} × ${top.secondary_name ?? top.secondary_id}, ${inWords(top.tca_utc)}` : undefined} />
        <Card value={updatedH === null ? "—" : updatedH < 1 ? "< 1 h" : `${Math.round(updatedH)} h`} label="Data age" sub="since the orbital data was last loaded" />
      </div>

      <div className="grid cols-3">
        {[
          ["1 · Track", "Load public orbital data (or your own) and check it for errors.", "datasets", "Data sources"],
          ["2 · Find", "Predict every path and list every pair that comes closer than a chosen distance.", "encounters", "Close approaches"],
          ["3 · Act", "Try small speed changes and see how much each one would widen the gap.", "scenarios", "Avoidance manoeuvres"],
        ].map(([t, d, to, cta]) => (
          <div key={t} className="card">
            <h3>{t}</h3>
            <span className="muted">{d}</span>
            <Link className="btn small" to={`/p/${pid}/${to}`} style={{ alignSelf: "flex-start" }}>{cta} →</Link>
          </div>
        ))}
      </div>

      <Panel title="Closest passes" meta="smallest predicted distance first" actions={<Link className="btn small" to={`/p/${pid}/encounters`}>See all</Link>}>
        {closest.data?.items.length === 0 && <Empty>No close approaches yet. Use “Run a search”.</Empty>}
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Objects</th><th>When</th><th className="num">Closest distance</th><th className="num">Speed between them</th><th></th></tr></thead>
            <tbody>
              {closest.data?.items.map((e) => (
                <tr key={e.id}>
                  <td>{e.primary_name ?? e.primary_id} × {e.secondary_name ?? e.secondary_id}</td>
                  <td className="muted">{inWords(e.tca_utc)}</td>
                  <td className="num">{km(e.miss_km, 2)}</td>
                  <td className="num">{kms(e.rel_speed_km_s, 1)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <Link to={`/p/${pid}/encounters/${e.id}`}>Details</Link>
                    {e.refinement_status !== "SUPPLIED_TCA" && <> · <Link to={`/p/${pid}/scenarios?encounter=${e.id}`}>Avoidance options</Link></>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
