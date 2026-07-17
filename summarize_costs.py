#!/usr/bin/env python3
"""
Summarize a GitHub billing CSV export per month, repo and SKU.

    python3 summarize_costs.py export.csv --org navikt
    # -> by_month_repo_sku.csv

Input columns (from the GUI export):
    date product sku quantity unit_type applied_cost_per_quantity
    gross_amount discount_amount net_amount organization repository
    cost_center_name

Output grain is (month, repository, product, sku, unit_type). Everything
downstream aggregates up from this, so the "what exactly costs money" detail
survives all the way to the dashboard.

Rows with no repository (Copilot seats, GHEC/GHAS licences) keep an empty
repository and are labelled by product later -- they are org-level spend, not
a mapping failure.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

# The export writes dates like 1/1/26 -- ambiguous between M/D/YY and D/M/YY
# for days 1-12, so we do not guess. Default M/D/YY; --dayfirst to override.
FORMATS_MONTHFIRST = ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d")
FORMATS_DAYFIRST = ("%d/%m/%y", "%d/%m/%Y", "%Y-%m-%d")


def parse_month(raw: str, dayfirst: bool) -> str:
    s = raw.strip()
    for fmt in (FORMATS_DAYFIRST if dayfirst else FORMATS_MONTHFIRST):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {raw!r}")


def num(raw: str) -> float:
    s = (raw or "").strip().replace(",", "")
    return float(s) if s else 0.0


def read_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        head = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(head, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        yield from csv.DictReader(f, dialect=dialect)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path", type=Path)
    p.add_argument("-o", "--out", type=Path, default=Path("by_month_repo_sku.csv"))
    p.add_argument("--org", help="keep only rows for this organization. The "
                   "enterprise export spans every org under `nav`.")
    p.add_argument("--dayfirst", action="store_true",
                   help="dates are D/M/YY rather than M/D/YY")
    a = p.parse_args()

    agg = defaultdict(lambda: defaultdict(float))
    months, orgs = set(), Counter()
    skipped = dropped = n = 0

    for row in read_rows(a.csv_path):
        org = (row.get("organization") or "").strip()
        orgs[org or "(none)"] += 1
        if a.org and org != a.org:
            dropped += 1
            continue
        try:
            month = parse_month(row["date"], a.dayfirst)
        except (ValueError, KeyError) as e:
            skipped += 1
            if skipped <= 3:
                print(f"skipping row: {e}", file=sys.stderr)
            continue

        n += 1
        months.add(month)
        key = (month,
               (row.get("repository") or "").strip(),
               (row.get("product") or "").strip(),
               (row.get("sku") or "").strip(),
               (row.get("unit_type") or "").strip())
        v = agg[key]
        v["quantity"] += num(row.get("quantity"))
        v["gross_amount"] += num(row.get("gross_amount"))
        v["discount_amount"] += num(row.get("discount_amount"))
        v["net_amount"] += num(row.get("net_amount"))
        v["line_items"] += 1

    if not n:
        sys.exit("no parseable rows")

    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month", "repository", "product", "sku", "unit_type",
                    "quantity", "gross_amount", "discount_amount", "net_amount",
                    "line_items"])
        for (month, repo, product, sku, unit), v in sorted(
                agg.items(), key=lambda x: (x[0][0], -x[1]["gross_amount"])):
            w.writerow([month, repo, product, sku, unit, round(v["quantity"], 4),
                        round(v["gross_amount"], 4), round(v["discount_amount"], 4),
                        round(v["net_amount"], 4), int(v["line_items"])])

    gross = sum(v["gross_amount"] for v in agg.values())
    net = sum(v["net_amount"] for v in agg.values())
    norepo = sum(v["gross_amount"] for k, v in agg.items() if not k[1])
    repos = {k[1] for k in agg if k[1]}

    print(f"{n:,} rows, {skipped} skipped"
          + (f", {dropped:,} dropped (org != {a.org})" if a.org else ""))
    if len(orgs) > 1:
        print(f"orgs:    {len(orgs)} -- "
              + ", ".join(f"{o} ({c:,})" for o, c in orgs.most_common(6)))
        if not a.org:
            print("         NOTE: repo names are not unique across orgs. "
                  "whodis takes a bare repo name, so consider --org.")
    print(f"months:  {min(months)} .. {max(months)}")
    print(f"repos:   {len(repos):,}   skus: {len({k[3] for k in agg})}")
    print(f"gross:   {gross:,.2f}")
    print(f"net:     {net:,.2f}  ({100*net/gross if gross else 0:.1f}% of gross)")
    print(f"org-level (no repo): {norepo:,.2f} gross "
          f"({100*norepo/gross if gross else 0:.1f}%) -- licences/Copilot, "
          f"reported per product rather than per team")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()


def run(csv_path, out_path, org=None, dayfirst=False):
    """Programmatic entry point for the NAIS app."""
    from collections import Counter, defaultdict
    from datetime import datetime
    agg = defaultdict(lambda: defaultdict(float))
    months, orgs = set(), Counter()
    skipped = dropped = n = 0
    for row in read_rows(csv_path):
        org_col = (row.get("organization") or "").strip()
        orgs[org_col or "(none)"] += 1
        if org and org_col != org:
            dropped += 1; continue
        try:
            month = parse_month(row["date"], dayfirst)
        except (ValueError, KeyError):
            skipped += 1; continue
        n += 1; months.add(month)
        key = (month, (row.get("repository") or "").strip(),
               (row.get("product") or "").strip(),
               (row.get("sku") or "").strip(),
               (row.get("unit_type") or "").strip())
        v = agg[key]
        v["quantity"]       += num(row.get("quantity"))
        v["gross_amount"]   += num(row.get("gross_amount"))
        v["discount_amount"]+= num(row.get("discount_amount"))
        v["net_amount"]     += num(row.get("net_amount"))
        v["line_items"]     += 1
    import csv
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["month","repository","product","sku","unit_type",
                    "quantity","gross_amount","discount_amount","net_amount","line_items"])
        for (month,repo,product,sku,unit),v in sorted(
                agg.items(), key=lambda x: (x[0][0],-x[1]["gross_amount"])):
            w.writerow([month,repo,product,sku,unit,
                        round(v["quantity"],4),round(v["gross_amount"],4),
                        round(v["discount_amount"],4),round(v["net_amount"],4),
                        int(v["line_items"])])
    import logging; logging.getLogger("app").info(
        "summarize: %d rows, %d skipped, %d dropped -> %s", n, skipped, dropped, out_path)
