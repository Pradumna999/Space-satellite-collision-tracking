import type { ReactNode } from "react";
import { ApiError } from "../api/client";
import { PC_BANDS, sci } from "../lib/format";

export function Panel({ title, meta, actions, children, id }: { title?: ReactNode; meta?: ReactNode; actions?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section className="panel" aria-labelledby={id}>
      {(title || meta || actions) && (
        <div className="panel-head">
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
            {title && <h3 id={id}>{title}</h3>}
            {meta && <span className="muted" style={{ fontSize: 13 }}>{meta}</span>}
          </div>
          {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function PageHead({ eyebrow, title, children, actions }: { eyebrow?: string; title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions && <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>{actions}</div>}
    </header>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <div className="empty" role="status" aria-live="polite">{what}…</div>;
}

export function ErrorView({ error }: { error: unknown }) {
  const e = error as ApiError | Error;
  const code = e instanceof ApiError ? e.code : "ERROR";
  const rid = e instanceof ApiError ? e.requestId : undefined;
  return (
    <div className="notice error" role="alert">
      <strong>{code}</strong> — {e?.message ?? "unexpected error"}
      {rid && <span className="muted mono"> · request {rid}</span>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="stat" title={hint}>
      <span className="label">{label}</span>
      <span className="v">{value}</span>
    </div>
  );
}

/** Pc status badge. Colour is secondary to the text; geometry alone never produces a risk badge. */
export function PcBadge({ status, value }: { status: string; value: number | null }) {
  if (status !== "COMPUTED" || value === null) {
    const label = status === "INSUFFICIENT_DATA_FOR_PC" ? "Probability: needs uncertainty data" : status.replace(/_/g, " ").toLowerCase();
    return <span className="badge" title="Collision probability needs position-uncertainty data for both objects. Public tracking data does not include it, so only the distance is reported.">{label}</span>;
  }
  const band = value >= PC_BANDS.high ? "alert" : value >= PC_BANDS.elevated ? "warn" : "";
  const text = value >= PC_BANDS.high ? "Higher probability (≥ 1 in 10,000)" : value >= PC_BANDS.elevated ? "Low probability" : "Very low probability";
  return <span className={`badge ${band}`} title={`Pc = ${sci(value, 3)}. Display bands are presentation aids, not operational thresholds.`}>{text}</span>;
}

export function JobStatus({ status }: { status: string }) {
  const cls = ["succeeded", "screened", "assessed", "done"].includes(status) ? "ok" : status === "failed" ? "alert" : status === "running" ? "acc" : "";
  return <span className={`badge ${cls}`}>{status}</span>;
}

export function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string; disabled?: boolean; title?: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={o.value === value} disabled={o.disabled} title={o.title} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function Kv({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ChartMeta({ units, time, source, kind }: { units: string; time?: string; source: string; kind: "computed" | "propagated" | "supplied" | "predicted" | "measured" }) {
  return (
    <div className="chart-meta">
      <span>Units: {units}</span>
      {time && <span>Time: {time}</span>}
      <span>Source: {source}</span>
      <span className="badge">{kind}</span>
    </div>
  );
}

/** Plain-language explanation shown under a chart or section. */
export function Explain({ children, title = "What this shows" }: { children: ReactNode; title?: string }) {
  return (
    <div className="explain">
      <span className="label" style={{ color: "var(--accT)" }}>{title}</span>
      <div>{children}</div>
    </div>
  );
}
