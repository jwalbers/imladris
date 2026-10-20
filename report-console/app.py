"""
report-console — the back end of the imaging workflow, seen from AdvaPACS.

Mirrors the modality console for the reporting side: every order with its
study, its report and a timeline of what changed when.

How it learns about changes
---------------------------
* AdvaPACS webhooks (orders, studies, patients, reports) reach the modality
  sidecar, which forwards each one here (POST /trigger). A webhook is only a
  trigger: we fetch the resource it names from the AdvaPACS FHIR API ourselves.
* A catch-up sync every SYNC_SEC asks FHIR for everything changed since the
  last sync (_lastUpdated), so a lost webhook only delays an update.
* Each fetched resource is compared with the stored copy; a new resource or a
  status change becomes a timeline event keyed by accession number.

FHIR R5 resources used: ServiceRequest (order), ImagingStudy (images),
DiagnosticReport (report), Patient, Practitioner, Device (station AE -> site).
The AdvaPACS worklist state itself ("Ready to Read", assignment) is not exposed
through FHIR, so it shows only as webhook arrivals.

Environment
-----------
FHIR_BASE_URL, FHIR_KEY_ID, FHIR_KEY_SECRET   AdvaPACS FHIR API
SYNC_SEC        catch-up interval (default 120)
DB_PATH         SQLite file (default /data/report-console.db)
CR_AET US_AET CT_AET                          this site's station AEs
LAB_SITE_NAME   label for this site (default "this site")
PORT            default 5003
"""

import base64
import json
import logging
import os
import sqlite3
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, abort, jsonify, render_template, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
log = logging.getLogger("report-console")

FHIR_BASE  = os.getenv("FHIR_BASE_URL", "https://usa1.api.integration.advapacs.com/fhir/R5").rstrip("/")
FHIR_ID    = os.getenv("FHIR_KEY_ID", "")
FHIR_SEC   = os.getenv("FHIR_KEY_SECRET", "")
SYNC_SEC   = int(os.getenv("SYNC_SEC", "120"))
DB_PATH    = os.getenv("DB_PATH", "/data/report-console.db")
SITE_AETS  = {a for a in (os.getenv("CR_AET"), os.getenv("US_AET"), os.getenv("CT_AET")) if a}
SITE_NAME  = os.getenv("LAB_SITE_NAME", "this site")
PORT       = int(os.getenv("PORT", "5003"))

TRACKED = ("ServiceRequest", "ImagingStudy", "DiagnosticReport")
WEBHOOK_TYPES = {"order": "ServiceRequest", "study": "ImagingStudy",
                 "report": "DiagnosticReport", "patient": "Patient"}

ORDER_STATUS = {"draft": "In Review", "active": "In Process", "on-hold": "On Hold",
                "completed": "Completed", "revoked": "Cancelled",
                "entered-in-error": "Entered in error", "unknown": "Unknown"}
REPORT_STATUS = {"registered": "Draft", "partial": "Draft", "unknown": "Draft",
                 "preliminary": "Preliminary", "final": "Final",
                 "amended": "Amended", "corrected": "Amended", "appended": "Amended",
                 "cancelled": "Cancelled", "entered-in-error": "Entered in error"}

app = Flask(__name__)
_lock = threading.Lock()
_stats = {"webhooks": Counter(), "last_webhook": None, "syncs": 0, "last_sync": None,
          "last_sync_secs": None, "last_sync_changes": 0, "fhir_errors": 0}
_errors: deque = deque(maxlen=50)
_lags: deque = deque(maxlen=200)   # seconds from AdvaPACS lastUpdated to our fetch, per webhook


