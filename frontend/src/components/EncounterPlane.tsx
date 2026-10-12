/**
 * Encounter-plane (B-plane-like) view from the design's "Encounter geometry"
 * panel. Axes: x along the miss vector's in-plane component, y = z × x, with z
 * along the relative velocity. Draws the nominal miss vector; the 1σ/3σ
 * ellipses appear ONLY when a projected combined covariance was computed.
 */
export default function EncounterPlane({ miss, cov, hbrKm }: { miss: number[]; cov?: number[][] | undefined; hbrKm?: number | undefined }) {
  const mx = miss[0] ?? 0, my = miss[1] ?? 0;
  let ell: { a: number; b: number; ang: number } | null = null;
  if (cov && cov.length === 2) {
    const a = cov[0]![0]!, b = cov[0]![1]!, d = cov[1]![1]!;
    const tr = (a + d) / 2, det = Math.sqrt(((a - d) / 2) ** 2 + b * b);
    const l1 = tr + det, l2 = Math.max(tr - det, 0);
    ell = { a: Math.sqrt(l1), b: Math.sqrt(l2), ang: (Math.atan2(l1 - a, b || 1e-30) * 180) / Math.PI };
    if (b === 0) ell.ang = a >= d ? 0 : 90;
  }
  const extent = Math.max(Math.hypot(mx, my) * 1.4, ell ? ell.a * 3.4 : 0, 0.05);
  const S = 160 / extent; // px per km in a 400x250 box centred at (200,125)
  const cx = 200, cy = 125;
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox="0 0 400 250" width="100%" role="img" aria-label={`Encounter plane: miss vector ${Math.hypot(mx, my).toFixed(3)} km${ell ? ", with covariance ellipses" : ", no covariance"}`}
        style={{ background: "var(--s1)", border: "1px solid var(--hair)", borderRadius: "var(--r)", display: "block" }}>
        <line x1="0" y1={cy} x2="400" y2={cy} stroke="var(--hair)" />
        <line x1={cx} y1="0" x2={cx} y2="250" stroke="var(--hair)" />
        {ell && [3, 1].map((k) => (
          <ellipse key={k} cx={cx + mx * S} cy={cy - my * S} rx={ell!.a * k * S} ry={ell!.b * k * S} fill="none" stroke="var(--accT)"
            strokeWidth={k === 1 ? 1.5 : 1} strokeDasharray={k === 1 ? "5 4" : "2 4"} transform={`rotate(${-ell!.ang} ${cx + mx * S} ${cy - my * S})`} />
        ))}
        {hbrKm !== undefined && <circle cx={cx} cy={cy} r={Math.max(hbrKm * S, 1.5)} fill="none" stroke="var(--text)" strokeWidth="1" />}
        <line x1={cx} y1={cy} x2={cx + mx * S} y2={cy - my * S} stroke="var(--muted)" strokeDasharray="3 3" />
        <circle cx={cx} cy={cy} r="5" fill="var(--text)" />
        <circle cx={cx + mx * S} cy={cy - my * S} r="5" fill="var(--alert)" />
        <text x="388" y={cy + 14} fill="var(--muted)" fontSize="11" fontFamily="var(--fm)" textAnchor="end">ξ</text>
        <text x={cx + 8} y="14" fill="var(--muted)" fontSize="11" fontFamily="var(--fm)">ζ</text>
        <text x="8" y="242" fill="var(--muted)" fontSize="10" fontFamily="var(--fm)">
          {ell ? "encounter plane · combined covariance 1σ (dashed) / 3σ (dotted)" : "encounter plane · nominal miss vector only (no covariance)"}
        </text>
        <text x="392" y="14" fill="var(--muted)" fontSize="10" fontFamily="var(--fm)" textAnchor="end">±{extent.toFixed(3)} km</text>
      </svg>
      <figcaption className="sr-only">Primary at the origin (filled, ink colour); secondary at the miss vector (filled, alert colour).</figcaption>
    </figure>
  );
}
