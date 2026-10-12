import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { Paged, User } from "../api/types";
import { useProjectId } from "../components/Layout";
import { ErrorView, Kv, PageHead, Panel, Seg } from "../components/ui";
import { useAuth, useTheme } from "../lib/context";
import { PAIRS, fontLabel, type Density, type FontSet, type Mode, type PairingKey } from "../theme/theme";
import { utc } from "../lib/format";

interface Audit { id: number; at: string; user_id: number | null; action: string; project_id: number | null; target: string | null; details: Record<string, unknown>; outcome: string; request_id: string | null }

function Appearance() {
  const { theme, setTheme } = useTheme();
  const p = PAIRS[theme.pairing];
  return (
    <Panel title="Appearance" meta="colour & type pairing (from the ASTRAL design exploration)">
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
          <div className="field">Pairing<Seg<PairingKey> label="Pairing" value={theme.pairing} onChange={(v) => setTheme({ ...theme, pairing: v })} options={[{ value: "D", label: "D Ignition" }, { value: "E", label: "E Kyoto" }]} /></div>
          <div className="field">Mode<Seg<Mode> label="Mode" value={theme.mode} onChange={(v) => setTheme({ ...theme, mode: v })} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} /></div>
          <div className="field">Density<Seg<Density> label="Density" value={theme.density} onChange={(v) => setTheme({ ...theme, density: v })} options={[{ value: "compact", label: "Compact" }, { value: "regular", label: "Regular" }, { value: "comfortable", label: "Comfortable" }]} /></div>
          <label className="field">Font set<select value={theme.fontSet} onChange={(e) => setTheme({ ...theme, fontSet: e.target.value as FontSet })}>
            {(["Pairing default", "Fjalla One + Cantarell", "Quicksand"] as FontSet[]).map((f) => <option key={f}>{f}</option>)}</select></label>
          <label className="field">Accent hue shift ({theme.accentHue}°)<input type="range" min={-180} max={180} step={5} value={theme.accentHue} onChange={(e) => setTheme({ ...theme, accentHue: Number(e.target.value) })} /></label>
        </div>
        <p className="muted" style={{ margin: 0 }}>{p.name}: {p.note} <span className="mono">{fontLabel(theme)}</span></p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0,1fr))", border: "var(--rw) solid var(--rule)", borderRadius: "var(--r)", overflow: "hidden" }}>
          {[["--bg", "ground", "--muted"], ["--s1", "surface", "--muted"], ["--s2", "raised", "--muted"], ["--text", "ink", "--bg"], ["--acc", "accent", "--on"], ["--alert", "Pc ≥ 1e-4 band", "--onAlert"], ["--warn", "Pc 1e-7–1e-4 band", "--onAlert"], ["--ok", "nominal", "--onAlert"]].map(([bg, l, fg]) => (
            <div key={bg} style={{ background: `var(${bg})`, color: `var(${fg})`, height: 56, padding: 8, display: "flex", alignItems: "flex-end", fontFamily: "var(--fm)", fontSize: 11 }}>{l}</div>
          ))}
          <div style={{ gridColumn: "1/-1", height: 28, background: "var(--grad)", color: "#fff", fontFamily: "var(--fm)", fontSize: 11, padding: "6px 8px" }}>ramp</div>
        </div>
      </div>
    </Panel>
  );
}