# ── Storage ───────────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS resources (
            rtype TEXT, rid TEXT, status TEXT, last_updated TEXT, fetched_at TEXT, json TEXT,
            PRIMARY KEY (rtype, rid));
        CREATE TABLE IF NOT EXISTS links (
            rtype TEXT, rid TEXT, accession TEXT, PRIMARY KEY (rtype, rid, accession));
        CREATE INDEX IF NOT EXISTS links_acc ON links (accession);
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, source TEXT, kind TEXT,
            rtype TEXT, rid TEXT, accession TEXT, detail TEXT, raw TEXT);
        CREATE INDEX IF NOT EXISTS events_acc ON events (accession);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_event(c, source, kind, rtype="", rid="", accession="", detail="", raw=None):
    c.execute("INSERT INTO events (ts, source, kind, rtype, rid, accession, detail, raw) "
              "VALUES (?,?,?,?,?,?,?,?)",
              (now_iso(), source, kind, rtype, rid, accession, detail,
               json.dumps(raw) if raw is not None else None))


# ── FHIR ──────────────────────────────────────────────────────────────────────

def _headers():
    return {"Authorization": f"ID={FHIR_ID},Secret={FHIR_SEC}", "Accept": "application/fhir+json"}


def fhir_get(path: str, **params):
    try:
        r = requests.get(f"{FHIR_BASE}/{path.lstrip('/')}", params=params or None,
                         headers=_headers(), timeout=20)
    except Exception as e:
        _stats["fhir_errors"] += 1
        _errors.appendleft(f"{now_iso()} GET {path}: {e}")
        return None
    if r.status_code == 404:
        return {"_deleted": True}
    if not r.ok:
        _stats["fhir_errors"] += 1
        _errors.appendleft(f"{now_iso()} GET {path}: HTTP {r.status_code} {r.text[:150]}")
        return None
    return r.json()


def fhir_search(rtype: str, **params) -> list[dict]:
    out, url, first = [], f"{FHIR_BASE}/{rtype}", True
    while url:
        try:
            r = requests.get(url, params={"_count": "200", **params} if first else None,
                             headers=_headers(), timeout=30)
            r.raise_for_status()
        except Exception as e:
            _stats["fhir_errors"] += 1
            _errors.appendleft(f"{now_iso()} search {rtype}: {e}")
            break
        b = r.json()
        out += [e["resource"] for e in b.get("entry", []) if "resource" in e]
        url = next((l["url"] for l in b.get("link", []) if l.get("relation") == "next"), None)
        first = False
    return out


def cached(rtype: str, rid: str) -> dict:
    """Patient / Practitioner / Device: fetch once, keep."""
    if not rid:
        return {}
    with db() as c:
        row = c.execute("SELECT json FROM resources WHERE rtype=? AND rid=?", (rtype, rid)).fetchone()
        if row:
            return json.loads(row["json"])
    res = fhir_get(f"{rtype}/{rid}")
    if not res or res.get("_deleted"):
        return {}
    with db() as c:
        c.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?,?,?,?)",
                  (rtype, rid, "", res.get("meta", {}).get("lastUpdated", ""), now_iso(), json.dumps(res)))
    return res


def ref_id(ref: str) -> str:
    return (ref or "").rsplit("/", 1)[-1]


# ── Resource interpretation ──────────────────────────────────────────────────

def accession_of(res: dict) -> str:
    for i in res.get("identifier", []):
        codes = [c.get("code") for c in (i.get("type") or {}).get("coding", [])]
        if "ACSN" in codes or "accession" in (i.get("system") or "").lower():
            return i.get("value", "")
    return ""


def accessions_of(c, res: dict) -> list[str]:
    rt = res.get("resourceType")
    if rt in ("ServiceRequest", "ImagingStudy"):
        a = accession_of(res)
        return [a] if a else []
    if rt == "DiagnosticReport":
        accs = set()
        for ref in res.get("basedOn", []) + res.get("study", []):
            rtype, rid = (ref.get("reference", "").split("/", 1) + [""])[:2]
            for row in c.execute("SELECT accession FROM links WHERE rtype=? AND rid=?", (rtype, rid)):
                accs.add(row["accession"])
        return sorted(accs)
    return []


def status_of(res: dict) -> str:
    return res.get("status", "")


def concept_text(cc: dict) -> str:
    cc = cc or {}
    concept = cc.get("concept", cc)
    return (concept.get("text") or
            next((x.get("display", "") for x in concept.get("coding", [])), "") or "")


