/** Decorative hero illustration (explicitly labelled; it shows no data). */
export default function OrbitArt() {
  return (
    <figure style={{ margin: 0, aspectRatio: "4/3", border: "1px solid var(--hair)", borderRadius: "var(--r)", background: "var(--s1)", position: "relative", overflow: "hidden" }}>
      <svg viewBox="0 0 400 300" width="100%" height="100%" role="img" aria-label="Decorative illustration of an orbit around Earth">
        <defs>
          <linearGradient id="og" x1="0" x2="1">
            <stop offset="0" stopColor="#c21500" />
            <stop offset="1" stopColor="#ffc500" />
          </linearGradient>
        </defs>
        <g stroke="var(--hair)" strokeWidth="1">
          <line x1="0" y1="150" x2="400" y2="150" />
          <line x1="200" y1="0" x2="200" y2="300" />
        </g>
        <circle cx="200" cy="150" r="62" fill="var(--s2)" stroke="var(--muted)" strokeWidth="1" />
        <ellipse cx="200" cy="150" rx="150" ry="58" fill="none" stroke="url(#og)" strokeWidth="5" transform="rotate(-18 200 150)" />
        <ellipse cx="200" cy="150" rx="128" ry="96" fill="none" stroke="var(--muted)" strokeWidth="1" strokeDasharray="4 5" transform="rotate(32 200 150)" />
        <circle cx="306" cy="98" r="7" fill="#ffc500" />
      </svg>
      <figcaption className="mono muted" style={{ position: "absolute", left: 14, bottom: 10, fontSize: 12 }}>illustration — not data</figcaption>
    </figure>
  );
}
