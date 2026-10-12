/**
 * Design tokens ported from "ASTRAL Pairings.dc.html" (docs/design/).
 * Two pairings — D "Ignition" (default) and E "Kyoto" — each with dark and
 * light modes, a density scale and an accent-hue shift. The token names
 * (--bg, --s1, --s2, --text, --muted, --rule, --hair, --ctl, --acc, --accH,
 * --accT, --on, --alert, --onAlert, --warn, --ok, --grad, --r, --rw, --d,
 * --fh, --fb, --fm, --fhw, --fhls, --lf, --ltt, --lls, --lw) are the design's.
 */

export type PairingKey = "D" | "E";
export type Mode = "dark" | "light";
export type Density = "compact" | "regular" | "comfortable";
export type FontSet = "Pairing default" | "Fjalla One + Cantarell" | "Quicksand";

type Lch = [number, number, number];

interface Palette {
  bg: string; s1: string; s2: string; text: string; muted: string; rule: string; hair: string; ctl: string;
  acc: Lch; accT: Lch; on: string; alert: string; onAlert: string; warn: string; ok: string;
}

interface Pairing {
  key: PairingKey; name: string; tag: string; font: PairingKey; r: string; rw: string; note: string;
  grad: (acc: string) => string; dark: Palette; light: Palette;
}

export const PAIRS: Record<PairingKey, Pairing> = {
  D: {
    key: "D", name: "Ignition", tag: "Teammate direction", font: "D", r: "0px", rw: "2px",
    note: "Black ground, a red accent and yellow as the secondary colour. Fjalla One headings over Cantarell body text.",
    grad: (acc) => `linear-gradient(90deg, oklch(0.12 0.006 30), ${acc} 55%, oklch(0.87 0.17 92))`,
    dark: { bg: "oklch(0.14 0.006 30)", s1: "oklch(0.18 0.008 30)", s2: "oklch(0.225 0.01 30)", text: "oklch(0.97 0.004 80)", muted: "oklch(0.80 0.008 60)", rule: "oklch(0.97 0.004 80)", hair: "oklch(0.30 0.01 30)", ctl: "oklch(0.97 0.004 80)", acc: [0.60, 0.22, 28], accT: [0.86, 0.17, 92], on: "#ffffff", alert: "oklch(0.66 0.22 28)", onAlert: "oklch(0.13 0.006 30)", warn: "oklch(0.86 0.17 92)", ok: "oklch(0.80 0.10 160)" },
    light: { bg: "oklch(0.975 0.006 85)", s1: "oklch(0.995 0.003 85)", s2: "oklch(0.93 0.01 80)", text: "oklch(0.14 0.006 30)", muted: "oklch(0.38 0.01 40)", rule: "oklch(0.14 0.006 30)", hair: "oklch(0.86 0.01 70)", ctl: "oklch(0.14 0.006 30)", acc: [0.55, 0.22, 28], accT: [0.45, 0.19, 28], on: "#ffffff", alert: "oklch(0.50 0.20 28)", onAlert: "#ffffff", warn: "oklch(0.52 0.12 75)", ok: "oklch(0.45 0.10 160)" },
  },
  E: {
    key: "E", name: "Kyoto", tag: "Black + Kyoto gradient", font: "E", r: "8px", rw: "1px",
    note: "Black as the main colour with the Kyoto gradient (deep red to golden yellow). Quicksand headings and body, Plex Mono figures.",
    grad: () => "linear-gradient(90deg, #c21500, #ffc500)",
    dark: { bg: "oklch(0.13 0 0)", s1: "oklch(0.175 0.003 40)", s2: "oklch(0.22 0.004 40)", text: "oklch(0.97 0.004 80)", muted: "oklch(0.80 0.006 60)", rule: "oklch(0.32 0.006 40)", hair: "oklch(0.27 0.005 40)", ctl: "oklch(0.52 0.008 40)", acc: [0.72, 0.18, 55], accT: [0.66, 0.21, 32], on: "oklch(0.13 0 0)", alert: "oklch(0.64 0.21 32)", onAlert: "oklch(0.13 0 0)", warn: "oklch(0.86 0.17 85)", ok: "oklch(0.80 0.10 160)" },
    light: { bg: "oklch(0.98 0.004 80)", s1: "#ffffff", s2: "oklch(0.94 0.006 70)", text: "oklch(0.13 0 0)", muted: "oklch(0.38 0.006 50)", rule: "oklch(0.13 0 0)", hair: "oklch(0.88 0.006 70)", ctl: "oklch(0.13 0 0)", acc: [0.13, 0, 0], accT: [0.56, 0.17, 50], on: "#ffffff", alert: "oklch(0.50 0.20 32)", onAlert: "#ffffff", warn: "oklch(0.52 0.12 75)", ok: "oklch(0.45 0.10 160)" },
  },
};

