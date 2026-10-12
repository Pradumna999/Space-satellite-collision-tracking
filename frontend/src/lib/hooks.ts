import { useQuery } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { Dataset, Encounter, Job, Paged } from "../api/types";

export function useDatasets(pid: number) {
  return useQuery({ queryKey: ["datasets", pid], queryFn: () => api.get<{ items: Dataset[] }>(`/projects/${pid}/datasets`) });
}

export function useJobs(pid: number, poll = false) {
  return useQuery({
    queryKey: ["jobs", pid],
    queryFn: () => api.get<Paged<Job>>(`/projects/${pid}/jobs${qs({ limit: 100 })}`),
    refetchInterval: (q) => (poll || q.state.data?.items.some((j) => j.status === "queued" || j.status === "running") ? 2000 : false),
  });
}

export function useEncounters(pid: number, params: Record<string, string | number | undefined>) {
  return useQuery({
    queryKey: ["encounters", pid, params],
    queryFn: () => api.get<Paged<Encounter>>(`/projects/${pid}/encounters${qs(params)}`),
  });
}

/** All dataset versions flattened, newest first, with their dataset. */
export function versionsOf(datasets: Dataset[] | undefined) {
  const out: { ds: Dataset; v: Dataset["versions"][number] }[] = [];
  for (const ds of datasets ?? []) for (const v of ds.versions) out.push({ ds, v });
  return out.sort((a, b) => b.v.id - a.v.id);
}
