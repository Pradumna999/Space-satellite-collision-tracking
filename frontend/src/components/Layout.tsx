import { NavLink, Outlet, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useAuth } from "../lib/context";

const NAV = [
  ["overview", "At a glance"],
  ["environment", "3D view"],
  ["encounters", "Close approaches"],
  ["scenarios", "Avoidance manoeuvres"],
  ["screening", "Run a search"],
  ["analytics", "Charts"],
  ["catalogue", "Tracked objects"],
  ["datasets", "Data sources"],
  ["reports", "Reports"],
  ["ml", "AI ranking (beta)"],
  ["admin", "Settings"],
  ["guide", "How it works"],
] as const;

export function useProjectId(): number {
  const { pid } = useParams();
  return Number(pid);
}

export function useProjects() {
  return useQuery({ queryKey: ["projects"], queryFn: () => api.get<{ items: Project[] }>("/projects") });
}

export default function Layout() {
  const pid = useProjectId();
  const nav = useNavigate();
  const { me, logout } = useAuth();
  const projects = useProjects();
  const current = projects.data?.items.find((p) => p.id === pid);
  return (
    <div className="shell">
      <nav className="sidenav" aria-label="Primary">
        <NavLink to="/" className="brand" end>ASTRAL</NavLink>
        {NAV.map(([path, label], i) => (
          <NavLink key={path} to={`/p/${pid}/${path}`} className={({ isActive }) => (isActive ? "active" : undefined)}>
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            <span>{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="main">
        <div className="topbar">
          <label className="sr-only" htmlFor="project-select">Project</label>
          <select id="project-select" className="input" value={pid} onChange={(e) => nav(`/p/${e.target.value}/overview`)} style={{ maxWidth: 320 }}>
            {projects.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {current && <span className="badge">{current.role}</span>}
          <span style={{ marginLeft: "auto" }} className="muted">{me?.user.display_name}</span>
          <button className="btn small" onClick={() => logout().then(() => nav("/"))}>Sign out</button>
        </div>
        <div className="ramp" aria-hidden />
        <Outlet />
        <footer className="muted" style={{ fontSize: 12, padding: "0 28px 24px" }}>
          Research and evaluation software. Not qualified for operational conjunction assessment. Results require independent expert review.
        </footer>
      </div>
    </div>
  );
}