def station_aet(sr: dict) -> str:
    dev = cached("Device", ref_id((sr.get("performer") or [{}])[0].get("reference", "")))
    for i in dev.get("identifier", []):
        if any(c.get("code") == "110119" for c in (i.get("type") or {}).get("coding", [])):
            return i.get("value", "")
    return ""


def site_label(aet: str) -> str:
    if not aet:
        return ""
    if aet in SITE_AETS:
        return SITE_NAME
    return {"_01": "Oregon", "_02": "Wisconsin"}.get(aet[-3:], aet)


def person_name(rtype: str, ref: str) -> str:
    p = cached(rtype, ref_id(ref))
    n = (p.get("name") or [{}])[0]
    if n.get("text"):
        return n["text"]
    return " ".join(n.get("given", []) + [n.get("family", "")]).strip()


def report_label(dr: dict) -> str:
    st = dr.get("status", "")
    label = REPORT_STATUS.get(st, st or "—")
    if st == "final" and verifiers(dr):
        return "Verified"
    return label


def verifiers(dr: dict) -> list[str]:
    out = []
    for p in dr.get("performer", []):
        fn = [c.get("code") for e in p.get("extension", [])
              for c in (e.get("valueCodeableConcept") or {}).get("coding", [])]
        if "VRF" in fn and p.get("reference") not in out:
            out.append(p.get("reference"))
    return out


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest(res: dict, source: str) -> bool:
    """Store a fetched resource; record NEW / STATUS events. True if anything changed."""
    rt, rid = res.get("resourceType"), res.get("id")
    if rt not in TRACKED or not rid:
        return False
    st, lu = status_of(res), res.get("meta", {}).get("lastUpdated", "")
    with _lock, db() as c:
        old = c.execute("SELECT status, last_updated FROM resources WHERE rtype=? AND rid=?",
                        (rt, rid)).fetchone()
        c.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?,?,?,?)",
                  (rt, rid, st, lu, now_iso(), json.dumps(res)))
        accs = accessions_of(c, res)
        c.execute("DELETE FROM links WHERE rtype=? AND rid=?", (rt, rid))
        c.executemany("INSERT OR IGNORE INTO links VALUES (?,?,?)", [(rt, rid, a) for a in accs])
        acc = ",".join(accs)
        label = report_label(res) if rt == "DiagnosticReport" else st
        if old is None:
            kind = "BASELINE" if source == "initial-sync" else "NEW"
            add_event(c, source, kind, rt, rid, acc, f"{rt} {label}")
            return True
        if old["status"] != st:
            add_event(c, source, "STATUS", rt, rid, acc, f"{rt} {old['status']} → {st}"
                      + (f" ({label})" if rt == "DiagnosticReport" else ""))
            return True
        if old["last_updated"] != lu:
            add_event(c, source, "UPDATED", rt, rid, acc, f"{rt} updated, status {label}")
            return True
    return False


def handle_trigger(payload: dict):
    """A webhook forwarded by the sidecar: record it, then fetch what it names."""
    etype = payload.get("eventType") or payload.get("event") or "unknown"
    data = payload.get("data") or {}
    rtype = WEBHOOK_TYPES.get((data.get("type") or "").lower())
    rid = data.get("id", "")
    _stats["webhooks"][etype] += 1
    _stats["last_webhook"] = now_iso()
    with _lock, db() as c:
        acc = ",".join(r["accession"] for r in
                       c.execute("SELECT accession FROM links WHERE rtype=? AND rid=?", (rtype or "", rid)))
        add_event(c, "webhook", etype, rtype or data.get("type", ""), rid, acc,
                  f"webhook {etype}", raw=payload)
    if not rtype or not rid:
        return
    if rtype == "Patient":
        with db() as c:   # refresh the cached patient
            c.execute("DELETE FROM resources WHERE rtype='Patient' AND rid=?", (rid,))
        cached("Patient", rid)
        return
    res = fhir_get(f"{rtype}/{rid}")
    if res is None:
        return
    if res.get("_deleted"):
        with _lock, db() as c:
            add_event(c, "webhook", "DELETED", rtype, rid, acc, f"{rtype} no longer in AdvaPACS")
        return
    lu = res.get("meta", {}).get("lastUpdated")
    if lu:
        try:
            _lags.append((datetime.now(timezone.utc) - datetime.fromisoformat(lu.replace("Z", "+00:00"))).total_seconds())
        except ValueError:
            pass
    ingest(res, "webhook")


