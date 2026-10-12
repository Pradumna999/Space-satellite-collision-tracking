import { Link } from "react-router-dom";
import { useProjectId } from "../components/Layout";
import { PageHead, Panel } from "../components/ui";

const GLOSSARY: [string, string][] = [
  ["Object", "Anything in orbit that we track: a working satellite, a dead satellite, a rocket body or a piece of debris."],
  ["Close approach (conjunction)", "A moment when two objects are predicted to pass closer than a chosen distance, for example 2 km."],
  ["TCA — time of closest approach", "The exact instant when the two objects are nearest to each other."],
  ["Closest distance (miss distance)", "How far apart the two objects are at that instant."],
  ["Speed between them (relative speed)", "How fast they move relative to each other — typically 7 to 15 km/s in low orbit, about 10× a rifle bullet."],
  ["Chance of collision (Pc)", "The probability that the objects actually hit. It needs to know how uncertain each position is; public tracking data does not include that, so for those passes ASTRAL shows only the distance."],
  ["Uncertainty data (covariance)", "A measure of how well each object's position is known. Operators share it in conjunction messages (CDMs)."],
  ["Manoeuvre / Δv", "A small push from the satellite's thrusters, measured as the change in speed in metres per second (m/s). 0.1 m/s is about walking pace."],
  ["Along-track, radial, cross-track", "The three directions of a push: forwards/backwards along the orbit, up/down away from Earth, and sideways."],
  ["TLE / orbital elements", "The standard public format that describes an orbit; CelesTrak publishes them daily for thousands of objects."],
];

const PAGES: { name: string; path: string; purpose: string; items: [string, string][] }[] = [
  { name: "At a glance", path: "overview", purpose: "The one-screen summary to start any demo.", items: [
    ["Four headline numbers", "How many objects are tracked, how many close approaches were found, the closest predicted pass, and how fresh the data is."],
    ["Track · Find · Act", "The three steps of the product, each linking to its page."],
    ["Closest passes", "The five tightest predicted passes, with links to their details and avoidance options."],
  ] },
  { name: "3D view", path: "environment", purpose: "See the problem: thousands of objects sharing the same space.", items: [
    ["The globe", "Earth turning in real time; each dot is a tracked object (bright = satellites, grey = debris)."],
    ["Play and speed", "Runs time forward at 60×, 300× or 1200× so orbits are visible."],
    ["Click a dot", "Follows that object and draws its orbit, with its altitude and speed."],
    ["Opened from a close approach", "Jumps to the moment of closest approach and highlights both objects."],
  ] },
  { name: "Close approaches", path: "encounters", purpose: "The list of every predicted close pass.", items: [
    ["The table", "One row per close pass: which objects, when (countdown), how close, and the collision-probability status."],
    ["How they pass each other", "A picture of the pass seen along the direction of approach: the gap between the dots is the closest distance."],
    ["Avoidance options strip", "Any manoeuvres already simulated for the selected pass."],
    ["Details page", "Distance-over-time chart (dips to the minimum at TCA), a 3D view of the fly-by, the chance of collision when it can be computed (or why not), and where every number came from."],
  ] },
  { name: "Avoidance manoeuvres", path: "scenarios", purpose: "Answer the question “what could the operator do?”.", items: [
    ["If nothing is done", "The predicted closest distance without any action — identical to the search result."],
    ["Predicted effect chart", "60 simulated pushes: 5 directions × 4 sizes × 3 timings. Each line is a direction; higher means the objects pass further apart; further right means more fuel."],
    ["When to fire", "Switch between firing half an orbit, one orbit or two orbits before the pass. Earlier pushes usually achieve more."],
    ["Most efficient options", "The three pushes that buy the most distance per m/s, written in plain words, with a button to check the new path against every other object."],
    ["Saved simulations", "Full checks: distance with and without the push, fuel (if mass is known) and whether the push creates any new close approach."],
  ] },
  { name: "Run a search", path: "screening", purpose: "Start a new analysis.", items: [
    ["New search", "Choose the data, the start time, how many hours ahead and the warning distance; the search runs in the background."],
    ["Searches list", "Progress of each search, with cancel and re-run."],
    ["Funnel chart", "How millions of possible pairs are narrowed down to the real close passes."],
    ["Check a conjunction message", "Computes the chance of collision when uncertainty data is provided."],
  ] },
  { name: "Charts", path: "analytics", purpose: "The results as pictures, each with a note on how to read it.", items: [
    ["When and how close", "Every close pass on a timeline; lower = closer."],
    ["Distance vs impact speed", "Bottom-right dots are the most serious: close and fast."],
    ["How fresh is the data", "Age of each object's orbit data; old data is less accurate."],
    ["Data quality checks", "Problems found when the data was loaded."],
    ["Position uncertainty / Speed of the search", "How well positions are known (when supplied) and how long searches take as the catalogue grows."],
  ] },
  { name: "Tracked objects · Data sources · Reports", path: "datasets", purpose: "Where the data comes from and what you can hand over.", items: [
    ["Tracked objects", "Searchable table of every object and its orbit."],
    ["Data sources", "Load public CelesTrak data or upload files; every record is checked and nothing is silently changed."],
    ["Reports", "PDF, spreadsheet (CSV) and JSON reports that state which data and software produced each result, so anyone can reproduce it."],
  ] },
  { name: "AI ranking (beta) · Settings", path: "ml", purpose: "Supporting features.", items: [
    ["AI ranking", "An experimental model that sorts close passes for review. It is not a collision probability and the physics works without it."],
    ["Settings", "System health, colour theme, accounts and the audit log of who did what."],
  ] },
];

