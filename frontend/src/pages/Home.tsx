import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Project } from "../api/types";
import { useProjects } from "../components/Layout";
import { Empty, ErrorView, Loading, PageHead, Panel } from "../components/ui";
import { useAuth } from "../lib/context";

export default function Home() {
  const projects = useProjects();
  const { me, logout } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", { name }),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["projects"] }); nav(`/p/${p.id}/datasets`); },
  });
  return (
    <div className="page" style={{ maxWidth: 960 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="brand">ASTRAL</span>
        <span className="muted">{me?.user.email} · <button className="btn small" onClick={() => logout()}>Sign out</button></span>
      </div>
      <PageHead eyebrow="Workspace" title="Projects">Projects isolate datasets, analyses and reports. Only members can see a project's data.</PageHead>
      <Panel title="Your projects">
        {projects.isLoading && <Loading />}
        {projects.error && <ErrorView error={projects.error} />}
        {projects.data && projects.data.items.length === 0 && <Empty>No projects yet. Create one below, or ask an administrator to load public data with <span className="mono">python -m astral.cli seed-live</span>.</Empty>}
        <table className="data">
          <tbody>
            {projects.data?.items.map((p) => (
              <tr key={p.id} className="clickable" onClick={() => nav(`/p/${p.id}/overview`)}>
                <td><Link to={`/p/${p.id}/overview`}>{p.name}</Link></td>
                <td className="muted">{p.description}</td>
                <td><span className="badge">{p.role}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="New project">
        <form className="panel-body" style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }} onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
          <label className="field" style={{ flex: 1, minWidth: 240 }}>Name<input required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} /></label>
          <button className="btn primary" disabled={!name || create.isPending}>Create project →</button>
        </form>
        {create.error && <div className="panel-body"><ErrorView error={create.error} /></div>}
      </Panel>
    </div>
  );
}
