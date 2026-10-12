export const km = (v: number | null | undefined, d = 3) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)} km`);
export const kms = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : `${v.toFixed(d)} km/s`);
export const sci = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "—" : v === 0 ? "< 1e-300" : v.toExponential(d));
export const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(d)}%`);
export const utc = (iso: string | null | undefined) => (iso ? iso.replace("T", " ").replace(/(\.\d{3})\d*/, "$1").replace(/Z?$/, " UTC").replace("+00:00", "") : "—");
export const short = (s: string, n = 12) => (s.length > n ? `${s.slice(0, n)}…` : s);

/** "T−04:12:08" relative to now; future TCAs are negative-countdown style. */
export function untilTca(iso: string, now = Date.now()): string {
  const t = Date.parse(iso.endsWith("Z") ? iso : `${iso}Z`);
  const s = Math.round((t - now) / 1000);
  const sign = s >= 0 ? "T−" : "T+";
  const a = Math.abs(s);
  const h = Math.floor(a / 3600), m = Math.floor((a % 3600) / 60), sec = a % 60;
  return `${sign}${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

export function ageLabel(days: number): string {
  if (days < 1) return `${(days * 24).toFixed(1)} h`;
  return `${days.toFixed(1)} d`;
}

/** Display bands for computed Pc only. These are presentation bands, not operational criteria. */
export const PC_BANDS = { high: 1e-4, elevated: 1e-7 };

/** Parse a server timestamp as UTC even when it carries no timezone (SQLite returns naive UTC). */
export function parseUtc(s: string): number {
  return Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : `${s.replace(" ", "T")}Z`);
}
