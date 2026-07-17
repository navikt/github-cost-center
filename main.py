"""
github-cost-dashboard — FastAPI app for NAIS.

Routes:
  GET  /           stream dashboard.html from GCS (or 404 if not yet generated)
  POST /upload     accept billing CSV, run pipeline, write dashboard to GCS
  GET  /health     liveness/readiness probe
"""

import asyncio
import io
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

class NoHealthFilter(logging.Filter):
    def filter(self, record):
        return "/health" not in record.getMessage()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("uvicorn.access").addFilter(NoHealthFilter())
log = logging.getLogger("app")

# ── env ──────────────────────────────────────────────────────────────────────
BUCKET_NAME    = os.environ["GCS_BUCKET_NAME"]        # set in nais.yaml env
WHODIS_BASE    = os.environ.get("WHODIS_BASE_URL", "http://whodis/")
BQ_PROJECT     = os.environ.get("BQ_PROJECT", "appsec-prod-624d")
GH_ORG         = os.environ.get("GITHUB_ORG", "navikt")
DASHBOARD_KEY  = "dashboard.html"
WHODIS_CACHE   = "whodis_cache.json"
TK_CACHE       = "teamkatalogen_cache.json"

# ── GCS ──────────────────────────────────────────────────────────────────────
from google.cloud import storage as gcs

_gcs: gcs.Client | None = None

def gcs_client() -> gcs.Client:
    global _gcs
    if _gcs is None:
        _gcs = gcs.Client()
    return _gcs

def bucket() -> gcs.Bucket:
    return gcs_client().bucket(BUCKET_NAME)

def gcs_read(key: str) -> bytes | None:
    try:
        return bucket().blob(key).download_as_bytes()
    except Exception:
        return None

def gcs_write(key: str, data: bytes | str, content_type="application/octet-stream"):
    blob = bucket().blob(key)
    blob.upload_from_string(data if isinstance(data, bytes) else data.encode(),
                            content_type=content_type)

# ── pipeline steps ────────────────────────────────────────────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent))

import summarize_costs
import map_teams
import enrich_seksjon
import visualize

import json

def load_cache(key: str) -> dict:
    raw = gcs_read(key)
    return json.loads(raw) if raw else {}

def save_cache(key: str, data: dict):
    gcs_write(key, json.dumps(data, indent=1, sort_keys=True),
              content_type="application/json")

