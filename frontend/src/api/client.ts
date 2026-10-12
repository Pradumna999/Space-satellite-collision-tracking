/** Typed client for the ASTRAL REST API (v1). Cookie session + CSRF header. */

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string, public details?: unknown) {
    super(message);
  }
}

let csrfToken: string | null = null;
export const setCsrf = (t: string | null) => { csrfToken = t; };

async function request<T>(method: string, path: string, body?: unknown, extraHeaders: Record<string, string> = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(`/api/v1${path}`, { method, headers, body: payload, credentials: "same-origin" });
  const ct = res.headers.get("content-type") ?? "";
  if (!res.ok) {
    let code = "HTTP_ERROR", message = res.statusText, rid: string | undefined, details: unknown;
    if (ct.includes("json")) {
      const j = await res.json().catch(() => null);
      if (j?.error) ({ code, message, request_id: rid, details } = j.error);
    }
    throw new ApiError(res.status, code, message, rid, details);
  }
  if (ct.includes("json")) return (await res.json()) as T;
  return (await res.blob()) as unknown as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown, h?: Record<string, string>) => request<T>("POST", p, b, h),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b),
  del: <T>(p: string) => request<T>("DELETE", p),
};

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : "";
}

/** Download an authenticated resource and save it with its server-provided name. */
export async function download(path: string, fallbackName: string): Promise<void> {
  const res = await fetch(`/api/v1${path}`, { credentials: "same-origin" });
  if (!res.ok) {
    const j = await res.json().catch(() => null);
    throw new ApiError(res.status, j?.error?.code ?? "HTTP_ERROR", j?.error?.message ?? res.statusText);
  }
  const cd = res.headers.get("content-disposition") ?? "";
  const m = /filename="([^"]+)"/.exec(cd);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = m?.[1] ?? fallbackName;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Client-side CSV of chart data that is already on screen (no new values). */
export function downloadCsv(name: string, header: string[], rows: (string | number | null | undefined)[][], meta: string[] = []): void {
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [...meta.map((m) => `# ${m}`), header.map(esc).join(","), ...rows.map((r) => r.map(esc).join(","))];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
