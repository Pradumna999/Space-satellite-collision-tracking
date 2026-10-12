import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, downloadCsv } from "../api/client";
import type { ManeuverOption, ManeuverOptions, Scenario } from "../api/types";
import { useProjectId } from "../components/Layout";
import { ChartMeta, Empty, ErrorView, Explain, Loading, PageHead, Panel, Seg } from "../components/ui";
import { useEncounters, useJobs } from "../lib/hooks";
import { km, utc } from "../lib/format";

const COLORS: Record<string, string> = { speed_up: "var(--acc)", slow_down: "var(--accT)", raise: "var(--ok)", lower: "var(--warn)", sideways: "var(--muted)" };
const SHORT: Record<string, string> = { speed_up: "Speed up", slow_down: "Slow down", raise: "Push outward", lower: "Push inward", sideways: "Sideways" };

function leadText(o: { lead_orbits: number; lead_minutes: number }) {
  const orbits = o.lead_orbits === 0.5 ? "half an orbit" : o.lead_orbits === 1 ? "1 orbit" : `${o.lead_orbits} orbits`;
  const t = o.lead_minutes >= 90 ? `${(o.lead_minutes / 60).toFixed(1)} h` : `${Math.round(o.lead_minutes)} min`;
  return `${orbits} (${t}) before`;
}

function useRunScenario(pid: number, eid: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<Scenario>(`/projects/${pid}/encounters/${eid}/scenarios`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scen", pid, eid] }),
  });
}

