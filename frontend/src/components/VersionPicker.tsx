import type { Dataset } from "../api/types";
import { versionsOf } from "../lib/hooks";

export default function VersionPicker({ datasets, value, onChange, filter, label = "Dataset version" }: {
  datasets: Dataset[] | undefined; value: number | null; onChange: (v: number) => void;
  filter?: (format: string) => boolean; label?: string;
}) {
  const vs = versionsOf(datasets).filter((x) => !filter || filter(x.v.format));
  return (
    <label className="field" style={{ minWidth: 260 }}>
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))}>
        {value === null && <option value="">Select…</option>}
        {vs.map(({ ds, v }) => (
          <option key={v.id} value={v.id}>
            {ds.name} · v{v.version} · {v.format} · {v.status}
          </option>
        ))}
      </select>
    </label>
  );
}
