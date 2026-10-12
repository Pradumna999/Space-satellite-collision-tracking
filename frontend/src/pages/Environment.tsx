import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { EncounterDetail, TrackObject, Tracks } from "../api/types";
import { useProjectId } from "../components/Layout";
import VersionPicker from "../components/VersionPicker";
import { ErrorView, Loading, PageHead, Seg } from "../components/ui";
import EarthScene, { toScene, type SimClock, type TrackLine } from "../scene/EarthScene";
import { useDatasets, useJobs, versionsOf } from "../lib/hooks";
import { ageLabel, km, utc } from "../lib/format";

const WINDOW_MS = 3 * 3600 * 1000; // one request covers 3 hours of motion
const STEP_S = 120;
const iso = (ms: number) => new Date(ms).toISOString().slice(0, 19) + "Z";
const alignHour = (ms: number) => Math.floor(ms / 3600000) * 3600000;
const SPEEDS = [
  { value: "60", label: "60×" },
  { value: "300", label: "300×" },
  { value: "1200", label: "1200×" },
];
const LIMITS = [
  { value: "250", label: "250" },
  { value: "500", label: "500" },
  { value: "1000", label: "1000" },
];

function at(o: TrackObject, data: Tracks, ms: number): number[] | null {
  const f = (ms - Date.parse(data.start_utc)) / (data.step_s * 1000);
  if (f < 0 || f > data.samples - 1) return null;
  const k = Math.min(Math.floor(f), data.samples - 2), a = f - k;
  const out: number[] = [];
  for (let c = 0; c < 3; c++) {
    const x0 = o.r[k * 3 + c], x1 = o.r[(k + 1) * 3 + c];
    if (x0 == null || x1 == null) return null;
    out.push(x0 + (x1 - x0) * a);
  }
  return out;
}

function samplesOf(o: TrackObject): number[][] {
  const pts: number[][] = [];
  for (let i = 0; i + 2 < o.r.length; i += 3) {
    const x = o.r[i], y = o.r[i + 1], z = o.r[i + 2];
    if (x != null && y != null && z != null) pts.push([x, y, z]);
  }
  return pts;
}

