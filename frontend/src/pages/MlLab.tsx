import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, downloadCsv } from "../api/client";
import type { MLModel } from "../api/types";
import { ChartMeta, Empty, ErrorView, Kv, Loading, PageHead, Panel } from "../components/ui";
import { useAuth } from "../lib/context";
import { pct, utc } from "../lib/format";

const tip = { contentStyle: { background: "var(--s1)", border: "1px solid var(--hair)", fontSize: 12 } };

export default function MlLab() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const models = useQuery({
    queryKey: ["ml"], queryFn: () => api.get<{ items: MLModel[]; training: { status: string; error?: string } | null }>("/ml/models"),
    refetchInterval: (q) => (q.state.data?.training?.status === "running" ? 3000 : false),
  });
  const [sel, setSel] = useState<number | null>(null);
  const m = models.data?.items.find((x) => x.id === sel) ?? models.data?.items[0];
  const trainM = useMutation({ mutationFn: () => api.post("/ml/train"), onSuccess: () => qc.invalidateQueries({ queryKey: ["ml"] }) });
  const toggle = useMutation({ mutationFn: ({ id, on }: { id: number; on: boolean }) => api.post(`/ml/models/${id}/${on ? "activate" : "deactivate"}`), onSuccess: () => qc.invalidateQueries({ queryKey: ["ml"] }) });
  const algo = m ? String(m.params.algorithm) : "";
  const tm = m?.metrics.test[algo];
  const rule = m?.metrics.test.rule_miss;
  const pr = tm ? tm.pr_curve.recall.map((r, i) => ({ recall: r, model: tm.pr_curve.precision[i] })) : [];
  const prRule = rule ? rule.pr_curve.recall.map((r, i) => ({ recall: r, rule: rule.pr_curve.precision[i] })) : [];
  const cal = tm?.calibration ? tm.calibration.mean_predicted.map((p, i) => ({ predicted: p, observed: tm.calibration!.fraction_positive[i], ideal: p })) : [];
  return (
    <div className="page">
      <PageHead eyebrow="AI ranking (beta)" title="AI-assisted ranking" actions={me?.user.is_admin && (
        <button className="btn primary" disabled={trainM.isPending || models.data?.training?.status === "running"} onClick={() => trainM.mutate()}>
          {models.data?.training?.status === "running" ? "Training…" : "Train new experimental model"}
        </button>)}>
        Experimental prioritisation of encounters for analyst review. Scores are <strong>not</strong> probabilities of collision and never replace the physical analysis. Models are experimental and have not been validated against operational data.
      </PageHead>
      {models.data?.training?.status === "failed" && <div className="notice error">Last training run failed: {models.data.training.error}</div>}
      {trainM.error && <ErrorView error={trainM.error} />}
      <div className="grid cols-2">
        <Panel title="Model registry">
          {models.isLoading && <Loading />}
          {models.data?.items.length === 0 && <Empty>No models. {me?.user.is_admin ? "Train one above." : "An administrator can train one."} The screening pipeline works without ML.</Empty>}
          <table className="data">
            <thead><tr><th>Model</th><th>Algorithm</th><th>Status</th><th className="num">Test AP</th><th>Created</th></tr></thead>
            <tbody>
              {models.data?.items.map((x) => (
                <tr key={x.id} className={`clickable ${x.id === m?.id ? "selected" : ""}`} onClick={() => setSel(x.id)}>
                  <td className="mono">{x.name}:{x.version}</td>
                  <td>{String(x.params.algorithm)}</td>
                  <td><span className={`badge ${x.status === "active_experimental" ? "acc" : ""}`}>{x.status.replace("_", " ")}</span></td>
                  <td className="num">{x.metrics.test[String(x.params.algorithm)]?.average_precision.toFixed(3)}</td>
                  <td className="muted">{utc(x.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        {m && tm && (
          <Panel title={`${m.name}:${m.version}`} meta={m.label} actions={me?.user.is_admin && (
            <button className="btn small" onClick={() => toggle.mutate({ id: m.id, on: m.status !== "active_experimental" })}>
              {m.status === "active_experimental" ? "Deactivate" : "Use for priority scores"}
            </button>)}>
            <div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              <Kv items={[
                ["Label definition", String(m.params.label_definition)],
                ["Test set", `${tm.n} events, ${tm.positives} positive (prevalence ${pct(tm.prevalence)})`],
                ["Average precision", `${tm.average_precision.toFixed(3)} (rule baseline ${rule?.average_precision.toFixed(3)})`],
                ["Precision / recall @0.5", `${tm.precision?.toFixed(3)} / ${tm.recall?.toFixed(3)}`],
                ["False-negative rate", tm.false_negative_rate?.toFixed(3) ?? "—"],
                ["False-positive rate", tm.false_positive_rate?.toFixed(4) ?? "—"],
                ["Brier score", tm.brier?.toFixed(4) ?? "—"],
                ["Split sizes", JSON.stringify(m.metrics.split_sizes)],
                ["Training data SHA-256", m.training_data_sha256],
                ["Artefact SHA-256", m.artefact_sha256],
                ["Seed / code", `${m.seed} / astral ${m.code_version}, sklearn ${String(m.params.sklearn)}`],
                ["Features", m.feature_schema.features.join(", ")],
              ]} />
              {tm.confusion_matrix && (
                <table className="data" style={{ maxWidth: 360 }} aria-label="Confusion matrix">
                  <thead><tr><th></th><th className="num">pred. low</th><th className="num">pred. priority</th></tr></thead>
                  <tbody>
                    <tr><td>actual low</td><td className="num">{tm.confusion_matrix.tn}</td><td className="num">{tm.confusion_matrix.fp}</td></tr>
                    <tr><td>actual priority</td><td className="num">{tm.confusion_matrix.fn}</td><td className="num">{tm.confusion_matrix.tp}</td></tr>
                  </tbody>
                </table>
              )}
              <div className="notice">Accuracy is not reported: with {pct(tm.prevalence)} positives a model that never flags anything would look highly "accurate". Compare average precision against the rule baseline instead.</div>
            </div>
          </Panel>
        )}
      </div>
      {m && tm && (
        <div className="grid cols-2">
          <Panel title="Precision–recall" meta="held-out temporal test split" actions={<button className="btn small" onClick={() => downloadCsv(`pr-${m.name}-${m.version}.csv`, ["recall", "precision_model"], pr.map((p) => [p.recall, p.model]))}>CSV</button>}>
            <div className="chart-box">
              <ResponsiveContainer>
                <LineChart margin={{ left: 8, right: 20, top: 12, bottom: 18 }}>
                  <CartesianGrid stroke="var(--hair)" />
                  <XAxis dataKey="recall" type="number" domain={[0, 1]} stroke="var(--muted)" fontSize={11} label={{ value: "recall", position: "insideBottom", offset: -8, fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis domain={[0, 1]} stroke="var(--muted)" fontSize={11} label={{ value: "precision", angle: -90, position: "insideLeft", fill: "var(--muted)", fontSize: 11 }} />
                  <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line data={pr} dataKey="model" name={algo} stroke="var(--acc)" dot={false} isAnimationActive={false} />
                  <Line data={prRule} dataKey="rule" name="rule: miss distance" stroke="var(--muted)" dot={false} strokeDasharray="4 3" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <ChartMeta units="dimensionless" source={`model ${m.name}:${m.version} evaluation`} kind="computed" />
          </Panel>
          <Panel title="Calibration" meta="quantile bins">
            <div className="chart-box">
              <ResponsiveContainer>
                <LineChart data={cal} margin={{ left: 8, right: 20, top: 12, bottom: 18 }}>
                  <CartesianGrid stroke="var(--hair)" />
                  <XAxis dataKey="predicted" type="number" domain={[0, 1]} stroke="var(--muted)" fontSize={11} label={{ value: "mean predicted score", position: "insideBottom", offset: -8, fill: "var(--muted)", fontSize: 11 }} />
                  <YAxis domain={[0, 1]} stroke="var(--muted)" fontSize={11} />
                  <Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="ideal" name="perfect calibration" stroke="var(--hair)" dot={false} isAnimationActive={false} />
                  <Line dataKey="observed" name="observed fraction positive" stroke="var(--accT)" isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <ChartMeta units="dimensionless" source={`model ${m.name}:${m.version} evaluation`} kind="computed" />
          </Panel>
        </div>
      )}
      {m && tm?.by_regime && (
        <Panel title="Performance by orbital regime">
          <table className="data"><thead><tr><th>Regime</th><th className="num">Events</th><th className="num">Average precision</th></tr></thead>
            <tbody>{Object.entries(tm.by_regime).map(([k, r]) => <tr key={k}><td>{k}</td><td className="num">{r.n}</td><td className="num">{r.average_precision.toFixed(3)}</td></tr>)}</tbody></table>
        </Panel>
      )}
    </div>
  );
}
