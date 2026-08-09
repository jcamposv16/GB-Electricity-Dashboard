
# GB Electricity Dashboard

An interactive analytics platform for the Great Britain electricity market, covering generation mix, cross border interconnector flows, wholesale prices and regional carbon intensity from 2020 to the present.

**[View the live dashboard on Hugging Face Spaces](https://huggingface.co/spaces/jcamposv16/gb-electricity-dashboard)**

Built with Streamlit, SQLite and Plotly, fed by a scheduled ETL pipeline that pulls from Elexon BMRS, the NESO SQL API, Nord Pool N2EX and the Carbon Intensity API.

---

## Contents

- [What this project does](#what-this-project-does)
- [Dashboard pages](#dashboard-pages)
- [Data sources](#data-sources)
- [Data model and aggregation logic](#data-model-and-aggregation-logic)
- [Data quality notes and known limitations](#data-quality-notes-and-known-limitations)
- [Architecture](#architecture)
- [Deployment](#deployment)
- [Engineering notes](#engineering-notes)
- [Tech stack](#tech-stack)
- [Running locally](#running-locally)

---

## What this project does

The GB electricity system publishes a large volume of operational data across several public APIs, but each source covers a different slice of the picture and none of them answers analyst questions directly. Elexon reports metered generation by fuel type at half hourly resolution but excludes most embedded solar and wind. NESO covers embedded generation but with a different schema. Prices, interconnector flows and carbon intensity each live somewhere else again.

This project consolidates those sources into a single dimensional store and presents them through seven analytical views. The emphasis is on making the data comparable rather than simply plotting it: reconciling fuel taxonomies across providers, deriving consistent share denominators, and being explicit where a source is a proxy rather than the real measurement.

Six years of history are held at daily, monthly and quarterly resolution, with a rolling ninety day window at native half hourly resolution.

---

## Dashboard pages

### 1. Generation by fuel type

Generation output broken down across the ten primary fuel types, with four linked views: a stacked area chart of absolute output, a hundred percent stacked area of share, individual fuel lines with a dashed system total, and per fuel share lines.

Selectable at half hourly, daily or monthly resolution with a configurable date range. Half hourly views are bounded to the available ninety day window; daily and monthly reach back to 2020.

**Answers:** how has the fuel mix shifted over a given period, both in absolute terms and as a share of the system.

### 2. Interconnector flows

Cross border flows across the ten interconnectors linking GB to France, Norway, the Netherlands, Belgium, Denmark, Ireland and Northern Ireland.

Opens with three KPI cards showing current net position, largest import and largest export. Below that, a per cable trend chart and a diverging stacked bar view with a net imports overlay.

The page then splits the fleet into three behavioural groups, which is where the analytical interest sits:

| Behaviour | Cables |
|---|---|
| Unidirectional into GB | Eleclink (FR), IFA1 (FR), IFA2 (FR), North Sea Link (NO) |
| Unidirectional out of GB | East West (IE), Greenlink (IE), Moyle (NI) |
| Cycling | BritNed (NL), Nemo Link (BE), Viking Link (DK) |

**Answers:** which markets GB is importing from and exporting to, and whether a given cable behaves as steady one way transfer or reverses with price spreads.

### 3. Generation flow

A live animated flow diagram of the grid for the most recent settlement period, rendered as custom SVG rather than a charting library. Nodes cover BM generation, embedded wind, solar, pumped storage, imports and exports, with flow line thickness scaled to magnitude.

Refreshes automatically every sixty seconds.

**Answers:** where GB electricity is coming from and going to right now, as a single readable snapshot.

### 4. Generation by main fuel group

The same underlying data as page one, consolidated from ten fuel types into five groups: Nuclear, Renewables, Imports, Gas and Coal. Same four chart views and the same granularity controls.

**Answers:** the high level system picture without the detail of individual fuels, useful for spotting structural trends rather than short term switching.

### 5. Quarterly analysis

A dense quarterly summary table covering generation and share by fuel and by group back to 2020, alongside derived metrics for fossil, clean and renewable share of consumption. A selectable quarter is highlighted for comparison. Below the table, two stacked area charts show quarterly trends by fuel type and by fuel group in TWh.

**Answers:** long run structural change in the generation mix at the resolution most commonly used in market reporting.

### 6. Comparison analysis

Year on year comparison across three configurable years, restricted to complete months so partial periods never distort a comparison.

Three sections:

- **Fuel comparison.** Monthly generation in TWh and monthly share for solar, wind and gas.
- **Renewables supply.** Monthly renewable generation and its share of total generation per selected year.
- **Price analysis.** GB Market Index Price (Elexon MID) plotted against Nord Pool N2EX day ahead prices at monthly, daily and half hourly resolution, with a parallel view of gas, solar and wind generation share over the same intervals.

**Answers:** how renewable output varies between years, and how wholesale prices move against the generation mix at the point of dispatch.

### 7. Carbon intensity

A live Leaflet map of the fourteen DNO regions coloured by carbon intensity in gCO₂/kWh, with interconnector routes and animated flow indicators overlaid. A ranked table lists regions from cleanest to most carbon intensive with the current index band.

Refreshes every thirty minutes from the Carbon Intensity API.

**Answers:** which parts of the country currently have the cleanest electricity, and the regional generation mix behind each figure.

---

## Data sources

All endpoints are public and require no authentication.

| Source | Endpoint | Supplies |
|---|---|---|
| Elexon BMRS | `/bmrs/api/v1/datasets/FUELHH` | Half hourly metered generation by fuel type, plus the ten interconnector columns. Historical backfill from 2020. |
| Elexon BMRS | `/bmrs/api/v1/datasets/MID` (`dataProviders=APXMIDP`) | Half hourly market index price and traded volume from 2020. |
| Elexon BMRS | `/bmrs/api/v1/generation/outturn/interconnectors` | Live per cable interconnector flows. |
| NESO | `/api/3/action/datastore_search_sql` | Embedded and non BM generation: biomass, wind, embedded wind, nuclear, solar. |
| Carbon Intensity API | `/intensity`, `/regional`, `/regional/intensity/{from}/{to}` | National and regional carbon intensity, live and historical. |
| Nord Pool | N2EX day ahead auction data | Day ahead cleared prices, loaded from published files. |

Elexon's FUELHH dataset caps each request at a seven day window, so historical backfill is paginated. The generation mix is not available from a single source: FUELHH is pivoted from long to wide format and inner joined to the NESO extract on settlement timestamp, because Elexon covers BM metered plant while NESO covers embedded generation that never appears in the balancing mechanism.

---

## Data model and aggregation logic

The store is SQLite, organised as raw half hourly tables with pre computed aggregates layered above them.

### Raw tables

| Table | Contents |
|---|---|
| `raw_generation_mix` | Half hourly MW and percentage by fuel type |
| `raw_interconnector` | Half hourly flow in MW per cable, signed by direction |
| `raw_electricity_price` | Half hourly MID price and volume per settlement period |
| `raw_nordpool_n2ex` | Half hourly Nord Pool N2EX day ahead price |

### Aggregate tables

Daily, monthly and quarterly aggregates exist for generation, interconnectors and prices, plus a settlement period price profile. These hold the full history back to 2020 and are never trimmed.

### Derivation

Energy is derived from instantaneous power by settlement period length:

```
total_mwh = SUM(mw) * 0.5
```

Each raw sample represents a thirty minute settlement period, hence the factor of 0.5.

Share is computed against a denominator restricted to the primary fuel tier:

```
total_percent = ROUND(fuel_mwh / period_total_mwh * 100, 2)
```

### Avoiding double counting

The raw tables store sub components alongside their totals: `wind_bm` and `wind_emb` sum to `wind`, and `ccgt` and `ocgt` sum to `gas`. Including both levels in an aggregate would count the same electricity twice, so every aggregate and every share denominator applies a primary tier filter:

```sql
WHERE fuel_type NOT IN ('wind_bm', 'wind_emb', 'ccgt', 'ocgt')
```

The sub components remain in the raw tables for analysis that needs the split.

### Pumped storage handling

Pumped storage carries a negative MW value while charging, since it is consuming grid electricity to pump water uphill rather than generating. Summing that signed value into a group total would understate renewable output during charging periods.

Every path that rolls pumped storage into a group total clips it at zero first. The signed value is still shown as is on the individual pumped storage line, where the charging behaviour is the point of interest.

### The ten primary fuels and five groups

| Fuel | Group |
|---|---|
| nuclear | Nuclear |
| wind, solar, hydro, pumped storage, biomass, other | Renewables |
| imports | Imports |
| gas | Gas |
| coal | Coal |

---

## Data quality notes and known limitations

These are documented deliberately. Treating a proxy as though it were the real measurement is a more serious error than the gap it papers over.

**Elexon MID is a proxy for day ahead price, not a substitute.** MID is an intraday volume weighted index reflecting trades close to delivery, whereas a day ahead auction price is set the previous day. They correlate but they are not the same signal, and they diverge under system stress. MID is used because complete historical GB day ahead auction data is commercially licensed. It is labelled as a distinct named series throughout the dashboard rather than presented as day ahead price.

**Nord Pool N2EX coverage is partial.** Free access to N2EX day ahead data is limited to short rolling windows, so the series available here is recent rather than complete. It is plotted alongside MID rather than merged into it.

**ENTSO-E is not usable for GB.** The ENTSO-E Transparency Platform lost GB coverage after Brexit removed the reporting obligation, which rules out the route most European market dashboards take.

**No spline smoothing.** All time series connect measured points with straight segments. Spline interpolation between monthly or half hourly observations implies intermediate values that were never measured, which is misleading in a chart intended to represent metered data.

**Complete months only in year on year comparisons.** Partial months are excluded from the comparison page so a month in progress never appears as a decline against the same month in a prior year.

**Deployed data is a periodically refreshed snapshot.** The live Space is updated daily rather than streaming in real time. The sidebar shows the coverage timestamp so the age of the data is always visible.

**Half hourly retention is bounded.** The deployed database holds ninety days of raw half hourly data. Daily, monthly and quarterly aggregates cover the full period from 2020. This keeps the deployed artefact small enough to update frequently while preserving all long run analysis.

---

## Architecture

```
Elexon BMRS ─┐
NESO SQL API ─┼─> ETL pipeline ─> CSV ─> SQLite (full history, ~845 MB)
Nord Pool ────┤                                      │
Carbon API ───┘                                      │
                                                     v
                                          trim to 90 day window
                                          rebuild as ~29 MB artefact
                                                     │
                                                     v
                                          Hugging Face Space
                                          (Streamlit, auto restart)
```

The local store holds the complete history: roughly 2.7 million half hourly rows across generation and interconnectors going back to 2020, at around 845 MB. That is the analytical source of truth and it never leaves the local machine.

The deployed artefact is a derived subset. A scheduled job copies the local database, deletes raw rows older than the retention window, drops tables no page reads, and vacuums the result down to about 29 MB. All aggregate tables are copied intact, so six years of daily, monthly and quarterly history survive the trim untouched.

The size reduction is what makes frequent updates practical. A 29 MB artefact uploads in a few seconds; the full database would take minutes and make daily refresh impractical.

---

## Deployment

The daily refresh runs as a scheduled task and completes in roughly fifteen seconds end to end:

1. **Copy.** The live local database is copied to a temporary file. The source is never opened for writing, so a fault in the trim can never damage the analytical store.
2. **Trim.** Raw rows outside the retention window are deleted, unused tables are dropped, WAL is checkpointed and the journal mode is reset, then the file is vacuumed.
3. **Verify.** Fifteen assertions run before anything is uploaded: the file is smaller than the source but above a minimum size, every aggregate table still exists and is populated, the daily aggregate still holds its expected row count, and the journal mode is confirmed reset. Any failure aborts the run without uploading.
4. **Upload.** The verified artefact is pushed to the Space via the Hugging Face API.
5. **Restart.** The Space is restarted programmatically so it never continues serving from a database file that was replaced underneath the running process.

Every step is logged to an append only file with timestamps and per assertion results, so a failed run is diagnosable after the fact rather than silently stale.

---

## Engineering notes

Deploying a SQLite backed Streamlit application to a containerised platform surfaced three distinct failures, none of which reproduced locally. They are recorded here because the diagnosis is more interesting than the code.

**Write ahead logging on container storage.** The database shipped with `journal_mode=WAL`, which is a property of the file rather than the connection. WAL requires memory mapping a shared index file alongside the database for every connection, readers included. On the platform's storage layer this produced native crashes rather than catchable exceptions. Since the deployed application never writes to the database, WAL provided nothing. The upload step now checkpoints and resets the journal mode before shipping, and connections open read only.

**Chunked object storage under SQLite.** The platform serves large files through a content addressed store that fetches in chunks over the network on access. SQLite assumes a local disk and seeks freely through the file, so queries reaching cold regions surfaced as `disk I/O error`. The fix was to copy the database to local container storage once at startup, before any connection opens, and resolve every connection through that path.

**Native crash in the Arrow string backend.** After both storage issues were resolved, the process continued dying silently after several interactions, with no Python traceback. Enabling `faulthandler` produced a stack dump on the next crash that located it precisely: a segmentation fault inside pandas 3's Arrow backed string conversion, triggered by an ordinary DataFrame construction. Pandas 3 made Arrow backed strings the default, and the deployed combination of pandas 3.0 with pyarrow 25 was not stable on that platform. Pinning pandas 2.2.3 with pyarrow 18.1.0 resolved it.

The common thread is that all three were native level failures in an environment that differed from the development machine in ways not visible from the application code. Each was found by instrumenting the deployed process rather than by inspection.

---

## Tech stack

| Layer | Technology |
|---|---|
| Application | Streamlit 1.58 |
| Visualisation | Plotly 6.8, Leaflet, custom SVG |
| Data processing | pandas 2.2.3, pyarrow 18.1.0 |
| Storage | SQLite |
| Deployment | Hugging Face Spaces, Git LFS |
| Automation | Python, Windows Task Scheduler, `huggingface_hub` API |

---

## Running locally

```bash
git clone https://github.com/jcamposv16/GB-Electricity-Dashboard.git
cd GB-Electricity-Dashboard

python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
streamlit run app.py
```

The repository includes a database snapshot, so the dashboard runs immediately without any ETL step.

---

## Repository structure

```
app.py                    Entry point, navigation and theme
navigation.py             Page registration
components/
  charts.py               Plotly chart builders and fuel grouping
  sidebar.py              Navigation rendering
data/
  cache_db.py             SQLite access layer and API fetchers
  csv_to_sqlite.py        CSV to dimensional model loader
  fetcher.py              Cached query interface
pages/                    The seven dashboard pages
utils/                    Comparison, quarterly and date window helpers
styles/theme.py           Design system and fuel colour palette
reference/                DNO region and interconnector geometry
cache/grid_cache.db       Database snapshot
```