function OptionsSection({ pid, eid }: { pid: number; eid: number }) {
  const opts = useQuery({ queryKey: ["mopts", pid, eid], queryFn: () => api.get<ManeuverOptions>(`/projects/${pid}/encounters/${eid}/maneuver-options`), staleTime: Infinity });
  const [leadPick, setLead] = useState<string | null>(null);
  const run = useRunScenario(pid, eid);
  const [checking, setChecking] = useState<string | null>(null);
  const o = opts.data;
  const feasible = o?.leads.filter((l) => !l.too_late) ?? [];
  // default: the earliest burn that is still in the future (earlier burns achieve more)
  const lead = leadPick ?? String(feasible.length ? Math.max(...feasible.map((l) => l.lead_orbits)) : (o?.leads[0]?.lead_orbits ?? 1));
  const chart = useMemo(() => {
    if (!o) return [];
    const L = Number(lead);
    const mags = [...new Set(o.options.map((x) => x.dv_m_s))].sort((a, b) => a - b);
    return [{ dv: 0, ...Object.fromEntries(Object.keys(SHORT).map((d) => [d, o.baseline_miss_km])) },
      ...mags.map((m) => ({ dv: m, ...Object.fromEntries(o.options.filter((x) => x.lead_orbits === L && x.dv_m_s === m).map((x) => [x.direction, x.miss_km])) }))];
  }, [o, lead]);
  const best = useMemo(() => (o ? [...o.options].filter((x) => x.change_km > 0 && !x.too_late).sort((a, b) => b.km_per_m_s - a.km_per_m_s || b.change_km - a.change_km).slice(0, 3) : []), [o]);
  const check = (x: ManeuverOption) => {
    setChecking(`${x.direction}-${x.lead_orbits}-${x.dv_m_s}`);
    run.mutate({
      name: `${SHORT[x.direction]} ${x.dv_m_s} m/s, ${leadText(x)}`, burn_minutes_before_tca: Math.round(x.lead_minutes * 100) / 100,
      dv_r_m_s: x.dv_rtn_m_s[0], dv_t_m_s: x.dv_rtn_m_s[1], dv_n_m_s: x.dv_rtn_m_s[2], screen_other_objects: true,
    });
  };

  if (opts.isLoading) return <Panel title="Predicted effect of possible manoeuvres"><Loading what="Simulating 60 possible manoeuvres" /></Panel>;
  if (opts.error) return <ErrorView error={opts.error} />;
  if (!o) return null;
  return (
    <>
      {/DEB|R\/B|ROCKET/i.test(o.primary) && (
        <div className="notice">{o.primary} is debris or a rocket body and cannot manoeuvre. The options show what a working satellite in the same position could do —
          in practice it is the operator of an active satellite who would move.</div>
      )}
      <div className="grid cols-3">
        <div className="card"><span className="label">If nothing is done</span><span className="big-number">{km(o.baseline_miss_km, 2)}</span>
          <span className="muted">closest distance between {o.primary} and {o.secondary} at {utc(o.baseline_tca_utc)}</span></div>
        <div className="card"><span className="label">One orbit takes</span><span className="big-number">{Math.round(o.orbital_period_min)} min</span>
          <span className="muted">so burns are tried ½, 1 and 2 orbits before the close approach</span></div>
        <div className="card"><span className="label">Options simulated</span><span className="big-number">{o.options.length}</span>
          <span className="muted">5 directions × 4 sizes (0.05–0.5 m/s) × 3 timings</span></div>
      </div>

      <Panel title="Predicted effect of possible manoeuvres" meta="simulation only — not a recommendation"
        actions={<button className="btn small" onClick={() => downloadCsv(`manoeuvre-options-${eid}.csv`, ["timing_orbits", "burn_utc", "direction", "speed_change_m_s", "predicted_distance_km", "change_km"],
          o.options.map((x) => [x.lead_orbits, x.burn_utc, x.direction_text, x.dv_m_s, x.miss_km, x.change_km]))}>CSV</button>}>
        <div className="panel-body" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <span className="label">When to fire</span>
          <Seg label="Burn timing" value={lead} onChange={setLead} options={o.leads.map((l) => ({ value: String(l.lead_orbits), label: l.too_late ? `${leadText(l)} — too late` : leadText(l), disabled: l.too_late,
            title: l.too_late ? "This burn time has already passed" : undefined }))} />
        </div>
        <div className="chart-box" style={{ height: 320 }}>
          <ResponsiveContainer>
            <LineChart data={chart} margin={{ left: 8, right: 28, top: 12, bottom: 24 }}>
              <CartesianGrid stroke="var(--hair)" />
              <XAxis dataKey="dv" type="number" domain={[0, "dataMax"]} stroke="var(--muted)" fontSize={11}
                label={{ value: "size of speed change (metres per second)", position: "insideBottom", offset: -10, fill: "var(--muted)", fontSize: 11 }} />
              <YAxis stroke="var(--muted)" fontSize={11} label={{ value: "closest distance (km)", angle: -90, position: "insideLeft", fill: "var(--muted)", fontSize: 11 }} />
              <Tooltip contentStyle={{ background: "var(--s1)", border: "1px solid var(--hair)", fontSize: 12 }}
                formatter={(v, name) => [`${Number(v).toFixed(2)} km`, SHORT[String(name)] ?? name]} labelFormatter={(l) => `speed change ${l} m/s`} />
              <Legend formatter={(v) => SHORT[String(v)] ?? v} wrapperStyle={{ fontSize: 12 }} />
              <ReferenceLine y={o.baseline_miss_km} stroke="var(--alert)" strokeDasharray="5 4" label={{ value: "no manoeuvre", fill: "var(--alert)", fontSize: 11, position: "insideTopRight" }} />
              {Object.keys(SHORT).map((d) => <Line key={d} dataKey={d} stroke={COLORS[d]} strokeWidth={2} dot isAnimationActive={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
        <ChartMeta units="km vs m/s" source="screening trajectories + simulated burn effect" kind="predicted" />
        <Explain>
          Each line is one direction of push. Moving right means a bigger push (more fuel); moving up means the two objects end up further apart.
          The red dashed line is what happens if nothing is done. Lines that climb steeply give the most extra distance for the least fuel.
          Typically, speeding up or slowing down along the direction of travel works best, and its effect grows the earlier the burn happens.
        </Explain>
      </Panel>

      <Panel title="Most efficient options" meta="most extra distance per m/s of speed change">
        <div className="grid cols-3" style={{ padding: "calc(var(--d)*16px) 20px" }}>
          {best.map((x) => {
            const key = `${x.direction}-${x.lead_orbits}-${x.dv_m_s}`;
            return (
              <div key={key} className="card">
                <span className="label" style={{ color: "var(--accT)" }}>{SHORT[x.direction]} · {x.dv_m_s} m/s</span>
                <span style={{ fontSize: 15 }}>Fire {leadText(x)} the close approach.</span>
                <span>Distance grows from <strong>{km(o.baseline_miss_km, 2)}</strong> to <strong>{km(x.miss_km, 2)}</strong> (+{x.change_km.toFixed(2)} km).</span>
                <span className="muted" style={{ fontSize: 12 }}>{x.direction_text} · burn at {utc(x.burn_utc)}</span>
                <button className="btn small" disabled={run.isPending} onClick={() => check(x)} style={{ alignSelf: "flex-start" }}>
                  {run.isPending && checking === key ? "Checking all objects…" : "Check against all other objects"}
                </button>
              </div>
            );
          })}
          {best.length === 0 && <Empty>{feasible.length === 0 ? "This close approach is too soon: every simulated burn time has already passed." : "None of the simulated manoeuvres increases the distance."}</Empty>}
        </div>
        {run.error && <div className="panel-body"><ErrorView error={run.error} /></div>}
        <Explain>
          These are ranked by efficiency, not chosen for you. Before anything like this could be considered for real, the new path must be checked against every other object
          (the button does that and saves the result below) and reviewed by flight-dynamics experts with better data, including uncertainty.
        </Explain>
      </Panel>
    </>
  );
}

function CustomForm({ pid, eid }: { pid: number; eid: number }) {
  const [f, setF] = useState({ name: "Custom manoeuvre", burn_minutes_before_tca: 90, dv_r_m_s: 0, dv_t_m_s: 0.1, dv_n_m_s: 0, spacecraft_mass_kg: "", isp_s: "" });
  const run = useRunScenario(pid, eid);
  const num = (k: keyof typeof f, label: string, step = 0.01, hint?: string) => (
    <label className="field">{label}<input className="mono" type="number" step={step} value={String(f[k])} onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? "" : Number(e.target.value) })} />{hint && <span className="hint">{hint}</span>}</label>
  );
  return (
    <details className="panel">
      <summary className="panel-head" style={{ cursor: "pointer" }}><h3>Try your own manoeuvre</h3><span className="muted" style={{ fontSize: 13 }}>for experts</span></summary>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label className="field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} maxLength={200} /></label>
        <div className="grid cols-3">
          {num("burn_minutes_before_tca", "Fire how many minutes before?", 1)}
          {num("dv_t_m_s", "Speed up (+) / slow down (−), m/s")}
          {num("dv_r_m_s", "Push outward (+) / inward (−), m/s")}
          {num("dv_n_m_s", "Push sideways, m/s")}
          {num("spacecraft_mass_kg", "Spacecraft mass (kg)", 1, "optional — to estimate fuel")}
          {num("isp_s", "Engine efficiency, Isp (s)", 1, "optional — to estimate fuel")}
        </div>
        <div><button className="btn primary" disabled={run.isPending} onClick={() => run.mutate({ ...f, screen_other_objects: true,
          spacecraft_mass_kg: f.spacecraft_mass_kg ? Number(f.spacecraft_mass_kg) : null, isp_s: f.isp_s ? Number(f.isp_s) : null })}>
          {run.isPending ? "Simulating…" : "Simulate and save"}</button></div>
        {run.error && <ErrorView error={run.error} />}
      </div>
    </details>
  );
}