export default function Environment() {
  const pid = useProjectId();
  const qc = useQueryClient();
  const [params] = useSearchParams();
  const encId = Number(params.get("encounter")) || null;
  const ds = useDatasets(pid);
  const jobs = useJobs(pid);
  const enc = useQuery({ queryKey: ["enc", pid, encId], enabled: !!encId, queryFn: () => api.get<EncounterDetail>(`/projects/${pid}/encounters/${encId}`) });

  const [vid, setVid] = useState<number | null>(null);
  const [limit, setLimit] = useState("500");
  const [speed, setSpeed] = useState("300");
  const [playing, setPlaying] = useState(false);
  const [ws, setWs] = useState(() => alignHour(Date.now()));
  const [displayMs, setDisplayMs] = useState(() => Date.now());
  const [selected, setSelected] = useState<string | null>(null);
  const [showAxes, setAxes] = useState(false);
  const [showOrbits, setOrbits] = useState(true);
  const clock = useRef<SimClock>({ t: Date.now(), playing: false, speed: 300 });

  useEffect(() => { clock.current.playing = playing; }, [playing]);
  useEffect(() => { clock.current.speed = Number(speed); }, [speed]);

  const include = enc.data && enc.data.job.kind === "screening" ? `${enc.data.primary_id},${enc.data.secondary_id}` : "";
  useEffect(() => {
    if (enc.data && jobs.data) {
      const job = jobs.data.items.find((j) => j.id === enc.data!.job.id);
      if (job && job.kind === "screening") setVid(job.dataset_version_id);
      const tca = Date.parse(enc.data.tca_utc);
      setWs(alignHour(tca - WINDOW_MS / 2));
      clock.current.t = tca;
      setDisplayMs(tca);
      setSelected(enc.data.primary_id);
    }
  }, [enc.data, jobs.data]);
  useEffect(() => {
    if (vid === null && ds.data && !encId) setVid(versionsOf(ds.data.items).find((x) => !x.v.format.startsWith("CDM") && !x.v.format.startsWith("STATES"))?.v.id ?? null);
  }, [ds.data, vid, encId]);

  const fetchWindow = useCallback((start: number) => ({
    queryKey: ["tracks", pid, vid, start, limit, include],
    queryFn: () => api.get<Tracks>(`/projects/${pid}/viz/tracks${qs({ vid, start: iso(start), duration_s: WINDOW_MS / 1000, step_s: STEP_S, limit, include })}`),
    staleTime: Infinity,
  }), [pid, vid, limit, include]);
  const tracks = useQuery({ ...fetchWindow(ws), enabled: vid !== null, placeholderData: (p) => p });
  const data = tracks.data && Date.parse(tracks.data.start_utc) === ws ? tracks.data : undefined;

  // Keep the clock inside the loaded window; prefetch and hand over to the next window.
  const end = ws + WINDOW_MS;
  useEffect(() => {
    if (clock.current.t < ws || clock.current.t > end) {
      clock.current.t = Math.min(Math.max(clock.current.t, ws), end);
      setDisplayMs(clock.current.t);
    }
  }, [ws, end]);
  useEffect(() => {
    if (vid === null) return;
    if (displayMs > ws + WINDOW_MS * 0.6) void qc.prefetchQuery(fetchWindow(end));
    if (playing && displayMs >= end - 1000 && qc.getQueryData(fetchWindow(end).queryKey)) setWs(end);
  }, [displayMs, ws, end, playing, vid, qc, fetchWindow]);

  const highlight = useMemo(() => new Set(include ? include.split(",") : []), [include]);
  const lines: TrackLine[] = useMemo(() => {
    if (!data || !showOrbits) return [];
    const ids = new Set([...(selected ? [selected] : []), ...highlight]);
    return data.objects.filter((o) => ids.has(o.object_id)).map((o) => ({
      id: o.object_id, points: samplesOf(o).map(toScene), color: enc.data && o.object_id === enc.data.secondary_id ? "#ffc500" : "#ff5a36",
    }));
  }, [data, selected, highlight, showOrbits, enc.data]);
  const sel = data?.objects.find((o) => o.object_id === selected);
  const selPos = sel && data ? at(sel, data, displayMs) : null;
  const selPos2 = sel && data ? at(sel, data, displayMs + 1000) : null;
  const marker = useMemo(() => {
    if (!enc.data || !data) return null;
    const p = data.objects.find((o) => o.object_id === enc.data!.primary_id);
    const pos = p ? at(p, data, Date.parse(enc.data.tca_utc)) : null;
    return pos ? { at: pos, label: `TCA · miss ${km(enc.data.miss_km)}` } : null;
  }, [enc.data, data]);
  const seek = (ms: number) => { clock.current.t = ms; setDisplayMs(ms); };

  return (
    <div className="page" style={{ gap: 16 }}>
      <PageHead eyebrow="3D view" title="Earth and everything around it">
        Positions are propagated by the backend in 3-hour windows and animated in the browser. Motion between 2-minute samples is visual interpolation; no uncertainty is drawn.
      </PageHead>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <VersionPicker datasets={ds.data?.items} value={vid} onChange={(v) => { setVid(v); setSelected(null); }} filter={(f) => !f.startsWith("CDM") && !f.startsWith("STATES")} />
        <div className="field">Objects shown<Seg label="Objects shown" value={limit} onChange={setLimit} options={LIMITS} /></div>
        <div className="field">Speed<Seg label="Playback speed" value={speed} onChange={setSpeed} options={SPEEDS} /></div>
        <button className="btn primary" onClick={() => setPlaying(!playing)} aria-pressed={playing} disabled={!data}>{playing ? "Pause" : "Play"}</button>
        <button className="btn" onClick={() => { const n = Date.now(); setWs(alignHour(n)); seek(n); }}>Now</button>
        {enc.data && <button className="btn" onClick={() => { const t = Date.parse(enc.data!.tca_utc); setWs(alignHour(t - WINDOW_MS / 2)); seek(t); }}>TCA</button>}
      </div>
      <label className="field">
        {utc(iso(displayMs))}
        <input type="range" min={ws} max={end} step={10000} value={Math.min(Math.max(displayMs, ws), end)} onChange={(e) => seek(Number(e.target.value))} aria-label="Simulation time" />
      </label>
      {enc.data?.job.kind === "cdm_assessment" && <div className="notice">This encounter comes from a conjunction data message (states at TCA only). Open its relative-motion view instead.</div>}
      {tracks.error && <ErrorView error={tracks.error} />}
      <div className="scene">
        {data ? (
          <EarthScene data={data} clock={clock} end={end} selected={selected} highlight={highlight} tracks={lines} showAxes={showAxes}
            onSelect={setSelected} onTick={setDisplayMs} marker={marker} />
        ) : <Loading what={vid === null ? "Select a dataset" : "Propagating"} />}
        <div className="scene-overlay">
          <div className="scene-card">
            <div className="label">Scene</div>
            {data && <div className="mono">{data.shown_objects} of {data.total_objects} objects · {data.frame}</div>}
            {tracks.isFetching && <div className="muted">loading window…</div>}
            <div style={{ display: "flex", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
              <label><input type="checkbox" checked={showOrbits} onChange={(e) => setOrbits(e.target.checked)} /> orbit of selected</label>
              <label><input type="checkbox" checked={showAxes} onChange={(e) => setAxes(e.target.checked)} /> frame axes</label>
            </div>
            <div className="muted" style={{ marginTop: 6 }}>Bright: satellites · grey: debris. Click an object to follow it.</div>
          </div>
          {sel && (
            <div className="scene-card">
              <div className="label">Selected object</div>
              <div style={{ fontWeight: 600 }}>{sel.name ?? sel.object_id} <span className="mono muted">{sel.object_id}</span></div>
              {selPos && <div className="mono">alt {km(Math.hypot(...selPos) - 6378.137, 1)}</div>}
              {selPos && selPos2 && <div className="mono">|v| {Math.hypot(selPos2[0]! - selPos[0]!, selPos2[1]! - selPos[1]!, selPos2[2]! - selPos[2]!).toFixed(2)} km/s</div>}
              <div>Element-set age {ageLabel(sel.age_days)}</div>
              <div style={{ marginTop: 6 }}><Link to={`/p/${pid}/encounters`}>Encounters</Link> · <button className="btn small ghost" onClick={() => setSelected(null)}>Clear</button></div>
            </div>
          )}
        </div>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>
        Earth rotation uses the Earth Rotation Angle with UT1 ≈ UTC (visual). Showing a prioritised subset keeps animation smooth; screening always uses every object.
      </span>
    </div>
  );
}
