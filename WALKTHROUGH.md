# ASTRAL — Walkthrough and pitch guide

A plain-language tour of the web application: what each page and chart does, how to read it, and a five-minute demo route. The same content is in the app under **How it works**.

---

## 1. The idea in 30 seconds

> Tens of thousands of objects orbit the Earth at about 7.5 km/s — working satellites, dead satellites, rocket bodies and debris. When two pass too close, a collision would destroy both and create thousands of new fragments. ASTRAL **tracks** these objects using real public data, **finds** every pair that will pass dangerously close in the coming hours, and lets an operator **test small avoidance manoeuvres** to see how much each would widen the gap.

Three verbs carry the whole pitch: **Track → Find → Act.**

---

## 2. Five-minute demo route

| # | Click | What to say |
|---|---|---|
| 1 | **At a glance** | "These are real objects from public tracking data. The second number is how many pairs pass dangerously close in the next 24 hours. The third is the closest one, and when it happens." |
| 2 | **3D view** → **Play** | "This is low Earth orbit. Every dot is a real object; the grey ones are debris from three break-up events. Speed 300× means one orbit in about 20 seconds." Click a dot: "We can follow any object and see its altitude and speed." |
| 3 | **Close approaches** → top row | "Each row is a predicted close pass. Here two objects pass a few hundred metres apart at around 14 km/s — ten times faster than a rifle bullet." Open **Details**: "The distance dips to its minimum at the moment of closest approach." |
| 4 | **Avoidance manoeuvres** | "What could an operator do? ASTRAL simulates 60 small pushes: 5 directions, 4 sizes, 3 timings. The chart shows which push buys the most distance for the least fuel." Click **Check against all other objects**: "In a few seconds it re-checks the new path against all ~2,800 other objects, so we don't swap one risk for another." |
| 5 | **Reports** | "Every result exports with the data and software versions that produced it, so anyone can reproduce it." |

Before the demo, open **At a glance** once so the pages are warm.

---

## 3. Page by page

### At a glance
| Element | What it shows | How to read it |
|---|---|---|
| **Objects tracked** | Number of satellites and debris in the latest data | Bigger = more of the sky covered |
| **Close approaches found** | Pairs predicted to pass closer than the search distance (e.g. 2 km) in the search window (e.g. 24 h) | Each one is a warning to look at |
| **Closest predicted pass** | The tightest pass and when it happens | The headline risk right now |
| **Data age** | Time since the orbit data was loaded | Fresh data = more trustworthy predictions |
| **Track · Find · Act** | The three steps, each linking to its page | The story of the product |
| **Closest passes table** | The five tightest passes | *Details* opens the analysis; *Avoidance options* opens the manoeuvre page |

### 3D view
| Element | What it shows | How to read it |
|---|---|---|
| Globe | The Earth turning in real time | Continents line up with the true time of day |
| Dots | Tracked objects (bright = satellites, grey = debris) | Clusters show crowded orbits |
| **Play / Speed** | Time moving forward at 60×, 300× or 1200× | Watch orbits sweep around the planet |
| **Objects shown** | 250 / 500 / 1000 dots | Fewer dots = smoother; the search always uses every object |
| Click a dot | Follows it, draws its orbit, shows altitude and speed | — |
| Opened from a close approach | Jumps to that moment; both objects highlighted | See where on Earth the pass happens |

### Close approaches
| Element | What it shows | How to read it |
|---|---|---|
| Table | One row per close pass: objects, when (countdown), distance, probability status | Sort by *Soonest* or *Closest* |
| "Probability: needs uncertainty data" | The chance of collision can't be computed from public data | Public data has no error bars, so only distance is shown. This is honest, not a gap. |
| **How they pass each other** | The pass seen along the direction of approach | White dot = first object, red dot = where the second passes; the gap is the closest distance |
| **Details** page → **Distance over time** | Distance between the two objects in the minutes around the pass | The red line dips to its minimum at the dashed line (closest approach). The other lines split it into up-down, ahead-behind and sideways. |
| **The pass in 3D** | The second object's path as it flies past the first | Drag to rotate; the yellow dot marks the closest point |
| **Chance of collision** | Probability, when uncertainty data is supplied (conjunction messages) | Otherwise it lists exactly which inputs are missing |
| **Where these numbers come from** | Data version, prediction method, data age | Traceability: anyone can check the inputs |

### Avoidance manoeuvres (the manoeuvre prediction section)
| Element | What it shows | How to read it |
|---|---|---|
| **If nothing is done** | The closest distance with no action | Same number as the search found |
| **One orbit takes** | Time for one lap of the Earth (~100 min in low orbit) | Burns are timed in orbits before the pass |
| **When to fire** | ½, 1 or 2 orbits before the pass | Times already in the past are marked *too late* and excluded |
| **Predicted effect chart** | Closest distance (up) against size of push (right), one line per direction | Lines that climb steeply buy the most distance per unit of fuel. Red dashed line = no manoeuvre. |
| **Most efficient options** | The three pushes with the most extra distance per m/s, in words | e.g. "Speed up by 0.2 m/s, one orbit before → distance grows from 0.09 km to 1.6 km" |
| **Check against all other objects** | Re-runs the chosen push against every tracked object | Confirms the new path doesn't create a new close pass; saves the result |
| **Saved simulations** | Distance without and with the push, speed change, fuel (if mass given), new close passes caused | The "Read this as" box states the outcome in one sentence |
| **Try your own manoeuvre** | Expert form for any direction, size and timing | — |