def sync(initial=False):
    t0 = time.time()
    with db() as c:
        row = c.execute("SELECT value FROM meta WHERE key='checkpoint'").fetchone()
    params = {}
    if row and not initial:
        since = datetime.fromisoformat(row["value"]) - timedelta(minutes=5)   # overlap
        params["_lastUpdated"] = "gt" + since.strftime("%Y-%m-%dT%H:%M:%SZ")
    started = datetime.now(timezone.utc)
    source = "initial-sync" if (initial and not row) else "sync"
    changes = 0
    if initial:   # names and station AEs, one search each instead of one GET per row
        with db() as c:
            for rt in ("Patient", "Practitioner", "Device"):
                for res in fhir_search(rt):
                    c.execute("INSERT OR REPLACE INTO resources VALUES (?,?,?,?,?,?)",
                              (rt, res["id"], "", res.get("meta", {}).get("lastUpdated", ""),
                               now_iso(), json.dumps(res)))
    # Orders and studies first: reports find their accessions through them.
    for rt in TRACKED:
        for res in fhir_search(rt, **params):
            changes += ingest(res, source)
    with db() as c:
        c.execute("INSERT OR REPLACE INTO meta VALUES ('checkpoint', ?)", (started.isoformat(),))
    _stats.update(syncs=_stats["syncs"] + 1, last_sync=now_iso(),
                  last_sync_secs=round(time.time() - t0, 1), last_sync_changes=changes)
    if changes:
        log.info(f"sync: {changes} change(s) in {time.time() - t0:.1f}s")


def sync_loop():
    try:
        sync(initial=True)
    except Exception as e:
        log.exception("initial sync failed")
        _errors.appendleft(f"{now_iso()} initial sync: {e}")
    while True:
        time.sleep(SYNC_SEC)
        try:
            sync()
        except Exception as e:
            log.exception("sync failed")
            _errors.appendleft(f"{now_iso()} sync: {e}")


# ── Views ─────────────────────────────────────────────────────────────────────

def load(rtype: str) -> dict[str, dict]:
    with db() as c:
        return {r["rid"]: json.loads(r["json"]) for r in
                c.execute("SELECT rid, json FROM resources WHERE rtype=?", (rtype,))}


def by_accession(rtype: str) -> dict[str, list[dict]]:
    res = load(rtype)
    out: dict[str, list[dict]] = {}
    with db() as c:
        for r in c.execute("SELECT rid, accession FROM links WHERE rtype=?", (rtype,)):
            if r["rid"] in res:
                out.setdefault(r["accession"], []).append(res[r["rid"]])
    return out


def series_summary(study: dict) -> list[dict]:
    out = []
    for s in study.get("series", []):
        mod = (s.get("modality") or {}).get("code") or \
              next((c.get("code") for c in (s.get("modality") or {}).get("coding", [])), "")
        out.append({"modality": mod, "n": s.get("numberOfInstances"),
                    "desc": s.get("description", ""),
                    "ai": "qxr" in (s.get("description", "") or "").lower() or mod in ("SR", "DOC") })
    return out


def build_rows() -> list[dict]:
    orders, studies, reports = load("ServiceRequest"), by_accession("ImagingStudy"), by_accession("DiagnosticReport")
    with db() as c:
        last = {r["accession"]: r["ts"] for r in c.execute(
            "SELECT accession, MAX(ts) ts FROM events WHERE accession<>'' GROUP BY accession")}
    rows, seen = [], set()
    for sr in orders.values():
        acc = accession_of(sr)
        if not acc:
            continue
        seen.add(acc)
        aet = station_aet(sr)
        pat = cached("Patient", ref_id(sr.get("subject", {}).get("reference", "")))
        rows.append(row_for(acc, sr, pat, aet, studies.get(acc, []), reports.get(acc, []), last.get(acc, "")))
    for acc, sts in studies.items():   # images without an order (e.g. Qure laptop pushes)
        if acc in seen:
            continue
        pat = cached("Patient", ref_id(sts[0].get("subject", {}).get("reference", "")))
        rows.append(row_for(acc, None, pat, "", sts, reports.get(acc, []), last.get(acc, "")))
    rows.sort(key=lambda r: r["sort"], reverse=True)
    return rows


