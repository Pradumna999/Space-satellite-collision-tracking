# User guide

## 1. Projects
Sign in, then create a project or open an existing one ("Low Earth Orbit — public catalogue" holds real CelesTrak data; "Covariance & manoeuvre studies" holds sample conjunction messages with covariance). Owners add members as viewer (read-only), analyst (upload, analyse, simulate) or owner (also manage members) in **Administration → Project members**.

## 2. Upload data (07 Datasets & uploads)
Drop a TLE, OMM, OEM, CDM or `astral-states` CSV/JSON file; the format is detected automatically or can be chosen. ASTRAL stores the original file unchanged, validates every record and creates **version 1** of the dataset. Review the findings table (filter by severity) and download the validation report CSV.
* *needs review*: some records have errors (they are excluded). Click **Approve for analysis** to continue with the rest.
* *Proposed corrections* (e.g. excluding duplicates, nearest-PSD covariance) are never applied automatically. Approving one creates a new version.
* Optionally fetch public GP data from CelesTrak (marked as provider data, not authoritative).

## 3. Screen (04 Conjunction screening)
Choose a dataset version (GP elements or ephemerides), the window start (UTC), duration, grid step and threshold, and optionally primary objects. **Run screening** submits a background job; progress, cancellation, warnings and the screening funnel appear in the job panel. For CDMs, use **Re-assess CDM** with a hard-body radius to compute Pc (optional Monte Carlo cross-check). The 3D method is not implemented.

## 4. Investigate (05 Encounter investigations)
The analysis workspace lists encounters with TCA countdown, miss distance and probability status. Click a row to see its encounter-plane geometry (covariance ellipses only when covariance exists). Double-click, or use *investigate*, for the full view: relative-motion chart (CSV export), 3D relative trajectory, Pc details or the reasons Pc was not computed, provenance (propagators, data ages, hashes), flags, analysis history and CDM export.

## 5. Visualise (03 3D environment)
Select a dataset version and press **Play**. Positions are propagated by the backend for a 3-hour window in one request and animated in the browser at 60×, 300× or 1200×; the next window loads automatically before the current one ends. Choose how many objects to draw (250 / 500 / 1000; satellites first, then an even sample of debris) — screening always uses every object. Click an object to follow it and see its orbit; opening from an encounter jumps to TCA and highlights both objects.

## 6. Analytics (06)
Encounter timeline and miss-vs-speed scatter (click a point to select), data freshness, validation findings, covariance diagnostics and benchmark runtime. Every chart states its units, time convention, source and data kind, and exports CSV.

## 7. Scenarios (09)
Pick a screening encounter, define an impulsive Δv (RTN) and burn time, optionally the mass and Isp, and confirm. The result compares baseline and alternative miss distances under the same J2 model, lists other encounters of the new trajectory and states all warnings. Simulation only: it is never a recommendation.

## 8. Reports (10)
Generate PDF, CSV or JSON reports for any completed analysis. They include hashes, configuration, software versions, results, data quality, limitations and reproducibility information. Compare two runs to see matched encounters, miss changes and whether inputs, configuration or software differ.

## 9. ML laboratory (08)
Inspect experimental models: metrics against the rule baseline, PR and calibration curves, confusion matrix and provenance. Admins can train and activate a model; scores then appear as "ML priority (experimental)". They are never probabilities.

## 10. Settings (11 Administration)
System health, appearance (pairing D Ignition / E Kyoto, dark/light, density, font set, accent hue), API tokens, members; for admins also accounts and the audit log.
