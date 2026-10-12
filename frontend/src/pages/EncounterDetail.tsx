import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, download, downloadCsv, qs } from "../api/client";
import type { EncounterDetail as Detail, RelativeMotion } from "../api/types";
import EncounterPlane from "../components/EncounterPlane";
import { useProjectId } from "../components/Layout";
import RelativeScene from "../scene/RelativeScene";
import { ChartMeta, ErrorView, Explain, Kv, Loading, PageHead, Panel, PcBadge, Seg } from "../components/ui";
import { ageLabel, km, kms, sci, untilTca, utc } from "../lib/format";

export default function EncounterDetail() {
  const pid = useProjectId();
  const eid = Number(useParams().eid);
  const [span, setSpan] = useState<"120" | "600" | "3600">("600");
  const d = useQuery({ queryKey: ["enc", pid, eid], queryFn: () => api.get<Detail>(`/projects/${pid}/encounters/${eid}`) });
  const rm = useQuery({
    queryKey: ["rel", pid, eid, span],
    queryFn: () => api.get<RelativeMotion>(`/projects/${pid}/encounters/${eid}/relative-motion${qs({ span_s: span, points: 241 })}`),
  });
  const [cdmErr, setCdmErr] = useState<unknown>(null);
  if (d.isLoading) return <div className="page"><Loading /></div>;
  if (d.error) return <div className="page"><ErrorView error={d.error} /></div>;
  const e = d.data!;
  const pc = e.probability[0]?.result;
  const rows = rm.data ? rm.data.t_s.map((t, i) => ({ t, range: rm.data!.range_km[i], r: rm.data!.rtn_km[i]![0], tt: rm.data!.rtn_km[i]![1], n: rm.data!.rtn_km[i]![2] })) : [];
  const kind = e.job.kind === "cdm_assessment" ? "supplied" : "propagated";
  return (
    <div className="page">
      <PageHead eyebrow={`Close approach · EVT-${String(e.id).padStart(4, "0")}`} title={`${e.primary_name ?? e.primary_id} × ${e.secondary_name ?? e.secondary_id}`} actions={<>
        <PcBadge status={e.pc_status} value={e.pc_value} />
        {e.job.kind === "screening" && <Link className="btn" to={`/p/${pid}/scenarios?encounter=${e.id}`}>Simulate manoeuvre</Link>}
        <Link className="btn" to={`/p/${pid}/environment?encounter=${e.id}`}>View in 3D</Link>
        <button className="btn" disabled={e.covariance_available !== "both"} title={e.covariance_available !== "both" ? "CCSDS CDM requires covariance for both objects" : undefined}
          onClick={() => download(`/projects/${pid}/encounters/${e.id}/export/cdm`, `encounter-${e.id}.cdm`).catch(setCdmErr)}>Export CDM</button>
      </>}>
        TCA {utc(e.tca_utc)} ({untilTca(e.tca_utc)}). Refinement: {e.refinement_status.toLowerCase().replace(/_/g, " ")}. Frame {e.frame}.
      </PageHead>
      {cdmErr !== null && <ErrorView error={cdmErr} />}
      <div className="stats">
        <div className="stat"><span className="label">Closest distance</span><span className="v">{km(e.miss_km, 4)}</span></div>
        <div className="stat"><span className="label">Speed between them</span><span className="v">{kms(e.rel_speed_km_s, 3)}</span></div>
        <div className="stat"><span className="label" title="radial / along-track / cross-track">Offset: up-down / ahead-behind / side</span><span className="v" style={{ fontSize: 15 }}>{e.geometry.rel_pos_rtn_km.map((x) => x.toFixed(3)).join(" / ")} km</span></div>
        <div className="stat"><span className="label">Crossing angle</span><span className="v">{e.geometry.approach_angle_deg.toFixed(1)}°</span></div>
        <div className="stat"><span className="label">Probability</span><span className="v" style={{ fontSize: 17 }}>{e.pc_value === null ? "not computed" : sci(e.pc_value, 3)}</span></div>
      </div>
      <div className="grid cols-2">
        <Panel title="Distance over time" meta="seen from the first object" actions={<>
          <Seg label="Time span" value={span} onChange={setSpan} options={[{ value: "120", label: "±2 min" }, { value: "600", label: "±10 min" }, { value: "3600", label: "±1 h" }]} />
          <button className="btn small" disabled={!rm.data} onClick={() => downloadCsv(`relative-motion-${e.id}.csv`, ["t_s", "range_km", "radial_km", "intrack_km", "crosstrack_km"],
            rows.map((r) => [r.t, r.range, r.r, r.tt, r.n]), [`encounter ${e.id}`, `TCA ${e.tca_utc}`, rm.data?.data_kind ?? ""])}>CSV</button>
        </>}>
          {rm.error && <div className="panel-body"><ErrorView error={rm.error} /></div>}
          <div className="chart-box">
            <ResponsiveContainer>
              <LineChart data={rows} margin={{ left: 8, right: 24, top: 12, bottom: 18 }}>
                <CartesianGrid stroke="var(--hair)" />
                <XAxis dataKey="t" type="number" domain={["dataMin", "dataMax"]} stroke="var(--muted)" fontSize={11} label={{ value: "time from TCA (s)", position: "insideBottom", offset: -8, fill: "var(--muted)", fontSize: 11 }} />
                <YAxis stroke="var(--muted)" fontSize={11} label={{ value: "km", angle: -90, position: "insideLeft", fill: "var(--muted)", fontSize: 11 }} />
                <Tooltip contentStyle={{ background: "var(--s1)", border: "1px solid var(--hair)" }} formatter={(v) => (typeof v === "number" ? v.toFixed(4) : v)} labelFormatter={(l) => `t = ${l} s`} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <ReferenceLine x={0} stroke="var(--accT)" strokeDasharray="4 3" label={{ value: "TCA", fill: "var(--accT)", fontSize: 11 }} />
                <Line dataKey="range" name="range" stroke="var(--acc)" dot={false} strokeWidth={2} isAnimationActive={false} />
                <Line dataKey="r" name="radial" stroke="var(--warn)" dot={false} isAnimationActive={false} />
                <Line dataKey="tt" name="in-track" stroke="var(--ok)" dot={false} isAnimationActive={false} />
                <Line dataKey="n" name="cross-track" stroke="var(--muted)" dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ChartMeta units="km vs seconds from TCA" time="UTC (TCA reference)" source={rm.data?.data_kind ?? "—"} kind={kind} />
          <Explain>The red line is the distance between the two objects; it dips to its minimum at the dashed line (closest approach, TCA). The other lines split that distance into up-down (radial), ahead-behind (along-track) and sideways (cross-track) parts.</Explain>
        </Panel>
        <Panel title="The pass in 3D" meta="drag to rotate">
          <div style={{ height: 300 }}>{rm.data ? <RelativeScene rtn={rm.data.rtn_km} t={rm.data.t_s} /> : <Loading />}</div>
          <ChartMeta units="km" source={rm.data?.data_kind ?? "—"} kind={kind} />
          <Explain>The first object sits at the centre. The orange curve is the path of the second object as it flies past; the yellow dot marks the closest point.</Explain>
        </Panel>
      </div>
      <div className="grid cols-2">
        <Panel title="Chance of collision" meta={pc?.method ?? "not computed"}>
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <EncounterPlane miss={e.geometry.miss_in_plane_km} cov={pc?.details.projected_cov_km2} hbrKm={pc?.details.hbr_km} />
            <Kv items={[
              ["Status", pc?.status ?? e.pc_status],
              ["Value", e.pc_value === null ? "—" : sci(e.pc_value, 4)],
              ["Algorithm", e.probability[0]?.algorithm_version ?? "—"],
              ["Hard-body radius", pc?.details.hbr_km ? `${(pc.details.hbr_km * 1000).toFixed(2)} m` : "not specified"],
              ["σ major / minor (plane)", pc?.details.sigma_major_km ? `${pc.details.sigma_major_km.toFixed(4)} / ${pc.details.sigma_minor_km?.toFixed(4)} km` : "—"],
              ["Est. encounter duration", pc?.details.encounter_duration_est_s ? `${pc.details.encounter_duration_est_s.toFixed(1)} s` : "—"],
              ["Monte Carlo cross-check", pc?.details.monte_carlo_crosscheck ? `${sci(pc.details.monte_carlo_crosscheck.value, 3)} (95% CI ${sci(pc.details.monte_carlo_crosscheck.ci95[0])}–${sci(pc.details.monte_carlo_crosscheck.ci95[1])}, n=${pc.details.monte_carlo_crosscheck.samples})` : "not run"],
              ["Originator Pc (CDM)", pc?.details.originator ? `${pc.details.originator.pc === null ? "not given" : sci(pc.details.originator.pc, 3)} — for comparison only` : "—"],
            ]} />
            {pc && pc.reasons.length > 0 && <div className="notice"><strong>Why no Pc:</strong><ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{pc.reasons.map((r) => <li key={r}>{r}</li>)}</ul></div>}
            {pc && pc.warnings.length > 0 && <div className="notice"><strong>Method warnings:</strong><ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{pc.warnings.map((r) => <li key={r}>{r}</li>)}</ul></div>}
          </div>
        </Panel>
        <Panel title="Where these numbers come from">
          <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <Kv items={[
              ["Dataset", `${e.dataset.name} v${e.dataset.version}`],
              ["Snapshot SHA-256", e.dataset.snapshot_sha256],
              ["Analysis", `job #${e.job.id} (${e.job.kind}) · config ${e.job.config_sha256.slice(0, 16)}…`],
              ...Object.entries(e.propagators).map(([k, v]) => [`Propagator · ${k}`, v] as [string, string]),
              ...Object.entries(e.data_age_days).map(([k, v]) => [`Data age at TCA · ${k}`, ageLabel(v)] as [string, string]),
              ["Covariance", e.covariance_available],
              ["Range-rate residual at TCA", `${e.geometry.range_rate_km_s.toExponential(2)} km/s`],
              ["ML priority (experimental)", e.ml_priority_experimental === null ? "no active model" : `${e.ml_priority_experimental.toFixed(3)} · ${e.ml_model} — not a probability`],
            ]} />
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>{e.flags.map((f) => <span key={f} className="badge warn" title={FLAG_HELP[f.split(":")[0]!] ?? ""}>{f.replace(/_/g, " ").toLowerCase()}</span>)}</div>
            {e.history.length > 1 && (<>
              <span className="label">Analysis history (same pair, TCA within 1 h)</span>
              <table className="data"><tbody>{e.history.map((h) => (
                <tr key={h.encounter_id}><td className="mono">job #{h.job_id}</td><td className="mono">{utc(h.tca_utc)}</td><td className="num">{km(h.miss_km, 4)}</td>
                  <td>{h.encounter_id === e.id ? "this" : <Link to={`/p/${pid}/encounters/${h.encounter_id}`}>open</Link>}</td></tr>))}</tbody></table>
            </>)}
          </div>
        </Panel>
      </div>
    </div>
  );
}

const FLAG_HELP: Record<string, string> = {
  TLE_ACCURACY_LIMITED: "Public TLE/OMM elements: kilometre-level errors; screening and research use only.",
  STALE_INPUT: "Input data older than the staleness limit at TCA.",
  WINDOW_BOUNDARY: "Minimum lies on the analysis-window edge; the true TCA may be outside the window.",
  REFINEMENT_FAILED: "Root-finding did not converge; reported time is the best bracket endpoint.",
  MISS_DIFFERS_FROM_ORIGINATOR: "ASTRAL's miss distance differs from the CDM originator's value by more than 10 m.",
};
