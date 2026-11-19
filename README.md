# ⚡ Voltstream

[![ci](https://github.com/Malee-Fonseka/voltstream/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Malee-Fonseka/voltstream/actions/workflows/ci.yml)
![Python 3.11](https://img.shields.io/badge/python-3.11-blue)
![Kafka](https://img.shields.io/badge/Kafka-3.8-black)
![Spark](https://img.shields.io/badge/Spark-3.5-orange)
![Airflow](https://img.shields.io/badge/Airflow-3-017CEE)
![Docker Compose](https://img.shields.io/badge/run-docker%20compose-2496ED)

**Real-time grid monitoring and exact daily billing from one smart-meter stream.**
A Lambda-architecture data platform built for _Smart Grid Energy Monitoring & Billing_.

![Live grid dashboard](images/screenshots/dashboard.png)

<table>
<tr>
<td width="33%"><b>⚡ Live in seconds</b><br>Grid load and solar share per zone, about 6 s behind the meters.</td>
<td width="33%"><b>🧾 Exact bills, daily</b><br>The batch layer re-bills each closed day from the raw data with that day's tariff.</td>
<td width="33%"><b>🔔 Watched end to end</b><br>JSON logs, 10 metrics, 5 alert rules and 3 Grafana dashboards.</td>
</tr>
</table>

## Contents

1. [Architecture](#1-architecture)
2. [Quick start](#2-quick-start)
3. [The dashboard](#3-the-dashboard)
4. [Reproduce the results](#4-reproduce-the-results)
5. [Run the tests](#5-run-the-tests)
6. [Troubleshooting](#6-troubleshooting)
7. [Reference](#7-reference)

---

## 1. Architecture

Fifty simulated households report electricity use and rooftop solar every 2 seconds, and a
tariff file arrives once per simulated day. Two consumers need opposite things:

- **Grid operators** want load and renewable share per zone **within seconds**; an
  approximate answer now beats a perfect one later.
- **Billing** wants an **exact, auditable** bill per household per day, using that day's
  tariff and including late readings, which is only possible after the day closes.

A Lambda architecture serves both from one stream of readings: a fast path for "now", a slow
path for "exact", and one API that picks the better answer available.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/00-overview-dark.svg">
    <img src="docs/architecture/diagrams/00-overview-light.svg" alt="Smart meters send a reading every 2 seconds into one stream. A fast path adds them up within seconds using yesterday's prices, giving an estimate; every reading is also kept unchanged in a raw copy. When a day ends its price list arrives, and a slow path re-reads the whole day with the right prices, giving the exact bill. The API answers with the exact bill if it is ready, otherwise the estimate, and the dashboard badge flips from Provisional to Final.">
  </picture>
</p>

- The **speed layer** (Spark Structured Streaming) answers in seconds. It is deliberately
  approximate: it prices bills with yesterday's tariff and drops very late readings.
- The **batch layer** (Airflow + Spark) waits for the day to close, rescans the whole day
  from the immutable Parquet master dataset, applies that day's tariff and writes the final bill.
- The **API merges the two**: batch if the day is finalised, otherwise speed, and every
  response says which. The dashboard badge flips from **Provisional** to **Final**.
- **Reconciliation** explains the gap, split into a _tariff effect_ and a _data effect_.

Both layers import one shared billing module (`src/voltstream/core/`), and a consistency
test proves the pure-Python and Spark versions give identical bills.

**Simulated time:** one simulated day = **5 real minutes** (288× faster), starting at
2026-01-01 00:00 when the stack starts.

### How it works in detail

The picture above is all you need to run the project; the diagrams below are for reading the
code. They share one notation: **boxes** are services, **cylinders** are data stores, **pipes**
are Kafka topics, `[brackets]` give the technology, and **colour** gives the layer (amber =
speed, blue = batch, red = rejected or failed, dashed = never read).

**Containers and data flow.** The speed layer prices a day with the *previous* day's tariff
(`tariff D−1`); the batch layer waits for that day's own tariff (`tariff D`). Invalid readings
go to a rejects table and a dead-letter topic that nothing reads yet.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/01-data-flow-dark.svg">
    <img src="docs/architecture/diagrams/01-data-flow-light.svg" alt="meter-producer publishes readings to the Kafka topic meter.readings, which raw-archiver copies unchanged into Parquet in MinIO and speed-layer aggregates into provisional Postgres tables, rejecting bad records to rejected_records and a DLQ topic nothing consumes. When a day closes, reference-dropper's tariff file triggers the Airflow daily_billing DAG, which rescans the day from Parquet and writes the final bill tables. The API serves the batch bill if the day is finalised, otherwise the speed estimate.">
  </picture>
</p>

### One simulated day

Steps 1–6 run all day: readings flow in, and a bill request gets the speed layer's estimate.
At simulated midnight the day's tariff lands (7); Airflow notices it (8), waits 90 s for late
readings (9), rescans the day and commits the bills with a `success` row (10–11), or marks the
run failed and retries (12). From then on the same request returns the final bill (14).

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/02-day-sequence-dark.svg">
    <img src="docs/architecture/diagrams/02-day-sequence-light.svg" alt="Sequence of one simulated day lasting 300 real seconds: readings flow every 2 seconds from meter-producer through Kafka to raw-archiver and speed-layer, and a bill request gets the provisional speed row. At simulated midnight reference-dropper writes tariff_D.csv, Airflow's tariff_watcher triggers daily_billing within a minute, which waits 90 seconds for late readings, rescans the day and in one transaction replaces the bills and marks pipeline_runs success, or marks it failed and retries. From that commit on, the API serves the batch row as final.">
  </picture>
</p>

### The merge function

Every bill request goes through one decision: does `pipeline_runs` hold a `success` row for
this day? The ledger's states decide what the API serves, and why a final bill never reverts.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/03-bill-states-dark.svg">
    <img src="docs/architecture/diagrams/03-bill-states-light.svg" alt="Two state machines. A pipeline_runs row goes from running to success when finalise commits or to failed on an exception, and success becomes superseded only inside the transaction that commits a restatement. The bill for a household and day goes from 404 to provisional, served from household_running_rt priced with the previous day's tariff, to final, served from household_bill_daily, once a success row exists, and never goes back.">
  </picture>
</p>

### Bad, repeated and late readings

The producer injects six kinds of fault on purpose. The raw archiver keeps every record; each
layer then handles each fault differently, and the two differences that remain are exactly the
gap that reconciliation explains.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/04-fault-handling-dark.svg">
    <img src="docs/architecture/diagrams/04-fault-handling-light.svg" alt="Matrix of the injected faults against each layer. Null fields, negative kWh and unknown households are rejected by both layers, to rejected_records and, from the speed layer only, the DLQ topic. Out-of-order readings within 30 simulated minutes are counted by both, and duplicates are removed by both on meter_id and event_ts. Dropout backfill older than the watermark is lost by the speed layer but counted by the batch rescan, which is the data effect; pricing with the previous day's tariff is the tariff effect. Speed minus batch equals the sum of the two effects.">
  </picture>
</p>

The diagrams are generated: edit `scripts/gen_diagrams.py` and run
`python scripts/gen_diagrams.py`, which writes both the light and dark versions.

### Deployment

Containers start in four health-gated tiers under Docker Compose. Tier 4 also runs the
Pushgateway, `sql-exporter` and a Docker socket proxy (18 containers in all).

<p align="center">
  <img src="images/architecture/deployment.png" alt="Deployment tiers" width="720">
</p>

---

## 2. Quick start

**You need:** Docker Desktop with **at least 8 GB memory (10 GB recommended)** and 4+
CPUs, and Git (Git Bash on Windows). Ports 3000, 5432, 8000, 8011, 8012, 8080, 9000, 9001,
9090, 9091, 9093 and 29092 must be free.

```powershell
git clone https://github.com/Malee-Fonseka/voltstream.git
cd voltstream
.\scripts\voltstream.ps1 run        # Linux / WSL: make up
```

This builds the images, starts all 18 containers and waits for their health checks (first
build: several minutes; later starts: about a minute). `.env` is created from
`.env.example` automatically; nothing needs editing.

| What                      | URL                                                 | Login                                                          |
| ------------------------- | --------------------------------------------------- | -------------------------------------------------------------- |
| **Dashboard**             | <http://localhost:8000/>                            | none                                                           |
| API reference (OpenAPI)   | <http://localhost:8000/docs>                        | none                                                           |
| Grafana                   | <http://localhost:3000/>                            | none                                                           |
| Airflow                   | <http://localhost:8080/>                            | `admin`; password printed by `.\scripts\voltstream.ps1 status` |
| Prometheus / Alertmanager | <http://localhost:9090/> / <http://localhost:9093/> | none                                                           |
| MinIO console             | <http://localhost:9001/>                            | `voltstream` / `voltstream-dev`                                |

**What to expect:** live zone data within 20 s; day 1 billed about 8 minutes after start;
**day 2 (2026-01-02), the first complete day, billed and reconciled after about 13
minutes**. Then run `.\scripts\voltstream.ps1 check`; it should end with **0 failed**.
`LowRenewableContribution` firing every simulated night is expected (no sun).

| Windows                          | Linux / WSL                                                                | Effect                     |
| -------------------------------- | -------------------------------------------------------------------------- | -------------------------- |
| `.\scripts\voltstream.ps1 stop`  | `make down`                                                                | Stop, keep data            |
| `.\scripts\voltstream.ps1 start` | `docker compose --env-file .env -f docker/docker-compose.yml up -d --wait` | Resume on the same clock   |
| `.\scripts\voltstream.ps1 clean` | `make clean`                                                               | Delete containers and data |

<details>
<summary>Windows tips: giving Docker more memory, script permissions</summary>

Docker Desktop gets half the machine's RAM by default. For 10 GB, create
`C:\Users\<you>\.wslconfig` with:

```ini
[wsl2]
memory=10GB
```

then run `wsl --shutdown` and restart Docker Desktop. If PowerShell refuses to run the
script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

</details>

---

## 3. The dashboard

<http://localhost:8000/> refreshes every 5 seconds. Amber means speed layer / provisional,
teal means batch layer / final. Every chart has a table view (▦).

- **Live grid** (top of this page): load, solar, renewable share, active meters and
  speed-layer lag per zone, from 15-minute windows. Click a zone to focus on it.
- **Household bills**: one household's bill for one day, from whichever layer can answer,
  with the bill breakdown, energy flow, block tariff, estimate vs final and lineage.

| While the day is open: **Provisional (speed)**                          | After billing: **Final (batch)**                            |
| ----------------------------------------------------------------------- | ----------------------------------------------------------- |
| ![Provisional bill](images/screenshots/dashboard-bills-provisional.png) | ![Final bill](images/screenshots/dashboard-bills-final.png) |

- **Daily report**: everything known about one day: zone totals, rejected records by
  reason, speed-vs-batch divergence and every billing run.

![Daily report](images/screenshots/dashboard-report.png)

- **How it works**: an animated pipeline diagram and a guided tour of one reading.

---

## 4. Reproduce the results

Each script runs unattended and **undoes its own changes**, even on Ctrl+C. Let at least one
day be billed first (about 8 minutes after start).

| Scenario              | Windows (`.\scripts\voltstream.ps1 …`)                                 | Linux                        | Shows                                                      | Time     |
| --------------------- | ---------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------------- | -------- |
| Provisional → final   | `demo`                                                                 | `make demo`                  | The merge function flipping a bill from speed to batch     | ~7 min   |
| All five alerts       | `faults`                                                               | `make faults`                | Each alert fires under its fault, then clears              | ~30 min  |
| One alert             | `faults -Scenario stale` (`rejects`, `sla`, `renewable`, `divergence`) | `make faults s=stale`        | A single alert                                             | 3–17 min |
| Crash the speed layer | `killtest`                                                             | `make kill-test`             | Losing the speed layer costs freshness, never correctness  | 7–10 min |
| Restate a day         | `backfill -Date 2026-01-02`                                            | `make backfill d=2026-01-02` | A corrupted tariff fixed by recomputing, with history kept | 6–8 min  |

What each scenario does, step by step, and what it checks (✓ marks the script's own checks):

### Provisional → final (`demo`)

The same household's bill for the same day, asked for before and after the day is billed.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/06-scenario-demo-dark.svg">
    <img src="docs/architecture/diagrams/06-scenario-demo-light.svg" alt="While day D is open, the bill for HH-0001 comes from the speed layer, marked provisional and priced with the previous day's tariff, and the dashboard badge reads Provisional. At simulated midnight the day closes; within about two minutes the batch layer rescans it and commits the bills. The same request then returns the batch bill, marked final and priced with day D's tariff, the badge reads Final, and the delta endpoint splits the difference into a tariff effect and a data effect.">
  </picture>
</p>

### Crash the speed layer (`killtest`)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/07-scenario-kill-dark.svg">
    <img src="docs/architecture/diagrams/07-scenario-kill-light.svg" alt="The speed layer is killed for 60 seconds. The raw copy keeps receiving every reading, the live zone view goes stale, and an already billed day's bill is served unchanged. After a restart the speed layer re-reads from its checkpoint and catches up. When the day of the kill closes it is billed in full from the raw copy: 50 bills, with as many readings as the day before.">
  </picture>
</p>

### Restate a day (`backfill`)

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/08-scenario-restate-dark.svg">
    <img src="docs/architecture/diagrams/08-scenario-restate-light.svg" alt="A billed day's price list is corrupted and the day re-run: all 50 bills change, the original run becomes superseded and the new run success. The price list is restored and the day re-run again: all 50 wrong bills are replaced. The API serves only the latest run's bills, while the history table keeps all three sets and the run ledger keeps all three runs.">
  </picture>
</p>

### The five alert drills (`faults`)

Each drill breaks one thing, waits until Alertmanager shows the alert, then undoes it.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/09-scenario-drills-dark.svg">
    <img src="docs/architecture/diagrams/09-scenario-drills-light.svg" alt="Timeline of the five drills in real minutes. Stopping the meter producer fires MeterDataStale after about 3 minutes; 15 percent invalid readings fire HighRejectRate after about 2; LowRenewableContribution fires at simulated dusk within 7 minutes with no change at all; pausing the billing DAG fires BatchSLAMiss 15 minutes after the last billing; making 60 percent of readings hours late fires LambdaDivergenceHigh after 8 to 13 minutes.">
  </picture>
</p>

Where each alert gets its data, and where it ends up:

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/architecture/diagrams/05-alerting-dark.svg">
    <img src="docs/architecture/diagrams/05-alerting-light.svg" alt="Prometheus scrapes the services' metrics, a Pushgateway fed by exiting batch containers, and sql-exporter, which turns two Postgres queries into gauges. Five rules route through Alertmanager by severity, with MeterDataStale silencing LowRenewableContribution in the same zone, to a webhook on the API that writes one log line per alert; no email, chat or pager receiver is configured.">
  </picture>
</p>

| Alert                                | Fault                       | Fires after               |
| ------------------------------------ | --------------------------- | ------------------------- |
| `MeterDataStale` (critical)          | Meter producer stopped      | ~3 min                    |
| `HighRejectRate` (warning)           | 15% of readings invalid     | ~2 min                    |
| `BatchSLAMiss` (critical)            | Billing DAG paused          | 15 min after last billing |
| `LowRenewableContribution` (warning) | None: every simulated night | at dusk                   |
| `LambdaDivergenceHigh` (warning)     | 60% of readings very late   | 8–13 min (needs ~10 GB)   |

| Grafana: pipeline health                                                 | Prometheus: the five rules                                             |
| ------------------------------------------------------------------------ | ---------------------------------------------------------------------- |
| ![Pipeline health](images/screenshots/stale-grafana-pipeline-health.png) | ![Prometheus alerts](images/screenshots/rejects-prometheus-alerts.png) |
| **Alertmanager**                                                         | **Grafana: Lambda divergence**                                         |
| ![Alertmanager](images/screenshots/stale-alertmanager.png)               | ![Lambda divergence](images/screenshots/grafana-lambda-divergence.png) |

The batch layer in Airflow, `daily_billing`, with all eight tasks green:

![Airflow daily_billing DAG](images/screenshots/airflow-daily-billing.png)

**Query the API directly** (full reference at <http://localhost:8000/docs>; in PowerShell use `curl.exe`):

```bash
curl -s localhost:8000/api/v1/zones/load                                  # latest window per zone
curl -s "localhost:8000/api/v1/households/HH-0001/bill?date=2026-01-02"   # merged bill: see "source"
curl -s "localhost:8000/api/v1/reports/daily?date=2026-01-02"             # the daily report
```

---

## 5. Run the tests

Needs Python 3.11 and Java 17, not Docker:

```bash
python -m venv .venv                                   # Windows: py -3.11 -m venv .venv
.venv/bin/pip install -e ".[dev,api,sim,spark]"        # Windows: .venv\Scripts\pip ...
make test                                              # unit, property and consistency tests
```

`make coverage` adds CI's gate (`core/` at 100%), `make lint` runs ruff and mypy,
`make check-alerts` tests the alert rules with promtool, and `make test-all` adds the
integration tests (needs the stack running). CI runs lint, tests and alert checks on every
push.

---

## 6. Troubleshooting

| Symptom                                        | Fix                                                                                                   |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Start times out / a service is unhealthy       | `.\scripts\voltstream.ps1 status`, then `logs -Service <name>`. Usually Docker has too little memory  |
| Simulated dates far in the future              | The clock anchor in `.env` is stale: `clean`, then `run`. Never start with a bare `docker compose up` |
| After the laptop sleeps, `BatchSLAMiss` fires  | Expected (hours asleep are weeks simulated); clears after the next billing run                        |
| `check` fails during a billing run             | The laptop was briefly overloaded; re-run a minute later                                              |
| An alert in Grafana is missing in Alertmanager | It is inhibited by another alert; tick _Inhibited_                                                    |

---

## 7. Reference

| Service                                                                | Port                      | Role                                                                    |
| ---------------------------------------------------------------------- | ------------------------- | ----------------------------------------------------------------------- |
| `kafka`                                                                | 29092                     | Event log, 3 partitions, ~7 day retention                               |
| `postgres`                                                             | 5432                      | Serving layer: speed and batch views                                    |
| `minio`                                                                | 9000 / 9001               | Master dataset and landing zone (`pgsty/silo`, a MinIO-compatible fork) |
| `meter-producer`, `reference-dropper`                                  | —                         | The two simulated sources                                               |
| `raw-archiver`, `speed-layer`                                          | 8011, 8012                | Kafka → Parquet; live windows and provisional bills                     |
| `api`                                                                  | 8000                      | Serving API, merge function, dashboard                                  |
| `airflow` (+ `docker-socket-proxy`)                                    | 8080                      | Bills each day as its tariff lands                                      |
| `prometheus`, `alertmanager`, `pushgateway`, `sql-exporter`, `grafana` | 9090, 9093, 9091, —, 3000 | Monitoring and alerting                                                 |

| Looking for                                 | Start here                                                                                                            |
| ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Shared billing logic / layer agreement test | [src/voltstream/core/](src/voltstream/core/), [test_pure_vs_spark.py](tests/consistency/test_pure_vs_spark.py)        |
| Sources and ingestion                       | [simulators/](src/voltstream/simulators/), [streaming/](src/voltstream/streaming/)                                    |
| Batch layer                                 | [batch/](src/voltstream/batch/), [airflow/dags/](airflow/dags/)                                                       |
| Serving and the merge function              | [api/routers/households.py](src/voltstream/api/routers/households.py)                                                 |
| Observability                               | [metrics.py](src/voltstream/metrics.py), [config/prometheus/](config/prometheus/), [config/grafana/](config/grafana/) |

**Deliberately simplified:** 50 households, single-broker Kafka, single-node Spark, no
schema registry, secrets in `.env`. Time compression speeds up event time but not processing
time, so the live 15-minute view misses about 1% of energy that the batch layer still bills.
