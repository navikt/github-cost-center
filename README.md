# github-cost-dashboard

Internal Nav tool that maps GitHub billing costs to teams and seksjoner.

Upload a GitHub billing export and get a self-contained HTML dashboard showing costs per seksjon, per team, and per SKU — with drill-down and a gross/net toggle.

## How it works

```
GitHub billing export (.csv)
  └─ summarize_costs.py   group by month + repo + SKU
  └─ map_teams.py         repo → teamkatalogen ID via whodis
  └─ enrich_seksjon.py    teamkatalogen ID → team name + pa_seksjon via BigQuery
  └─ visualize.py         generate dashboard.html
```

Repo attribution works through [whodis](https://github.com/navikt/whodis), which maps a repository name to one or more teamkatalogen UUIDs. Those UUIDs are then joined against the `styring-av-sky-prod-77f0.teamkatalogen.team_productarea_nom` BigQuery view to get human-readable team names and which seksjon they belong to.

Costs with no repository (Copilot seats, GHEC/GHAS licences) are not a mapping failure — they are labelled by product (`copilot`, `ghec`, `ghas`) and reported as org-level spend. The dashboard's reconciliation ribbon shows what fraction of the bill is attributed to a seksjon vs org-level vs genuinely unknown.

## Running locally

### Prerequisites

- Python 3.13+
- `bq` CLI from the [gcloud SDK](https://cloud.google.com/sdk/docs/install)
- Access to whodis (or run it locally on port 8080)

### Setup

```bash
gcloud auth login --update-adc
gcloud config set project appsec-prod-624d
```

### Run

```bash
# 1. Download a billing export from:
#    https://github.com/enterprises/nav/billing/usage
#    (arrives by email as a .csv)

python3 summarize_costs.py export.csv --org navikt
# → by_month_repo_sku.csv

python3 map_teams.py by_month_repo_sku.csv --base-url http://localhost:8080
# → by_month_team_sku.csv
# caches to whodis_cache.json

python3 enrich_seksjon.py by_month_team_sku.csv
# → by_month_team_sku_named.csv, by_month_seksjon.csv, by_month_team_named.csv
# caches to teamkatalogen_cache.json

python3 visualize.py by_month_team_sku_named.csv
# → dashboard.html  (open directly in browser)
```

Caches are written to JSON files next to the scripts. Delete them to force a fresh lookup.

### Flags

| Script | Flag | Purpose |
|---|---|---|
| `summarize_costs.py` | `--org navikt` | Filter to one org (export covers all of `nav`) |
| `summarize_costs.py` | `--dayfirst` | If dates are D/M/YY rather than M/D/YY |
| `map_teams.py` | `--base-url` | whodis base URL |
| `map_teams.py` | `--allocation split\|duplicate\|first` | How to split cost when a repo belongs to multiple teams |
| `enrich_seksjon.py` | `--project` | GCP project to run the BQ job from |

## Deploying to NAIS

The app is a FastAPI service that accepts CSV uploads via a browser form, runs the pipeline in-process, and stores the generated dashboard in a GCS bucket. Subsequent visitors read the dashboard directly from GCS — no recomputation.

### Deploy

Push to `main`. The [deploy workflow](.github/workflows/deploy.yaml) builds and pushes the image with `nais/docker-build-push`, then deploys with `nais/deploy`.

The app will be available at `https://github-cost-dashboard.intern.nav.no` (Wonderwall-protected — nav.no accounts only).

### First run

Visit the app and you will be redirected to the upload page. Upload a billing export CSV. The pipeline runs in the background — with a full enterprise export this can take **5–15 minutes** (whodis lookups for ~2 000 repos, plus a BigQuery query). The upload form polls for completion and redirects automatically when done.

Subsequent uploads regenerate the dashboard. The **Bruk hurtigbuffer** checkbox skips fresh whodis and BQ calls and uses cached results from the previous run — faster, but may return stale team mappings.

### Configuration (`nais.yaml`)

| Env var | Default | Purpose |
|---|---|---|
| `GCS_BUCKET_NAME` | `github-cost-dashboard-appsec` | Bucket for caches and the dashboard HTML |
| `WHODIS_BASE_URL` | `http://whodis` | whodis service URL inside the cluster |
| `BQ_PROJECT` | `appsec-prod-624d` | GCP project used to run BQ queries |
| `GITHUB_ORG` | `navikt` | Which org to filter the export to |

GCS access is handled via Workload Identity — no service account key needed.

## Cost buckets

Not all spend can be attributed to a team via repositories. The dashboard separates three classes:

| Class | Meaning |
|---|---|
| **På en seksjon** | Mapped through whodis + teamkatalogen |
| **Org-nivå** | No repository exists to map on (`copilot`, `ghec`, `ghas`). Labelled by product |
| **Ukjent** | A mapping problem — see below |

Ukjent sub-buckets:

| Bucket | Meaning |
|---|---|
| `(no team)` | whodis returned no team for the repo. The team table lists which repos — these are the ones to fix in teamkatalogen |
| `(whodis lookup failed)` | Transport error. Re-upload to retry |
| `(id not in teamkatalogen)` | whodis returned a UUID the BQ view does not have. Likely a deleted team |
| `(team has no pa_seksjon)` | Team joined, but `pa_seksjon` is null |

## gross vs net

The dashboard shows both `gross` (usage before the included free allowance) and `net` (what GitHub actually charges). If `net` is a small fraction of `gross`, cost per team in net terms reflects who ran jobs after the org's free quota was exhausted — a calendar artifact, not a fair signal. Use `gross` for internal chargeback.

## Data sources

| Source | What it provides |
|---|---|
| [github.com/enterprises/nav/billing/usage](https://github.com/enterprises/nav/billing/usage) | Billing export CSV |
| [whodis](https://github.com/navikt/whodis) | `GET /repository/{repo}` → `[teamkatalogenId, ...]` |
| `styring-av-sky-prod-77f0.teamkatalogen.team_productarea_nom` | teamkatalogenId → team name, teamType, pa_seksjon |