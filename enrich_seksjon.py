#!/usr/bin/env python3
"""
Enrich team costs from teamkatalogen (BigQuery) and roll up per seksjon.

    python3 enrich_seksjon.py by_month_team_sku.csv --project <gcp-project>

Writes:
    by_month_team_sku_named.csv   the full grain -- feeds the dashboard
    by_month_seksjon.csv          rollup, month x seksjon
    by_month_team_named.csv       rollup, month x team

Uses the `bq` CLI from the gcloud SDK, so it reuses your existing gcloud auth
and needs no python BigQuery client. Run once:

    gcloud auth login --update-adc
    gcloud config set project <gcp-project>

Rows with an empty teamkatalogen_id are org-level spend (Copilot seats,
GHEC/GHAS licences). They are labelled by product -- "copilot", "ghec",
"ghas" -- so the bill shows what they cost rather than hiding them in a
single unmapped bucket.

Rows that could not be mapped are named after the repo, not the bucket, so the
team list under "(no team)" tells you which repos to go and fix.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

TABLE = "styring-av-sky-prod-77f0.teamkatalogen.team_productarea_nom"

# Emitted by map_teams.py in place of a real team id. Not UUIDs, will not join.
SENTINELS = {"(no team)", "(whodis lookup failed)"}
NOT_IN_TK = "(id not in teamkatalogen)"
NO_SEKSJON = "(team has no pa_seksjon)"

MONEY = ("quantity", "gross_amount", "discount_amount", "net_amount")


def bq_lookup(table: str, cache_path, project: str | None) -> dict[str, dict]:
    if cache_path and Path(cache_path).exists():
        return json.loads(Path(cache_path).read_text())

    sql = ("SELECT teamkatalogenId, teamkatalogen, teamType, pa_seksjon, status "
           f"FROM `{table}` WHERE teamkatalogenId IS NOT NULL")
    print(f"querying BigQuery: {table}", file=sys.stderr)
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project)
        rows = [dict(r) for r in client.query(sql).result()]
    except ImportError:
        # fall back to bq CLI for local use without the python client installed
        cmd = ["bq", "query", "--use_legacy_sql=false", "--format=json",
               "--max_rows=1000000", "--headless"]
        if project:
            cmd.append(f"--project_id={project}")
        cmd.append(sql)
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except FileNotFoundError:
            sys.exit(
                "`bq` not found and google-cloud-bigquery is not installed.\n"
                "Either:  pip install google-cloud-bigquery\n"
                "     or: install the gcloud SDK and run gcloud auth login --update-adc"
            )
        if out.returncode != 0:
            sys.exit("bq failed (exit {}).\n--- stdout ---\n{}\n--- stderr ---\n{}"
                     .format(out.returncode, out.stdout.strip()[:2000] or "(empty)",
                             out.stderr.strip()[:2000] or "(empty)"))
        try:
            rows = json.loads(out.stdout or "[]")
        except json.JSONDecodeError:
            sys.exit(f"bq exited 0 but did not return JSON:\n{out.stdout[:2000]}")

    dupes = [i for i, c in Counter(r["teamkatalogenId"] for r in rows).items() if c > 1]
    if dupes:
        print(f"WARNING: {len(dupes)} teamkatalogenId(s) appear more than once in "
              f"the view; keeping the first row of each. e.g. {dupes[:3]}",
              file=sys.stderr)

    lookup = {}
    for r in rows:
        lookup.setdefault(r["teamkatalogenId"], {
            "teamkatalogen": r.get("teamkatalogen") or "",
            "teamType": r.get("teamType") or "",
            "pa_seksjon": r.get("pa_seksjon") or "",
            "status": r.get("status") or "",
        })
    if cache_path:
        Path(cache_path).write_text(json.dumps(lookup, indent=1, sort_keys=True))
    print(f"{len(lookup):,} teams from teamkatalogen -> {cache_path}", file=sys.stderr)
    return lookup


def rollup(rows, keys, out_path, extra_cols=()):
    agg = defaultdict(lambda: defaultdict(float))
    meta, repos = {}, defaultdict(int)
    for r in rows:
        k = tuple(r[x] for x in keys)
        for c in MONEY:
            agg[k][c] += float(r[c] or 0)
        repos[k] = max(repos[k], int(float(r.get("repos") or 0)))
        meta.setdefault(k, r)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(list(keys) + list(extra_cols)
                   + ["gross_amount", "discount_amount", "net_amount", "repos"])
        for k, v in sorted(agg.items(), key=lambda x: (x[0][0], -x[1]["gross_amount"])):
            w.writerow(list(k) + [meta[k].get(c, "") for c in extra_cols]
                       + [round(v["gross_amount"], 4), round(v["discount_amount"], 4),
                          round(v["net_amount"], 4), repos[k]])
    return agg


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path", type=Path, help="by_month_team_sku.csv")
    p.add_argument("--outdir", type=Path, default=Path("."))
    p.add_argument("--table", default=TABLE)
    p.add_argument("--cache", type=Path, default=Path("teamkatalogen_cache.json"))
    p.add_argument("--project", default=os.environ.get("BQ_PROJECT"),
                   help="billing project for the query. Defaults to $BQ_PROJECT, "
                        "else whatever gcloud config has set.")
    a = p.parse_args()
    a.outdir.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(a.csv_path.open(newline="", encoding="utf-8-sig")))
    if not rows:
        sys.exit("empty input")
    tk = bq_lookup(a.table, a.cache, a.project)

    missing = set()
    named = []
    for r in rows:
        tid = r["teamkatalogen_id"]
        if not tid:
            # org-level: name it after the product so the bill is legible
            product = r["product"] or "(ukjent produkt)"
            meta = {"teamkatalogen": product, "teamType": "org-level",
                    "pa_seksjon": product, "status": ""}
        elif tid in SENTINELS:
            # name the row after the repo -- the bucket is already the seksjon,
            # so repeating it as the team name says nothing actionable
            meta = {"teamkatalogen": r.get("repo") or tid, "teamType": "repo",
                    "pa_seksjon": tid, "status": ""}
        elif tid in tk:
            meta = dict(tk[tid])
            meta["pa_seksjon"] = meta["pa_seksjon"] or NO_SEKSJON
        else:
            missing.add(tid)
            meta = {"teamkatalogen": NOT_IN_TK, "teamType": "",
                    "pa_seksjon": NOT_IN_TK, "status": ""}
        named.append({**r, **meta})

    out1 = a.outdir / "by_month_team_sku_named.csv"
    cols = ["month", "teamkatalogen_id", "teamkatalogen", "teamType", "pa_seksjon",
            "status", "repo", "product", "sku", "unit_type", "quantity",
            "gross_amount", "discount_amount", "net_amount", "repos", "line_items"]
    with out1.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(named, key=lambda x: (x["month"], -float(x["gross_amount"] or 0))):
            w.writerow(r)

    out2 = a.outdir / "by_month_seksjon.csv"
    rollup(named, ("month", "pa_seksjon"), out2)
    out3 = a.outdir / "by_month_team_named.csv"
    rollup(named, ("month", "teamkatalogen"),
           out3, extra_cols=("teamkatalogen_id", "teamType", "pa_seksjon", "status"))

    src = sum(float(r["gross_amount"] or 0) for r in rows)
    dst = sum(float(r["gross_amount"] or 0) for r in named)
    orglevel = sum(float(r["gross_amount"] or 0) for r in named
                   if r["teamType"] == "org-level")
    print(f"\nseksjoner: {len({r['pa_seksjon'] for r in named}):,}")
    print(f"org-level: {orglevel:,.2f} gross, split across "
          + ", ".join(sorted({r['product'] for r in named
                              if r['teamType'] == 'org-level'})) or "(none)")
    if missing:
        print(f"NOT IN TEAMKATALOGEN: {len(missing)} id(s) whodis returned but the "
              f"view lacks, e.g. {sorted(missing)[:3]}")
    print(f"gross in:  {src:,.2f}")
    print(f"gross out: {dst:,.2f}  (delta {dst - src:+.4f})")
    for o in (out1, out2, out3):
        print(f"wrote {o}")


if __name__ == "__main__":
    main()


def run(csv_path, outdir, cache_path=None, project=None, table=TABLE,
        use_cache=False):
    """Programmatic entry point for the NAIS app.
    use_cache=False (default): always query BigQuery, ignore cache file.
    use_cache=True: read existing cache and skip BQ if populated (local dev)."""
    import pathlib
    outdir = pathlib.Path(outdir)
    if cache_path is None:
        cache_path = outdir / "tk_cache.json"
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8-sig")))
    if use_cache and cache_path and cache_path.exists():
        import json
        tk = json.loads(cache_path.read_text())
        import logging; logging.getLogger("app").info(
            "enrich: using cached teamkatalogen (%d teams)", len(tk))
    else:
        tk = bq_lookup(table, cache_path if use_cache else None, project)
    missing = set()
    named = []
    for r in rows:
        tid = r["teamkatalogen_id"]
        if not tid:
            product = r["product"] or "(ukjent produkt)"
            meta = {"teamkatalogen": product, "teamType": "org-level",
                    "pa_seksjon": product, "status": ""}
        elif tid in SENTINELS:
            meta = {"teamkatalogen": r.get("repo") or tid, "teamType": "repo",
                    "pa_seksjon": tid, "status": ""}
        elif tid in tk:
            meta = dict(tk[tid])
            meta["pa_seksjon"] = meta["pa_seksjon"] or NO_SEKSJON
        else:
            missing.add(tid)
            meta = {"teamkatalogen": NOT_IN_TK, "teamType": "",
                    "pa_seksjon": NOT_IN_TK, "status": ""}
        named.append({**r, **meta})
    cols = ["month","teamkatalogen_id","teamkatalogen","teamType","pa_seksjon",
            "status","repo","product","sku","unit_type","quantity","gross_amount",
            "discount_amount","net_amount","repos","line_items"]
    out1 = outdir / "by_month_team_sku_named.csv"
    with out1.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in sorted(named, key=lambda x:(x["month"],-float(x["gross_amount"] or 0))):
            w.writerow(r)
    rollup(named, ("month","pa_seksjon"), outdir/"by_month_seksjon.csv")
    rollup(named, ("month","teamkatalogen"), outdir/"by_month_team_named.csv",
           extra_cols=("teamkatalogen_id","teamType","pa_seksjon","status"))
    import logging; logging.getLogger("app").info(
        "enrich: %d missing ids, wrote %s", len(missing), out1)