def row_for(acc, sr, pat, aet, studies, reports, last_ts) -> dict:
    n = (pat.get("name") or [{}])[0]
    dr = max(reports, key=lambda r: r.get("meta", {}).get("lastUpdated", ""), default=None)
    series = [s for st in studies for s in series_summary(st)]
    when = (sr or {}).get("authoredOn") or (studies[0].get("started") if studies else "") or ""
    return {
        "accession": acc,
        "patient": f"{n.get('family', '')}, {' '.join(n.get('given', []))}".strip(", "),
        "patient_id": next((i.get("value") for i in pat.get("identifier", [])), ""),
        "procedure": concept_text(sr.get("code")) if sr else (studies[0].get("description", "") if studies else ""),
        "station": aet, "site": site_label(aet),
        "order_status": ORDER_STATUS.get(sr.get("status"), sr.get("status")) if sr else "No order",
        "order_raw": sr.get("status") if sr else "",
        "ordered": when[:16].replace("T", " "),
        "series": series,
        "report": report_label(dr) if dr else "",
        "radiologist": person_name("Practitioner", (dr.get("resultsInterpreter") or [{}])[0].get("reference", "")) if dr else "",
        "last": last_ts[:16].replace("T", " "),
        "sort": max(when, last_ts),
        "local": (not aet and not sr) or aet in SITE_AETS,
    }


@app.route("/")
def index():
    site = request.args.get("site", "local")
    view = request.args.get("view", "all")
    rows = build_rows()
    if site == "local":
        rows = [r for r in rows if r["local"]]
    counts = Counter(r["report"] or "Awaiting report" for r in rows)
    if view == "awaiting":
        rows = [r for r in rows if not r["report"]]
    elif view != "all":
        rows = [r for r in rows if r["report"].lower() == view]
    return render_template("index.html", rows=rows, site=site, view=view, counts=counts,
                           total=sum(counts.values()), site_name=SITE_NAME, stats=_stats)