interface Fonts { label: string; fh: string; fb: string; fm: string; fhw: string; fhls: string; lf: string; ltt: string; lls: string; lw: string }

export const FONTS: Record<PairingKey, Fonts> = {
  E: { label: "Quicksand 700 · Quicksand 400 · Plex Mono figures", fh: "'Quicksand', sans-serif", fb: "'Quicksand', sans-serif", fm: "'IBM Plex Mono', monospace", fhw: "700", fhls: "-0.02em", lf: "'Quicksand', sans-serif", ltt: "uppercase", lls: "0.06em", lw: "700" },
  D: { label: "Fjalla One 400 · Cantarell 400/700 · Plex Mono figures", fh: "'Fjalla One', sans-serif", fb: "'Cantarell', sans-serif", fm: "'IBM Plex Mono', monospace", fhw: "400", fhls: "0.005em", lf: "'Fjalla One', sans-serif", ltt: "uppercase", lls: "0.07em", lw: "400" },
};

const FONTSET: Record<FontSet, PairingKey | null> = { "Pairing default": null, "Fjalla One + Cantarell": "D", Quicksand: "E" };
const DENS: Record<Density, number> = { compact: 0.72, regular: 1, comfortable: 1.3 };

export interface ThemeSettings { pairing: PairingKey; mode: Mode; fontSet: FontSet; accentHue: number; density: Density }

export const DEFAULT_THEME: ThemeSettings = { pairing: "D", mode: "dark", fontSet: "Pairing default", accentHue: 0, density: "regular" };

export function themeVars(t: ThemeSettings): Record<string, string> {
  const p = PAIRS[t.pairing] ?? PAIRS.D;
  const c = p[t.mode];
  const f = FONTS[FONTSET[t.fontSet] ?? p.font];
  const shift = t.accentHue;
  const ok = (a: Lch, dl = 0) => `oklch(${(a[0] + dl).toFixed(3)} ${a[1]} ${(((a[2] + shift) % 360) + 360) % 360})`;
  return {
    "--bg": c.bg, "--s1": c.s1, "--s2": c.s2, "--text": c.text, "--muted": c.muted, "--rule": c.rule, "--hair": c.hair, "--ctl": c.ctl,
    "--acc": ok(c.acc), "--accH": ok(c.acc, t.mode === "dark" ? 0.05 : -0.06), "--accT": ok(c.accT), "--on": c.on,
    "--alert": c.alert, "--onAlert": c.onAlert, "--warn": c.warn, "--ok": c.ok,
    "--grad": p.grad(ok(c.acc)),
    "--r": p.r, "--rw": p.rw, "--d": String(DENS[t.density]),
    "--fh": f.fh, "--fb": f.fb, "--fm": f.fm, "--fhw": f.fhw, "--fhls": f.fhls, "--lf": f.lf, "--ltt": f.ltt, "--lls": f.lls, "--lw": f.lw,
  };
}

export function fontLabel(t: ThemeSettings): string {
  return FONTS[FONTSET[t.fontSet] ?? PAIRS[t.pairing].font].label;
}

const KEY = "astral.theme.v1";

export function loadTheme(): ThemeSettings {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_THEME;
    const v = JSON.parse(raw) as Partial<ThemeSettings>;
    return { ...DEFAULT_THEME, ...v };
  } catch {
    return DEFAULT_THEME;
  }
}

export function saveTheme(t: ThemeSettings): void {
  localStorage.setItem(KEY, JSON.stringify(t));
}

export function applyTheme(t: ThemeSettings): void {
  const root = document.documentElement;
  for (const [k, v] of Object.entries(themeVars(t))) root.style.setProperty(k, v);
  root.dataset.mode = t.mode;
  root.style.colorScheme = t.mode;
}