def run_pipeline(csv_bytes: bytes, use_cache: bool = False) -> str:
    """Run all four steps in-process and return the dashboard HTML."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        csv_path     = tmp / "export.csv"
        repo_sku     = tmp / "by_month_repo_sku.csv"
        team_sku     = tmp / "by_month_team_sku.csv"
        named        = tmp / "by_month_team_sku_named.csv"
        dashboard    = tmp / "dashboard.html"
        wc           = tmp / "whodis_cache.json"
        tc           = tmp / "tk_cache.json"

        csv_path.write_bytes(csv_bytes)

        # pull caches from GCS only when the caller opted in
        if use_cache:
            whodis_cache = load_cache(WHODIS_CACHE)
            wc.write_text(json.dumps(whodis_cache))
            tk_cache = load_cache(TK_CACHE)
            tc.write_text(json.dumps(tk_cache))

        # step 1: summarize
        summarize_costs.run(csv_path, repo_sku, org=GH_ORG)

        # step 2: map repos -> teams
        map_teams.run(repo_sku, team_sku,
                      base_url=WHODIS_BASE, cache_path=wc, use_cache=use_cache)

        # step 3: enrich from BQ
        enrich_seksjon.run(team_sku, outdir=tmp,
                           cache_path=tc, project=BQ_PROJECT,
                           use_cache=use_cache)

        # step 4: build dashboard
        visualize.run(named, dashboard)

        if use_cache:
            save_cache(WHODIS_CACHE, json.loads(wc.read_text()))
            save_cache(TK_CACHE, json.loads(tc.read_text()))

        return dashboard.read_text(encoding="utf-8")

# ── FastAPI ───────────────────────────────────────────────────────────────────
_pipeline_lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup — bucket=%s whodis=%s", BUCKET_NAME, WHODIS_BASE)
    yield


UPLOAD_PAGE = """<!DOCTYPE html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Last opp GitHub-eksport</title>
<style>
  :root { --ink:#16202C; --muted:#64717F; --line:#D6DCE3;
          --card:#FFF; --paper:#EDF0F3; --c0:#1F5D75; }
  * { box-sizing:border-box; }
  body { margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; background:var(--paper);
         font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         font-size:15px; color:var(--ink); }
  .card { background:var(--card); border:1px solid var(--line);
          border-radius:12px; padding:36px 40px; width:100%; max-width:480px; }
  h1 { font-size:18px; font-weight:650; margin:0 0 6px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:28px; }
  label { display:block; font-size:13px; font-weight:600; margin-bottom:6px; }
  .drop { border:2px dashed var(--line); border-radius:8px; padding:32px 20px;
          text-align:center; cursor:pointer; transition:border-color .15s;
          color:var(--muted); }
  .drop:hover, .drop.over { border-color:var(--c0); color:var(--c0); }
  .drop input { display:none; }
  .fname { margin-top:10px; font-size:13px; font-weight:600;
           color:var(--c0); min-height:18px; }
  .row { display:flex; align-items:center; gap:10px; margin-top:10px; }
  .row label { margin:0; font-size:13px; font-weight:400; color:var(--muted); }
  button { margin-top:24px; width:100%; padding:11px;
           background:var(--c0); color:#fff; border:0; border-radius:8px;
           font:inherit; font-size:15px; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  button:hover:not(:disabled) { filter:brightness(1.1); }
  .msg { margin-top:16px; font-size:13px; min-height:18px; text-align:center; }
  .err { color:#b03a2e; }
</style>
</head>
<body>
<div class="card">
  <h1>GitHub-kostnader</h1>
  <div class="sub">Last opp en billing-eksport fra
    <a href="https://github.com/enterprises/nav/billing/usage" target="_blank">
      github.com/enterprises/nav/billing/usage</a>.
  </div>

  <label>Eksport-fil (.csv)</label>
  <div class="drop" id="drop">
    <input type="file" id="file" accept=".csv">
    <div>Dra hit eller <span style="color:var(--c0);text-decoration:underline">bla</span></div>
    <div class="fname" id="fname"></div>
  </div>

  <div class="row">
    <input type="checkbox" id="cache">
    <label for="cache">Bruk hurtigbuffer (whodis + BQ) — raskere, men kan gi utdaterte data</label>
  </div>

  <button id="btn" disabled>Last opp og generer dashboard</button>
  <div class="msg" id="msg"></div>
</div>

<script>
const drop=document.getElementById("drop"), fi=document.getElementById("file"),
      fname=document.getElementById("fname"), btn=document.getElementById("btn"),
      msg=document.getElementById("msg"), cache=document.getElementById("cache");

function setFile(f){
  fname.textContent = f ? f.name : "";
  btn.disabled = !f;
  fi._file = f;
}
drop.onclick = () => fi.click();
fi.onchange = () => setFile(fi.files[0]);
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => {
  e.preventDefault(); drop.classList.remove("over");
  const f = e.dataTransfer.files[0];
  if (f && f.name.endsWith(".csv")) setFile(f);
  else { msg.textContent = "Kun .csv-filer støttes."; msg.className="msg err"; }
};

btn.onclick = async () => {
  const f = fi._file; if (!f) return;
  btn.disabled = true;
  msg.className = "msg"; msg.textContent = "Laster opp…";
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await fetch("/upload?cache=" + cache.checked, {method:"POST", body:fd});
    if (r.redirected) { window.location.href = r.url; return; }
    if (r.ok) { window.location.href = "/"; return; }
    const j = await r.json().catch(() => ({detail: r.statusText}));
    msg.textContent = j.detail || "Noe gikk galt.";
    msg.className = "msg err";
  } catch(e) {
    msg.textContent = "Nettverksfeil: " + e.message;
    msg.className = "msg err";
  } finally { btn.disabled = false; }
};
</script>
</body>
</html>"""

app = FastAPI(title="GitHub cost dashboard", lifespan=lifespan)

@app.get("/upload", response_class=HTMLResponse)
def upload_page():
    return HTMLResponse(UPLOAD_PAGE)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
def index():
    html = gcs_read(DASHBOARD_KEY)
    if html is None:
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/upload")
    return HTMLResponse(html.decode())

@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile = File(...),
    cache: bool = False,
):
    """
    cache=false (default): always call whodis and BQ fresh.
    cache=true:  read/write GCS cache files -- useful when BQ is slow
                 and the teamkatalogen mapping hasn't changed.
    ?cache=true in the URL or form field to enable.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Forventet en .csv-fil")

    csv_bytes = await file.read()
    if len(csv_bytes) > 200 * 1024 * 1024:
        raise HTTPException(413, "Filen er for stor (maks 200 MB)")

    if _pipeline_lock.locked():
        raise HTTPException(409, "Et annet bygg pågår allerede — prøv igjen om litt")

    async with _pipeline_lock:
        try:
            html = await asyncio.get_event_loop().run_in_executor(
                None, run_pipeline, csv_bytes
            )
        except Exception as e:
            log.exception("pipeline feilet")
            raise HTTPException(500, f"Pipeline feilet: {e}") from e

        gcs_write(DASHBOARD_KEY, html, content_type="text/html; charset=utf-8")
        log.info("dashboard updated — %d kB", len(html) // 1024)

    return JSONResponse({"status": "ok", "size_kb": len(html) // 1024},
                        headers={"HX-Redirect": "/"})
