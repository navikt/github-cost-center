#!/usr/bin/env python3
"""
Map per-repo costs to teamkatalogen teams via whodis, keeping the SKU grain.

    python3 map_teams.py by_month_repo_sku.csv
    python3 map_teams.py by_month_repo_sku.csv --base-url http://whodis.internal
    # -> by_month_team_sku.csv

whodis:  GET {base_url}/repository/{repo} -> ["<uuid>", "<uuid>", ...]

A repo can map to 0, 1 or many teams. --allocation controls the many case:
  split      (default) cost / n_teams to each team. Org total is preserved.
  duplicate  full cost to each team. Total inflates -- do not sum the column.
  first      full cost to the first id only. Arbitrary but total-preserving.

Rows with no repository are org-level spend (licences, Copilot). They pass
through with an empty team id and are labelled by product downstream.

Rows that could not be mapped keep their repo name in the `repo` column, so a
human can go and fix them. Mapped rows leave `repo` empty -- the repo names are
not needed once a team owns the cost, and keeping them would explode the grain.

Lookups cache to whodis_cache.json. Failures are NOT cached, so a rerun
retries them; they are reported separately from a genuine "no team".
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

NO_TEAM = "(no team)"
LOOKUP_FAILED = "(whodis lookup failed)"
ORG_LEVEL = ""          # empty repository -> empty team id

MONEY = ("quantity", "gross_amount", "discount_amount", "net_amount", "line_items")


def whodis_teams(repo: str, base_url: str, timeout: float) -> list[str]:
    """Returns team ids. Raises on transport/parse failure -- caller decides."""
    url = f"{base_url.rstrip('/')}/repository/{urllib.parse.quote(repo)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []  # known-unknown repo, not an error
        raise
    if not isinstance(data, list):
        raise ValueError(f"expected a list, got {type(data).__name__}")
    return [str(x) for x in data if x]


def resolve(repos, base_url, cache_path, timeout):
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    failed = set()
    todo = [r for r in repos if r not in cache]
    for i, repo in enumerate(todo, 1):
        try:
            cache[repo] = whodis_teams(repo, base_url, timeout)
        except Exception as e:                       # noqa: BLE001
            failed.add(repo)
            print(f"  ! {repo}: {e}", file=sys.stderr)
        if i % 50 == 0:
            print(f"  whodis {i}/{len(todo)}", file=sys.stderr)
            cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
            time.sleep(0.05)
    cache_path.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache, failed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path", type=Path, help="by_month_repo_sku.csv")
    p.add_argument("-o", "--out", type=Path, default=Path("by_month_team_sku.csv"))
    p.add_argument("--base-url",
                   default=os.environ.get("WHODIS_BASE_URL", "http://localhost:8080"))
    p.add_argument("--allocation", choices=("split", "duplicate", "first"),
                   default="split")
    p.add_argument("--cache", type=Path, default=Path("whodis_cache.json"))
    p.add_argument("--timeout", type=float, default=10.0)
    a = p.parse_args()

    rows = list(csv.DictReader(a.csv_path.open(newline="", encoding="utf-8-sig")))
    if not rows:
        sys.exit("empty input")

    repos = sorted({r["repository"] for r in rows if r["repository"]})
    print(f"{len(repos):,} repos -> {a.base_url}", file=sys.stderr)
    cache, failed = resolve(repos, a.base_url, a.cache, a.timeout)

    # (month, team, repo, product, sku, unit_type) -> totals
    # `repo` is only set for rows we could not map, so the grain is unchanged
    # for everything else.
    agg = defaultdict(lambda: defaultdict(float))
    repos_seen = defaultdict(set)
    unmapped = set()

    for row in rows:
        repo = row["repository"]
        if not repo:
            teams, weight = [ORG_LEVEL], 1.0
        elif repo in failed:
            teams, weight = [LOOKUP_FAILED], 1.0
        else:
            ids = cache.get(repo, [])
            if not ids:
                unmapped.add(repo)
                teams, weight = [NO_TEAM], 1.0
            elif a.allocation == "first":
                teams, weight = ids[:1], 1.0
            elif a.allocation == "duplicate":
                teams, weight = ids, 1.0
            else:
                teams, weight = ids, 1.0 / len(ids)

        for team in teams:
            # keep the repo name where nobody owns the cost -- that is the
            # actionable detail; drop it once a team does
            keep = repo if team in (NO_TEAM, LOOKUP_FAILED) else ""
            k = (row["month"], team, keep, row["product"], row["sku"],
                 row["unit_type"])
            v = agg[k]
            for col in MONEY:
                v[col] += float(row.get(col) or 0) * weight
            if repo:
                repos_seen[(row["month"], team, keep)].add(repo)

    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "teamkatalogen_id", "repo", "product", "sku",
                    "unit_type", "quantity", "gross_amount", "discount_amount",
                    "net_amount", "repos", "line_items"])
        for (month, team, repo, product, sku, unit), v in sorted(
                agg.items(), key=lambda x: (x[0][0], -x[1]["gross_amount"])):
            w.writerow([month, team, repo, product, sku, unit,
                        round(v["quantity"], 4), round(v["gross_amount"], 4),
                        round(v["discount_amount"], 4), round(v["net_amount"], 4),
                        len(repos_seen[(month, team, repo)]),
                        round(v["line_items"], 2)])

    src = sum(float(r["gross_amount"] or 0) for r in rows)
    dst = sum(v["gross_amount"] for v in agg.values())
    multi = sum(1 for r in repos if len(cache.get(r, [])) > 1)
    print(f"\nteams:            {len({t for _, t, *_ in agg if t and t not in (NO_TEAM, LOOKUP_FAILED)}):,}")
    print(f"repos, no team:   {len(unmapped):,} / {len(repos):,}")
    print(f"repos, multiteam: {multi:,}  (allocation={a.allocation})")
    if failed:
        print(f"LOOKUPS FAILED:   {len(failed):,} -- rerun to retry; their cost "
              f"sits in {LOOKUP_FAILED!r}")
    print(f"\ngross in:  {src:,.2f}")
    print(f"gross out: {dst:,.2f}", end="")
    print("  <- inflated by duplication, expected" if a.allocation == "duplicate"
          else f"  (delta {dst - src:+.4f})")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()


def run(csv_path, out_path, base_url="http://localhost:8080",
        cache_path=None, allocation="split", timeout=10.0, use_cache=False):
    """Programmatic entry point for the NAIS app.
    use_cache=False (default): always call whodis, never read/write cache file.
    use_cache=True: read existing cache and persist new lookups (local dev)."""
    import csv, pathlib
    if cache_path is None:
        cache_path = pathlib.Path("whodis_cache.json")
    rows = list(csv.DictReader(csv_path.open(newline="", encoding="utf-8-sig")))
    repos = sorted({r["repository"] for r in rows if r["repository"]})
    if use_cache:
        cache, failed = resolve(repos, base_url, cache_path, timeout)
    else:
        # fresh lookups only -- bypass cache file entirely
        cache = {}
        failed = set()
        for repo in repos:
            try:
                cache[repo] = whodis_teams(repo, base_url, timeout)
            except Exception as e:  # noqa: BLE001
                failed.add(repo)
                import logging; logging.getLogger("app").warning("whodis %s: %s", repo, e)
    agg = defaultdict(lambda: defaultdict(float))
    repos_seen = defaultdict(set)
    unmapped = set()
    for row in rows:
        repo = row["repository"]
        if not repo:
            teams, weight = [ORG_LEVEL], 1.0
        elif repo in failed:
            teams, weight = [LOOKUP_FAILED], 1.0
        else:
            ids = cache.get(repo, [])
            if not ids:
                unmapped.add(repo); teams, weight = [NO_TEAM], 1.0
            elif allocation == "first":
                teams, weight = ids[:1], 1.0
            elif allocation == "duplicate":
                teams, weight = ids, 1.0
            else:
                teams, weight = ids, 1.0/len(ids)
        for team in teams:
            keep = repo if team in (NO_TEAM, LOOKUP_FAILED) else ""
            k = (row["month"],team,keep,row["product"],row["sku"],row["unit_type"])
            v = agg[k]
            for col in MONEY:
                v[col] += float(row.get(col) or 0)*weight
            if repo:
                repos_seen[(row["month"],team,keep)].add(repo)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month","teamkatalogen_id","repo","product","sku","unit_type",
                    "quantity","gross_amount","discount_amount","net_amount",
                    "repos","line_items"])
        for (month,team,repo,product,sku,unit),v in sorted(
                agg.items(), key=lambda x: (x[0][0],-x[1]["gross_amount"])):
            w.writerow([month,team,repo,product,sku,unit,
                        round(v["quantity"],4),round(v["gross_amount"],4),
                        round(v["discount_amount"],4),round(v["net_amount"],4),
                        len(repos_seen[(month,team,repo)]),round(v["line_items"],2)])
    import logging; logging.getLogger("app").info(
        "map_teams: %d unmapped repos, wrote %s", len(unmapped), out_path)