const DEMO: [string, string][] = [
  ["At a glance", "“These are real objects from public data. The second number is how many pairs pass dangerously close in the next 24 hours; the third is the closest one.”"],
  ["3D view → Play", "“This is what low Earth orbit looks like — every dot is real. The grey ones are debris from three break-up events.”"],
  ["Close approaches → a row", "“Pick the top row: two objects passing a short distance apart at many km per second. The chart shows the distance dipping to its minimum at the moment of closest approach.”"],
  ["Avoidance manoeuvres", "“If one were a working satellite, what could it do? We simulate 60 small pushes. The chart shows which push buys the most distance for the least fuel — and one click checks it doesn't create a new risk.”"],
  ["Reports", "“Every result exports with its inputs and software versions, so anyone can reproduce it.”"],
];

export default function Guide() {
  const pid = useProjectId();
  return (
    <div className="page" style={{ maxWidth: 1100 }}>
      <PageHead eyebrow="How it works" title="A guided tour of ASTRAL">
        What the problem is, what ASTRAL does about it, and what every page and chart is for.
      </PageHead>

      <Panel title="The problem in one paragraph">
        <div className="panel-body" style={{ fontSize: 15, lineHeight: 1.6 }}>
          Tens of thousands of objects circle the Earth at around 7.5 km/s. When two of them pass too close, a collision would destroy both and create
          thousands of new fragments. Satellite operators must spot these close approaches days in advance and decide whether to move. ASTRAL does the
          spotting and helps with the deciding: it predicts every path, finds every close pass, and shows what small manoeuvres would change.
        </div>
      </Panel>

      <div className="grid cols-3">
        {[["1 · Track", "Load orbit data for satellites and debris (public CelesTrak data or your own files). Every record is checked."],
          ["2 · Find", "Predict where every object will be over the coming hours and list every pair that passes closer than a chosen distance."],
          ["3 · Act", "For any close pass, simulate small thruster pushes and see how far apart the objects would then pass."]].map(([t, d]) => (
          <div key={t} className="card"><h3>{t}</h3><span className="muted">{d}</span></div>
        ))}
      </div>

      <Panel title="Five-minute demo route">
        <ol style={{ margin: 0, padding: "calc(var(--d)*16px) 20px calc(var(--d)*16px) 40px", display: "flex", flexDirection: "column", gap: 10 }}>
          {DEMO.map(([step, say]) => <li key={step}><strong>{step}</strong> — <span className="muted">{say}</span></li>)}
        </ol>
      </Panel>

      {PAGES.map((p) => (
        <Panel key={p.name} title={p.name} meta={p.purpose} actions={<Link className="btn small" to={`/p/${pid}/${p.path}`}>Open</Link>}>
          <dl style={{ margin: 0, padding: "calc(var(--d)*14px) 20px", display: "grid", gridTemplateColumns: "minmax(160px, 260px) 1fr", gap: "10px 20px" }}>
            {p.items.map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt style={{ fontWeight: 600 }}>{k}</dt>
                <dd style={{ margin: 0 }} className="muted">{v}</dd>
              </div>
            ))}
          </dl>
        </Panel>
      ))}

      <Panel title="Words you will hear">
        <dl style={{ margin: 0, padding: "calc(var(--d)*14px) 20px", display: "grid", gridTemplateColumns: "minmax(160px, 260px) 1fr", gap: "10px 20px" }}>
          {GLOSSARY.map(([k, v]) => (
            <div key={k} style={{ display: "contents" }}>
              <dt style={{ fontWeight: 600 }}>{k}</dt>
              <dd style={{ margin: 0 }} className="muted">{v}</dd>
            </div>
          ))}
        </dl>
      </Panel>

      <Panel title="What ASTRAL does not claim">
        <div className="panel-body muted" style={{ lineHeight: 1.6 }}>
          Public orbit data is accurate to roughly a kilometre, so close passes found from it are warnings to investigate, not collision predictions.
          The chance of collision is only shown when uncertainty data is available. Manoeuvre results are simulations for discussion and never instructions to fly.
          ASTRAL is research software and has not been certified for operational use.
        </div>
      </Panel>
    </div>
  );
}