function Saved({ s, pid, eid }: { s: Scenario; pid: number; eid: number }) {
  const qc = useQueryClient();
  const del = useMutation({ mutationFn: () => api.del(`/projects/${pid}/scenarios/${s.id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["scen", pid, eid] }) });
  const r = s.result;
  const others = r.other_encounters.length;
  const checked = r.others_checked ?? 0;
  return (
    <Panel title={s.name} meta={utc(s.created_at)} actions={<button className="btn small ghost" onClick={() => del.mutate()}>Delete</button>}>
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <div className="stats">
          <div className="stat"><span className="label">Without manoeuvre</span><span className="v">{km(r.baseline.miss_km, 2)}</span></div>
          <div className="stat"><span className="label">With manoeuvre</span><span className="v">{km(r.alternative.miss_km, 2)}</span></div>
          <div className="stat"><span className="label">Change</span><span className="v">{r.miss_change_km === null ? "—" : `${r.miss_change_km >= 0 ? "+" : ""}${r.miss_change_km.toFixed(2)} km`}</span></div>
          <div className="stat"><span className="label">Speed change</span><span className="v">{r.dv_magnitude_m_s.toFixed(2)} m/s</span>
            <span className="muted" style={{ fontSize: 11 }}>{r.propellant_kg === null ? "fuel not estimated" : `≈ ${r.propellant_kg.toFixed(3)} kg fuel`}</span></div>
          <div className="stat"><span className="label">New close approaches caused</span><span className="v">{checked ? others : "not checked"}</span>
            {checked > 0 && <span className="muted" style={{ fontSize: 11 }}>against {checked.toLocaleString()} other objects</span>}</div>
        </div>
        {others > 0 && <ul style={{ fontSize: 13, margin: 0 }}>{r.other_encounters.map((o, i) => <li key={i} className="mono">{o.primary} × {o.secondary} · {utc(o.tca_utc)} · {km(o.geometry.miss_km)}</li>)}</ul>}
        <Explain title="Read this as">
          {r.miss_change_km !== null && r.miss_change_km > 0 ? `The simulated burn widens this pass by ${r.miss_change_km.toFixed(2)} km` : "The simulated burn does not widen this pass"}
          {!checked ? "; other objects were not checked." : others === 0 ? ` and creates no new close approach with any of the ${checked.toLocaleString()} other objects.` : ` but creates ${others} new close approach${others > 1 ? "es" : ""} with other objects.`}
          {" "}This is a simulation for discussion, not an instruction to fly.
        </Explain>
        <details><summary className="muted" style={{ fontSize: 12 }}>Technical notes</summary>
          <ul style={{ fontSize: 12, margin: 0, paddingLeft: 18 }}>{[r.model, ...r.warnings].map((w) => <li key={w}>{w}</li>)}</ul>
        </details>
      </div>
    </Panel>
  );
}

export default function Scenarios() {
  const pid = useProjectId();
  const [params, setParams] = useSearchParams();
  const jobs = useJobs(pid);
  const lastSearch = jobs.data?.items.find((j) => j.status === "succeeded" && j.kind === "screening");
  const encs = useEncounters(pid, { sort: "miss", limit: 200, job_id: lastSearch?.id ?? -1 });
  const usable = encs.data?.items.filter((e) => e.refinement_status !== "SUPPLIED_TCA") ?? [];
  const eid = Number(params.get("encounter")) || usable[0]?.id;
  const scen = useQuery({ queryKey: ["scen", pid, eid], enabled: !!eid, queryFn: () => api.get<{ items: Scenario[] }>(`/projects/${pid}/encounters/${eid}/scenarios`) });
  return (
    <div className="page">
      <PageHead eyebrow="Avoidance manoeuvres" title="What if we move the satellite?">
        Pick a close approach. ASTRAL simulates 60 small pushes — different directions, sizes and timings — and predicts how far apart the two objects would then pass.
        Results are simulations to support a discussion; they never command a spacecraft.
      </PageHead>
      <label className="field" style={{ maxWidth: 640 }}>Close approach
        <select value={eid ?? ""} onChange={(e) => setParams({ encounter: e.target.value })}>
          {usable.map((e) => (
            <option key={e.id} value={e.id}>{e.primary_name ?? e.primary_id} × {e.secondary_name ?? e.secondary_id} · {km(e.miss_km, 2)} · {utc(e.tca_utc)}</option>
          ))}
        </select>
      </label>
      {!eid && <Empty>No close approaches from a search yet. (Approaches imported from conjunction messages have no trajectory to manoeuvre.)</Empty>}
      {eid && <OptionsSection pid={pid} eid={eid} />}
      {eid && <CustomForm pid={pid} eid={eid} />}
      {eid && <h2 style={{ marginTop: 8 }}>Saved simulations</h2>}
      {scen.isLoading && <Loading />}
      {scen.data?.items.length === 0 && <Empty>None yet. Use “Check against all other objects” on an option above.</Empty>}
      {scen.data?.items.slice().reverse().map((s) => <Saved key={s.id} s={s} pid={pid} eid={eid!} />)}
      {eid && <span className="muted" style={{ fontSize: 12 }}><Link to={`/p/${pid}/encounters/${eid}`}>Open the full close-approach details</Link></span>}
    </div>
  );
}