function Tokens() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["tokens"], queryFn: () => api.get<{ items: { id: number; label: string; expires_at: string }[] }>("/auth/tokens") });
  const [label, setLabel] = useState("");
  const [shown, setShown] = useState<string | null>(null);
  const create = useMutation({ mutationFn: () => api.post<{ token: string }>("/auth/tokens", { label, days: 30 }), onSuccess: (r) => { setShown(r.token); setLabel(""); qc.invalidateQueries({ queryKey: ["tokens"] }); } });
  const revoke = useMutation({ mutationFn: (id: number) => api.del(`/auth/tokens/${id}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["tokens"] }) });
  return (
    <Panel title="API tokens" meta="for scripted access (Authorization: Bearer)">
      <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <form style={{ display: "flex", gap: 8, alignItems: "flex-end" }} onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <label className="field" style={{ flex: 1 }}>Label<input value={label} onChange={(e) => setLabel(e.target.value)} required maxLength={100} /></label>
          <button className="btn">Create (30 days)</button>
        </form>
        {shown && <div className="notice">Copy this token now; it is not shown again: <span className="mono" style={{ wordBreak: "break-all" }}>{shown}</span></div>}
        <table className="data"><tbody>{list.data?.items.map((t) => <tr key={t.id}><td>{t.label}</td><td className="muted">expires {utc(t.expires_at)}</td><td><button className="btn small ghost" onClick={() => revoke.mutate(t.id)}>Revoke</button></td></tr>)}</tbody></table>
      </div>
    </Panel>
  );
}

function Members({ pid }: { pid: number }) {
  const qc = useQueryClient();
  const proj = useQuery({ queryKey: ["project", pid], queryFn: () => api.get<{ role: string; members: { user_id: number; email: string; display_name: string; role: string }[] }>(`/projects/${pid}`) });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const add = useMutation({ mutationFn: () => api.post(`/projects/${pid}/members`, { email, role }), onSuccess: () => qc.invalidateQueries({ queryKey: ["project", pid] }) });
  return (
    <Panel title="Project members" meta="data isolation is per project">
      <table className="data"><tbody>{proj.data?.members.map((m) => <tr key={m.user_id}><td>{m.display_name}</td><td className="mono muted">{m.email}</td><td><span className="badge">{m.role}</span></td></tr>)}</tbody></table>
      {proj.data?.role === "owner" && (
        <form className="panel-body" style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
          <label className="field" style={{ flex: 1 }}>User email<input value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
          <label className="field">Role<select value={role} onChange={(e) => setRole(e.target.value)}><option>viewer</option><option>analyst</option><option>owner</option></select></label>
          <button className="btn">Add / update</button>
        </form>
      )}
      {add.error && <div className="panel-body"><ErrorView error={add.error} /></div>}
    </Panel>
  );
}

function UsersAdmin() {
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<{ items: User[] }>("/admin/users") });
  const [f, setF] = useState({ email: "", display_name: "", password: "", is_admin: false });
  const create = useMutation({ mutationFn: () => api.post("/admin/users", f), onSuccess: () => { setF({ email: "", display_name: "", password: "", is_admin: false }); qc.invalidateQueries({ queryKey: ["users"] }); } });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) => api.patch(`/admin/users/${id}`, body), onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }) });
  return (
    <Panel title="Accounts" meta="administrators manage accounts; they do not gain access to project data">
      <table className="data"><thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th><th></th></tr></thead>
        <tbody>{users.data?.items.map((u) => (
          <tr key={u.id}><td>{u.display_name}</td><td className="mono">{u.email}</td><td>{u.is_admin ? <span className="badge acc">admin</span> : "user"}</td><td>{u.is_active ? "yes" : "no"}</td>
            <td><button className="btn small" onClick={() => patch.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? "Deactivate" : "Activate"}</button></td></tr>))}</tbody></table>
      <form className="panel-body" style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
        <label className="field">Email<input type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></label>
        <label className="field">Name<input required value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
        <label className="field">Initial password<input type="password" minLength={12} required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" /></label>
        <label><input type="checkbox" checked={f.is_admin} onChange={(e) => setF({ ...f, is_admin: e.target.checked })} /> admin</label>
        <button className="btn">Create account</button>
      </form>
      {(create.error || patch.error) && <div className="panel-body"><ErrorView error={create.error ?? patch.error} /></div>}
    </Panel>
  );
}

function AuditLog() {
  const [action, setAction] = useState("");
  const log = useQuery({ queryKey: ["audit", action], queryFn: () => api.get<Paged<Audit>>(`/admin/audit${qs({ action, limit: 200 })}`) });
  return (
    <Panel title="Audit log" meta={log.data ? `${log.data.total} events` : undefined} actions={<input className="input" placeholder="filter action prefix, e.g. dataset" value={action} onChange={(e) => setAction(e.target.value)} />}>
      <div className="table-wrap" style={{ maxHeight: 420, overflowY: "auto" }}>
        <table className="data"><thead><tr><th>Time</th><th>User</th><th>Action</th><th>Project</th><th>Target</th><th>Outcome</th><th>Details</th></tr></thead>
          <tbody>{log.data?.items.map((a) => (
            <tr key={a.id}><td className="mono muted">{utc(a.at)}</td><td className="mono">{a.user_id ?? "—"}</td><td className="mono">{a.action}</td><td className="mono">{a.project_id ?? "—"}</td>
              <td className="mono">{a.target ?? ""}</td><td><span className={`badge ${a.outcome === "ok" ? "" : "warn"}`}>{a.outcome}</span></td><td className="mono muted" style={{ fontSize: 11 }}>{JSON.stringify(a.details)}</td></tr>))}</tbody></table>
      </div>
    </Panel>
  );
}

export default function Admin() {
  const pid = useProjectId();
  const { me } = useAuth();
  const sys = useQuery({ queryKey: ["sys-full"], queryFn: () => api.get<Record<string, unknown>>("/system/info"), refetchInterval: 10000 });
  const ready = useQuery({ queryKey: ["ready"], queryFn: () => fetch("/api/v1/health/ready").then((r) => r.json() as Promise<{ status: string; checks: Record<string, { ok: boolean }> }>), refetchInterval: 10000 });
  const s = sys.data as { version?: string; profile?: string; uptime_s?: number; queue?: Record<string, number>; process?: Record<string, number>; limits?: Record<string, number>; dependencies?: Record<string, string>; leap_second_table_expires?: string; readiness_statement?: string } | undefined;
  return (
    <div className="page">
      <PageHead eyebrow="Settings" title="Settings">{s?.readiness_statement}</PageHead>
      <div className="grid cols-2">
        <Panel title="System health" meta={ready.data?.status}>
          <div className="panel-body">
            <Kv items={[
              ...Object.entries(ready.data?.checks ?? {}).map(([k, v]) => [k, v.ok ? "ok" : "DEGRADED"] as [string, string]),
              ["Version / profile", `${s?.version ?? "—"} / ${s?.profile ?? "—"}`],
              ["Uptime", s?.uptime_s ? `${Math.round(s.uptime_s / 60)} min` : "—"],
              ["Job queue", JSON.stringify(s?.queue ?? {})],
              ["Process", JSON.stringify(s?.process ?? {})],
              ["Limits", JSON.stringify(s?.limits ?? {})],
              ["Dependencies", JSON.stringify(s?.dependencies ?? {})],
              ["Leap-second table expires", s?.leap_second_table_expires ?? "—"],
            ]} />
          </div>
        </Panel>
        <Appearance />
      </div>
      <div className="grid cols-2">
        <Members pid={pid} />
        <Tokens />
      </div>
      {me?.user.is_admin && <UsersAdmin />}
      {me?.user.is_admin && <AuditLog />}
    </div>
  );
}
