#!/usr/bin/env python3
"""
Build a self-contained HTML dashboard from by_month_team_sku_named.csv.

    python3 visualize.py by_month_team_sku_named.csv
    # -> dashboard.html   open it; no server, no network, no deps

Data is inlined, so the file can be mailed or committed as-is.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Seksjon values that are a mapping problem rather than a real section.
UNKNOWN = {
    "(no team)": "whodis returned no team for the repo",
    "(whodis lookup failed)": "whodis errored — rerun map_teams.py to retry",
    "(id not in teamkatalogen)": "whodis gave an id the BQ view lacks — deleted team?",
    "(team has no pa_seksjon)": "team joined, but pa_seksjon is null",
}


def num(r, k):
    try:
        return float(r.get(k) or 0)
    except ValueError:
        return 0.0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("csv_path", type=Path, help="by_month_team_sku_named.csv")
    p.add_argument("-o", "--out", type=Path, default=Path("dashboard.html"))
    a = p.parse_args()

    with a.csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = [{
            "month": r["month"],
            "team": r.get("teamkatalogen") or r.get("teamkatalogen_id") or "?",
            "type": r.get("teamType") or "",
            "seksjon": r.get("pa_seksjon") or "",
            "status": r.get("status") or "",
            "repo": r.get("repo") or "",
            "product": r.get("product") or "",
            "sku": r.get("sku") or "",
            "unit": r.get("unit_type") or "",
            "qty": num(r, "quantity"),
            "gross": num(r, "gross_amount"),
            "net": num(r, "net_amount"),
            "repos": int(num(r, "repos")),
        } for r in csv.DictReader(f)]
    if not rows:
        sys.exit("empty input")

    payload = json.dumps({"rows": rows, "unknown": UNKNOWN},
                         ensure_ascii=False, separators=(",", ":"))
    a.out.write_text(HTML.replace("/*__DATA__*/null", payload), encoding="utf-8")
    months = sorted({r["month"] for r in rows})
    print(f"wrote {a.out}  ({a.out.stat().st_size/1024:.0f} kB, {len(months)} months, "
          f"{len(rows):,} rows, {len({r['sku'] for r in rows})} skus)")


HTML = r"""<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GitHub-kostnader per seksjon</title>
<style>
  :root {
    --paper:#EDF0F3; --card:#FFF; --ink:#16202C; --muted:#64717F;
    --line:#D6DCE3; --unattr:#98A4B0; --org:#4C5F70;
    --c0:#1F5D75; --c1:#B4762A; --c2:#8C4A3F; --c3:#4E7350;
    --c4:#6A4A72; --c5:#2E6E8E; --c6:#7A6A3A; --c7:#54636F;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink); font-family:var(--sans);
         font-size:14px; line-height:1.5; -webkit-font-smoothing:antialiased; }
  .wrap { max-width:1100px; margin:0 auto; padding:32px 20px 80px; }
  header { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-end;
           justify-content:space-between; margin-bottom:20px; }
  h1 { font-size:19px; font-weight:650; margin:0; letter-spacing:-0.01em; }
  .sub { color:var(--muted); font-size:13px; margin-top:2px; }
  .controls { display:flex; gap:8px; align-items:center; }
  select, .seg button {
    font:inherit; color:var(--ink); background:var(--card);
    border:1px solid var(--line); border-radius:6px; padding:6px 10px; cursor:pointer; }
  .seg { display:flex; }
  .seg button { border-radius:0; border-left-width:0; }
  .seg button:first-child { border-radius:6px 0 0 6px; border-left-width:1px; }
  .seg button:last-child { border-radius:0 6px 6px 0; }
  .seg button[aria-pressed="true"] { background:var(--ink); color:#fff; border-color:var(--ink); }
  select:focus-visible, button:focus-visible, tr:focus-visible {
    outline:2px solid var(--c0); outline-offset:2px; }

  /* signature: what can and cannot be placed, stated before anything else */
  .ribbon { background:var(--card); border:1px solid var(--line); border-radius:10px;
            padding:14px 16px; margin-bottom:16px;
            display:grid; grid-template-columns:1fr auto; gap:14px; align-items:center; }
  .ribbon .bar { height:10px; border-radius:5px; overflow:hidden; display:flex;
                 border:1px solid var(--line); }
  .ribbon .bar i { display:block; height:100%; }
  .placed { background:var(--c0); }
  .orglvl { background:var(--org); }
  .unplaced { background:var(--unattr); background-image:
    repeating-linear-gradient(45deg,rgba(255,255,255,.55) 0 3px,transparent 3px 6px); }
  .ribbon .figure { font-family:var(--mono); font-size:21px; font-weight:600;
                    text-align:right; white-space:nowrap; }
  .ribbon .cap { color:var(--muted); font-size:12px; margin-top:4px; }
  .key { display:inline-flex; align-items:center; gap:5px; margin-right:14px;
         white-space:nowrap; }
  .key b { font-family:var(--mono); font-weight:600; color:var(--ink); }
  .ribbon .cap { line-height:1.9; }
  .key i { width:9px; height:9px; border-radius:2px; display:inline-block; }

  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:16px; margin-bottom:16px; }
  h2 { font-size:12px; text-transform:uppercase; letter-spacing:.07em;
       color:var(--muted); font-weight:600; margin:0 0 12px; }
  h2 span { text-transform:none; letter-spacing:0; color:var(--ink); }
  h2 span.f { font-weight:400; color:var(--muted); }

  .scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
  table { width:100%; border-collapse:collapse; min-width:520px; }
  th, td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); }
  th { font-size:11px; text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); font-weight:600; }
  td.n, th.n { text-align:right; font-family:var(--mono);
               font-variant-numeric:tabular-nums; white-space:nowrap; }
  tbody tr[data-k] { cursor:pointer; }
  tbody tr[data-k]:hover { background:var(--paper); }
  tr[aria-selected="true"] { background:#E3EBF0; }
  .swatch { display:inline-block; width:9px; height:9px; border-radius:2px;
            margin-right:7px; vertical-align:baseline; }
  .track { background:var(--paper); height:6px; border-radius:3px; overflow:hidden;
           min-width:60px; }
  .track i { display:block; height:100%; }
  .tag { font-size:11px; color:var(--muted); border:1px solid var(--line);
         border-radius:99px; padding:1px 7px; white-space:nowrap; }
  code { font-family:var(--mono); font-size:12.5px; }
  .warn { color:var(--muted); font-style:italic; }
  .empty { color:var(--muted); padding:20px 8px; }
  .hint { color:var(--muted); font-size:12px; margin-top:10px; }
  .clear { font:inherit; font-size:12px; background:none; border:0; color:var(--c0);
           cursor:pointer; padding:0; text-decoration:underline; }
  svg { display:block; width:100%; height:auto; }
  .axis { font-family:var(--mono); font-size:10px; fill:var(--muted); }
  .gl { stroke:var(--line); stroke-width:1; }
  @media (prefers-reduced-motion:no-preference) {
    rect.seg, .track i, .ribbon .bar i { transition:width .18s ease, height .18s ease, y .18s ease; }
  }
  @media (max-width:640px) {
    .ribbon { grid-template-columns:1fr; }
    .ribbon .figure { text-align:left; }
    header { align-items:flex-start; }
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>GitHub-kostnader per seksjon</h1>
      <div class="sub" id="sub"></div>
      <div class="sub">Alle beløp i <strong>USD</strong> — GitHub fakturerer i USD.</div>
    </div>
    <div class="controls">
      <select id="scope" aria-label="Periode"></select>
      <div class="seg" role="group" aria-label="Beløp">
        <button id="bGross" aria-pressed="true">Gross</button>
        <button id="bNet" aria-pressed="false">Net</button>
      </div>
    </div>
  </header>

  <div class="ribbon">
    <div>
      <div class="bar" id="ribBar"></div>
      <div class="cap" id="ribCap"></div>
    </div>
    <div>
      <div class="figure" id="ribFig"></div>
      <div class="cap" style="text-align:right" id="ribFigCap"></div>
    </div>
  </div>

  <div class="card">
    <h2>Per måned <span class="f">— valgt periode uthevet</span></h2>
    <div id="chart"></div>
  </div>

  <div class="card">
    <h2>Seksjoner — <span id="mLabel"></span></h2>
    <div class="scroll"><table>
      <thead><tr>
        <th>Seksjon</th><th class="n">Beløp USD</th><th class="n">Andel</th>
        <th style="width:22%"></th><th class="n">Team</th>
      </tr></thead>
      <tbody id="sekBody"></tbody>
    </table></div>
    <div class="hint">Klikk en seksjon for å filtrere. Klikk igjen for å nullstille.</div>
  </div>

  <div class="card">
    <h2>Team — <span id="tLabel"></span></h2>
    <div class="scroll"><table>
      <thead><tr>
        <th id="teamHead">Team</th><th>Seksjon</th><th>Type</th>
        <th class="n" id="repHead">Repos</th><th class="n">Beløp USD</th>
      </tr></thead>
      <tbody id="teamBody"></tbody>
    </table></div>
    <div class="hint">Klikk et team for å se hva pengene går til.</div>
  </div>

  <div class="card">
    <h2>Hva koster penger — <span id="sLabel"></span>
      <span id="sClear"></span></h2>
    <div class="scroll"><table>
      <thead><tr>
        <th>Produkt</th><th>SKU</th><th class="n">Mengde</th><th>Enhet</th>
        <th class="n">Beløp USD</th><th class="n">Andel</th><th style="width:18%"></th>
      </tr></thead>
      <tbody id="skuBody"></tbody>
    </table></div>
  </div>
</div>

<script>
const DATA = /*__DATA__*/null;
const ROWS = DATA.rows, UNK = DATA.unknown;
const PAL = ["--c0","--c1","--c2","--c3","--c4","--c5","--c6","--c7"];
const isUnk = s => Object.prototype.hasOwnProperty.call(UNK, s);
const isOrg = r => r.type === "org-level";

const months = [...new Set(ROWS.map(r => r.month))].sort();
const years  = [...new Set(months.map(m => m.slice(0,4)))].sort();

let metric = "gross";
// default to the most recent year, unless it only has one month of data
const lastYear = months[months.length - 1].slice(0,4);
let scope = months.filter(m => m.startsWith(lastYear)).length > 1
          ? {t:"year", v:lastYear}
          : {t:"month", v:months[months.length - 1]};
let pickSek = null, pickTeam = null;

const kr = n => n.toLocaleString("nb-NO", {minimumFractionDigits:2, maximumFractionDigits:2});
const qty = n => n.toLocaleString("nb-NO", {maximumFractionDigits:1});
const pct = (n,d) => d ? (100*n/d).toFixed(1) + " %" : "0 %";
const el = id => document.getElementById(id);

const inScope = m => scope.t === "all" ? true
                   : scope.t === "year" ? m.slice(0,4) === scope.v
                   : m === scope.v;
const scopeMonths = () => months.filter(inScope);
const scopeLabel = () => scope.t === "all"
      ? `alle måneder (${months[0]} – ${months[months.length-1]})`
      : scope.t === "year" ? `${scope.v} — hele året` : scope.v;

// stable colour per seksjon, ranked by all-time spend so it survives scope changes
const tot = {};
for (const r of ROWS) tot[r.seksjon] = (tot[r.seksjon] || 0) + r.gross;
const ranked = Object.keys(tot).filter(s => !isUnk(s)).sort((a,b) => tot[b]-tot[a]);
const colorOf = s => isUnk(s) ? "var(--unattr)" : `var(${PAL[ranked.indexOf(s) % PAL.length]})`;

const scoped = () => ROWS.filter(r => inScope(r.month));
const sel = () => scoped().filter(r => (!pickSek || r.seksjon === pickSek)
                                    && (!pickTeam || r.team === pickTeam));

function group(rows, keyfn, seed) {
  const g = {};
  for (const r of rows) {
    const k = keyfn(r);
    (g[k] ??= seed(r, k)).v += r[metric];
    g[k].rows.push(r);
  }
  return Object.values(g).filter(x => x.v !== 0).sort((a,b) => b.v - a.v);
}

function ribbon() {
  const rows = scoped();
  const all = rows.reduce((s,r) => s + r[metric], 0);
  const org = rows.filter(isOrg).reduce((s,r) => s + r[metric], 0);
  const unk = rows.filter(r => isUnk(r.seksjon)).reduce((s,r) => s + r[metric], 0);
  const placed = all - org - unk;
  const w = v => all ? 100*v/all : 0;

  el("ribBar").innerHTML = `<i class="placed" style="width:${w(placed)}%"></i>`
    + `<i class="orglvl" style="width:${w(org)}%"></i>`
    + `<i class="unplaced" style="width:${w(unk)}%"></i>`;
  const key = (cls, v, label) =>
    `<span class="key"><i class="${cls}"></i>${kr(v)} USD `
    + `<b>${w(v).toFixed(1)} %</b> ${label}</span>`;
  el("ribCap").innerHTML = all
    ? key("placed", placed, "på en seksjon")
      + key("orglvl", org, "org-nivå (lisenser, AI)")
      + key("unplaced", unk, "ukjent")
    : "Ingen kostnad i denne perioden.";
  el("ribFig").innerHTML = `${kr(all)} <span style="font-size:13px;color:var(--muted)">USD</span>`;
  el("ribFigCap").textContent = `totalt ${metric} · ${w(org + unk).toFixed(1)} % ikke på en seksjon`;
  const n = scopeMonths().length;
  el("sub").textContent = `${n} ${n === 1 ? "måned" : "måneder"} · ${
    metric === "gross" ? "gross = forbruk før inkludert kvote"
                       : "net = faktisk fakturert"}`;
}

function chart() {
  const W=900, H=260, L=62, R=8, T=8, B=26;
  const per = months.map(m => group(ROWS.filter(r => r.month === m),
                                    r => r.seksjon,
                                    (r,k) => ({k, v:0, rows:[], org:isOrg(r)})));
  const max = Math.max(...per.map(g => g.reduce((s,x) => s + Math.max(0,x.v), 0)), 1);
  const bw = Math.min(56, (W-L-R)/months.length*0.62);
  const x = i => L + (W-L-R)*(i+0.5)/months.length - bw/2;
  const y = v => T + (H-T-B)*(1 - v/max);
  const thin = months.length > 14;

  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Kostnad per måned per seksjon">
    <defs><pattern id="h" width="6" height="6" patternTransform="rotate(45)"
      patternUnits="userSpaceOnUse"><rect width="6" height="6" fill="var(--unattr)"/>
      <line x1="0" y1="0" x2="0" y2="6" stroke="#fff" stroke-width="3" opacity=".55"/>
    </pattern></defs>`;
  for (let g=0; g<=4; g++) {
    const v = max*g/4, yy = y(v);
    s += `<line class="gl" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/>
          <text class="axis" x="${L-8}" y="${yy+3}" text-anchor="end">${Math.round(v)}</text>`;
  }
  months.forEach((m,i) => {
    const on = inScope(m);
    const g = per[i].filter(x => x.v > 0)
      .sort((a,b) => (isUnk(a.k)?2:a.org?1:0) - (isUnk(b.k)?2:b.org?1:0) || b.v - a.v);
    let acc = 0;
    for (const x0 of g) {
      const h = (H-T-B)*x0.v/max; acc += x0.v;
      const fill = isUnk(x0.k) ? "url(#h)" : x0.org ? "var(--org)" : colorOf(x0.k);
      s += `<rect class="seg" x="${x(i)}" y="${y(acc)}" width="${bw}"
              height="${Math.max(h,0.5)}" fill="${fill}" opacity="${on?1:0.28}">
              <title>${m} · ${x0.k} · ${kr(x0.v)}</title></rect>`;
    }
    const lab = thin ? (m.endsWith("-01") ? m.slice(0,4) : m.slice(5)) : m;
    s += `<text class="axis" x="${x(i)+bw/2}" y="${H-8}" text-anchor="middle"
            font-weight="${on?700:400}" opacity="${on?1:0.6}">${lab}</text>`;
  });
  el("chart").innerHTML = s + "</svg>";
}

function seksjoner() {
  const g = group(scoped(), r => r.seksjon,
                  (r,k) => ({k, v:0, rows:[], org:isOrg(r)}));
  const total = g.reduce((s,x) => s + x.v, 0);
  const max = Math.max(...g.map(x => x.v), 1);
  el("mLabel").textContent = scopeLabel();

  el("sekBody").innerHTML = g.length ? g.map(x => {
    const c = isUnk(x.k) ? "var(--unattr)" : x.org ? "var(--org)" : colorOf(x.k);
    const nteams = new Set(x.rows.filter(r => r[metric] !== 0).map(r => r.team)).size;
    return `<tr tabindex="0" data-k="${encodeURIComponent(x.k)}"
        aria-selected="${pickSek === x.k}">
      <td><span class="swatch" style="background:${c}"></span>${
        isUnk(x.k) ? `<span class="warn">${x.k}</span> <span class="tag" title="${UNK[x.k]}">?</span>`
        : x.org ? `<code>${x.k}</code> <span class="tag" title="Org-nivå: lisenser og AI-bruk uten repo">org</span>`
        : x.k}</td>
      <td class="n">${kr(x.v)}</td><td class="n">${pct(x.v,total)}</td>
      <td><div class="track"><i style="width:${100*x.v/max}%;background:${c}"></i></div></td>
      <td class="n">${nteams}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">Ingen kostnad.</td></tr>`;
  wire("sekBody", k => { pickSek = pickSek === k ? null : k; pickTeam = null; render(); });
}

function teamTable() {
  const g = group(sel(), r => r.team,
                  (r,k) => ({k, v:0, rows:[], org:isOrg(r), seksjon:r.seksjon,
                             type:r.type, status:r.status}));
  el("tLabel").textContent = pickSek ? `${scopeLabel()} · ${pickSek}` : scopeLabel();
  el("teamHead").textContent = pickSek && isUnk(pickSek) ? "Repo" : "Team";
  const multi = scopeMonths().length > 1;
  el("repHead").title = multi ? "Største enkeltmåned — repos kan ikke summeres over måneder"
                              : "Antall repos";

  el("teamBody").innerHTML = g.length ? g.slice(0,200).map(x => {
    const repos = Math.max(...x.rows.map(r => r.repos), 0);
    return `<tr tabindex="0" data-k="${encodeURIComponent(x.k)}"
        aria-selected="${pickTeam === x.k}">
      <td>${isUnk(x.seksjon)
              ? `<code>${x.k}</code> <span class="tag" title="Repo uten kjent team — dette er repoet å fikse">repo</span>`
            : x.org ? `<code>${x.k}</code>`
            : x.k + (x.status && x.status !== "ACTIVE" ? ` <span class="tag">${x.status}</span>` : "")}</td>
      <td>${isUnk(x.seksjon) ? `<span class="warn">—</span>` : x.seksjon}</td>
      <td>${isUnk(x.seksjon) ? "—" : x.type || "—"}</td>
      <td class="n">${repos || "—"}${multi && repos ? '<span class="warn"> maks</span>' : ""}</td>
      <td class="n">${kr(x.v)}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">Ingen team.</td></tr>`;
  wire("teamBody", k => { pickTeam = pickTeam === k ? null : k; render(); });
}

function skuTable() {
  const rows = sel();
  const g = group(rows, r => r.product + "\u0000" + r.sku + "\u0000" + r.unit,
                  (r) => ({v:0, rows:[], product:r.product, sku:r.sku, unit:r.unit}));
  const total = g.reduce((s,x) => s + x.v, 0);
  const max = Math.max(...g.map(x => x.v), 1);

  const what = pickTeam ? pickTeam : pickSek ? pickSek : "hele organisasjonen";
  el("sLabel").textContent = `${what} · ${scopeLabel()}`;
  el("sClear").innerHTML = (pickSek || pickTeam)
    ? ` <button class="clear" id="clr">nullstill</button>` : "";
  if (el("clr")) el("clr").onclick = () => { pickSek = pickTeam = null; render(); };

  el("skuBody").innerHTML = g.length ? g.map(x => `
    <tr><td><code>${x.product}</code></td><td><code>${x.sku}</code></td>
      <td class="n">${qty(x.rows.reduce((s,r) => s + r.qty, 0))}</td>
      <td class="warn">${x.unit}</td>
      <td class="n">${kr(x.v)}</td><td class="n">${pct(x.v,total)}</td>
      <td><div class="track"><i style="width:${100*x.v/max}%;
        background:var(--c0)"></i></div></td></tr>`).join("")
    : `<tr><td colspan="7" class="empty">Ingen kostnad.</td></tr>`;
}

function wire(id, fn) {
  for (const tr of el(id).querySelectorAll("tr[data-k]")) {
    const go = () => fn(decodeURIComponent(tr.dataset.k));
    tr.onclick = go;
    tr.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } };
  }
}

function render() { ribbon(); chart(); seksjoner(); teamTable(); skuTable(); }

const opts = [];
if (months.length > 1) opts.push({v:"all", t:"all", label:"Alle måneder"});
for (const y of years)
  if (months.filter(m => m.startsWith(y)).length > 1)
    opts.push({v:"y:"+y, t:"year", label:`${y} — hele året`});
for (const m of months) opts.push({v:"m:"+m, t:"month", label:m});
const scopeKey = scope.t === "all" ? "all"
               : scope.t === "year" ? "y:" + scope.v : "m:" + scope.v;
el("scope").innerHTML = opts.map(o =>
  `<option value="${o.v}" ${o.v === scopeKey ? "selected":""}>${o.label}</option>`).join("");
el("scope").onchange = e => {
  const v = e.target.value;
  scope = v === "all" ? {t:"all"} : v.startsWith("y:") ? {t:"year", v:v.slice(2)}
        : {t:"month", v:v.slice(2)};
  render();
};
for (const [id,m] of [["bGross","gross"],["bNet","net"]]) {
  el(id).onclick = () => {
    metric = m;
    el("bGross").setAttribute("aria-pressed", String(m==="gross"));
    el("bNet").setAttribute("aria-pressed", String(m==="net"));
    render();
  };
}
render();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()


def run(csv_path, out_path):
    """Programmatic entry point for the NAIS app."""
    import csv, json
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        rows = [{
            "month": r["month"],
            "team":  r.get("teamkatalogen") or r.get("teamkatalogen_id") or "?",
            "type":  r.get("teamType") or "",
            "seksjon": r.get("pa_seksjon") or "",
            "status":  r.get("status") or "",
            "repo":    r.get("repo") or "",
            "product": r.get("product") or "",
            "sku":     r.get("sku") or "",
            "unit":    r.get("unit_type") or "",
            "qty":  _num(r, "quantity"),
            "gross":_num(r, "gross_amount"),
            "net":  _num(r, "net_amount"),
            "repos": int(_num(r, "repos")),
        } for r in csv.DictReader(f)]
    payload = json.dumps({"rows": rows, "unknown": UNKNOWN},
                         ensure_ascii=False, separators=(",",":"))
    html = HTML.replace("/*__DATA__*/null", payload)
    out_path.write_text(html, encoding="utf-8")
    import logging; logging.getLogger("app").info(
        "visualize: %d rows -> %s (%d kB)", len(rows), out_path,
        out_path.stat().st_size//1024)

def _num(r, k):
    try: return float(r.get(k) or 0)
    except ValueError: return 0.0