**Why speeding up or slowing down works best (for questions):** a small change in speed changes the orbit's period, so the satellite arrives at the crossing point slightly earlier or later. That timing offset grows every orbit, so earlier burns give a bigger effect for the same fuel. Pushing outward or inward changes altitude, which helps most about half an orbit later. Sideways pushes mostly tilt the orbit and do little for most passes.

**If the moving object is debris:** debris can't manoeuvre. The page says so and frames the options as "what a working satellite in that position could do".

### Run a search
| Element | What it shows |
|---|---|
| **New search** | Choose data, start time, hours ahead and warning distance; runs in the background |
| **Searches** list | Progress, cancel, re-run with identical inputs |
| **Funnel chart** | How millions of possible pairs are narrowed down: pairs whose altitudes never overlap are dropped, then pairs that never get near each other, leaving the real close passes |
| **Check a conjunction message** | Computes the chance of collision when operators supply uncertainty data |

### Charts
| Chart | What it shows | How to read it |
|---|---|---|
| **When and how close** | Every close pass on a timeline | Lower dots = closer passes; clusters = busy periods |
| **Distance vs impact speed** | Closeness against relative speed | Bottom-right = most serious (close *and* fast) |
| **How fresh is the data** | Age of each object's orbit update | Most bars should be on the left; >3 days is flagged stale |
| **Data quality checks** | Problems found when loading data | Red = record not used; yellow = warning |
| **Position uncertainty** | How well positions are known (when supplied) | Smaller = better known |
| **Speed of the search** | Search time as the catalogue grows | ~2,000 objects in about 12 s on a laptop |

### Tracked objects · Data sources · Reports · AI ranking · Settings
- **Tracked objects** — searchable list with altitude range, tilt, time per orbit and data age.
- **Data sources** — load public CelesTrak data or upload files; every record is checked and nothing is silently changed.
- **Reports** — PDF, spreadsheet (CSV) and JSON, each stating its inputs and software versions.
- **AI ranking (beta)** — an experimental model that orders close passes for review. It is *not* a collision probability; the physics works without it.
- **Settings** — system health, colour theme, accounts and an audit log of who did what.

---

## 4. Questions the jury may ask

| Question | Honest answer |
|---|---|
| Is the data real? | Yes. Objects come from CelesTrak, the public catalogue built on US Space Force tracking, refreshed before the demo. The second project uses sample conjunction messages so we can show the probability calculation, which needs uncertainty data that public catalogues don't publish. |
| How accurate are the predictions? | Public orbit data is accurate to about a kilometre and degrades with age, so close passes are warnings to investigate, not collision predictions. Our prediction code reproduces the official SGP4 reference test set to better than 1 mm. |
| Why no collision probability on most passes? | It needs to know how uncertain each position is. Public data doesn't include that, so we refuse to invent a number. With operator data (conjunction messages) it is computed. |
| Would you really tell an operator to fire? | No. Manoeuvre results are simulations to support a decision by qualified engineers. Every result is labelled that way. |
| How fast is it? | A 24-hour search over ~2,800 real objects takes about a minute on a laptop. A manoeuvre check against all objects takes about 12 seconds. |
| How do you know it doesn't miss a close pass? | The search uses a mathematical bound that guarantees no pass below the threshold is skipped, and we verify it against brute-force second-by-second checks in our tests. |
| What's next? | Uncertainty propagation, comparison with NASA's reference tools, and integrating operator data feeds. |

---

## 5. Glossary

| Term | Meaning |
|---|---|
| Close approach / conjunction | Two objects predicted to pass closer than a chosen distance |
| TCA | Time of closest approach — the instant they are nearest |
| Miss distance | How far apart they are at TCA |
| Relative speed | How fast they move relative to each other |
| Pc | Probability of collision |
| Covariance | Uncertainty data: how well each position is known |
| Δv (delta-v) | Change in speed from a thruster burn, in m/s |
| Along-track / radial / cross-track | Forwards-backwards / up-down / sideways relative to the orbit |
| TLE | Standard public format describing an orbit |
| CDM | Conjunction Data Message — an operator's warning that includes uncertainty |

---

## 6. Checklist for the morning of the pitch

1. Refresh the real data so passes are in the future (needs internet, about 1–6 minutes). If the data was downloaded less than 2 hours ago, CelesTrak asks us not to re-download it, so the command keeps it and simply re-runs the search from the current hour:
   ```bash
   cd backend
   .venv/Scripts/python -m astral.cli seed-live --email admin@astral.test --project 1
   ```
2. Start the API and the website:
   ```bash
   cd backend && .venv/Scripts/python -m uvicorn astral.main:app --port 8000
   ```
   ```bash
   cd frontend && npm run dev
   ```
3. Open <http://localhost:5173>, sign in (credentials in `backend/data/dev-credentials.txt`) and click through the five demo steps once.
4. Keep the **How it works** page ready as a fallback explanation.