@app.route("/a/<acc>")
def accession_view(acc):
    with db() as c:
        refs = c.execute("SELECT rtype, rid FROM links WHERE accession=?", (acc,)).fetchall()
        events = [dict(e) for e in c.execute(
            "SELECT * FROM events WHERE accession=? OR accession LIKE ? OR accession LIKE ? "
            "OR accession LIKE ? ORDER BY id", (acc, f"{acc},%", f"%,{acc}", f"%,{acc},%"))]
    if not refs:
        abort(404)
    res = {}
    with db() as c:
        for r in refs:
            row = c.execute("SELECT json FROM resources WHERE rtype=? AND rid=?", (r["rtype"], r["rid"])).fetchone()
            if row:
                res.setdefault(r["rtype"], []).append(json.loads(row["json"]))
    sr = (res.get("ServiceRequest") or [None])[0]
    studies, reports = res.get("ImagingStudy", []), res.get("DiagnosticReport", [])
    prev = None
    for e in events:   # time since the previous event
        t = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        e["delta"] = "" if prev is None else fmt_delta((t - prev).total_seconds())
        prev = t
        e["raw_pretty"] = json.dumps(json.loads(e["raw"]), indent=2) if e["raw"] else ""
    report_views = []
    for dr in reports:
        full = fhir_get(f"DiagnosticReport/{dr['id']}") or dr   # presentedForm data only on a single read
        html = ""
        for pf in full.get("presentedForm", []):
            if pf.get("data") and pf.get("contentType", "").startswith(("text/html", "text/plain")):
                text = base64.b64decode(pf["data"]).decode("utf-8", "replace")
                html = text if pf["contentType"].startswith("text/html") else f"<pre>{text}</pre>"
                break
        report_views.append({
            "id": dr["id"], "label": report_label(full), "status": full.get("status"),
            "issued": (full.get("issued") or "")[:19].replace("T", " "),
            "interpreters": [person_name("Practitioner", p.get("reference", "")) for p in full.get("resultsInterpreter", [])],
            "verifiers": [person_name("Practitioner", r) for r in verifiers(full)],
            "forms": [pf.get("contentType") for pf in full.get("presentedForm", [])],
            "html": html, "json": json.dumps(full, indent=2)[:20000],
        })
    study_views = [{
        "uid": next((i.get("value", "").removeprefix("urn:oid:") for i in st.get("identifier", [])
                     if i.get("system") == "urn:dicom:uid"), ""),
        "status": st.get("status"), "started": (st.get("started") or "")[:19].replace("T", " "),
        "series": series_summary(st), "json": json.dumps(st, indent=2)[:20000]} for st in studies]
    pat = cached("Patient", ref_id(((sr or (studies or [{}])[0]) or {}).get("subject", {}).get("reference", "")))
    n = (pat.get("name") or [{}])[0]
    return render_template(
        "accession.html", acc=acc, events=events, reports=report_views, studies=study_views,
        order=sr, order_json=json.dumps(sr, indent=2) if sr else "",
        order_label=ORDER_STATUS.get((sr or {}).get("status"), (sr or {}).get("status", "No order")),
        procedure=concept_text(sr.get("code")) if sr else "",
        station=station_aet(sr) if sr else "",
        patient=f"{n.get('family', '')}, {' '.join(n.get('given', []))}".strip(", "),
        patient_id=next((i.get("value") for i in pat.get("identifier", [])), ""),
        ohif_host=request.host.replace("reports.", "ohif.", 1) if request.host.startswith("reports.") else "",
        site_name=SITE_NAME)


def fmt_delta(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"+{s}s"
    if s < 3600:
        return f"+{s // 60}m {s % 60:02d}s"
    if s < 86400:
        return f"+{s // 3600}h {s % 3600 // 60:02d}m"
    return f"+{s // 86400}d {s % 86400 // 3600}h"


@app.route("/events")
def events_view():
    with db() as c:
        events = [dict(e) for e in c.execute("SELECT * FROM events ORDER BY id DESC LIMIT 300")]
        counts = {r["rtype"]: r["n"] for r in c.execute("SELECT rtype, COUNT(*) n FROM resources GROUP BY rtype")}
    for e in events:
        e["raw_pretty"] = json.dumps(json.loads(e["raw"]), indent=2) if e["raw"] else ""
    lags = sorted(_lags)
    lag = {"n": len(lags), "median": round(lags[len(lags) // 2], 1) if lags else None,
           "max": round(lags[-1], 1) if lags else None}
    return render_template("events.html", events=events, stats=_stats, errors=list(_errors),
                           counts=counts, lag=lag, sync_sec=SYNC_SEC, fhir_base=FHIR_BASE,
                           site_aets=sorted(SITE_AETS), site_name=SITE_NAME)


@app.route("/trigger", methods=["POST"])
def trigger():
    payload = request.get_json(force=True, silent=True) or {}
    threading.Thread(target=handle_trigger, args=(payload,), daemon=True).start()
    return jsonify({"ok": True}), 202


@app.route("/sync", methods=["POST"])
def sync_now():
    threading.Thread(target=sync, daemon=True).start()
    return jsonify({"ok": True}), 202


@app.route("/status")
def status():
    return jsonify({"ok": True, **{k: v for k, v in _stats.items() if k != "webhooks"},
                    "webhooks": dict(_stats["webhooks"])})


if __name__ == "__main__":
    init_db()
    threading.Thread(target=sync_loop, daemon=True).start()
    from waitress import serve
    log.info(f"Report console on :{PORT}  FHIR={FHIR_BASE}  site AETs={sorted(SITE_AETS)}  sync every {SYNC_SEC}s")
    serve(app, host="0.0.0.0", port=PORT, threads=8)
