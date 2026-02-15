from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import threading
import traceback

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.refresh_pipeline import run_refresh

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNTIME_DIR = DATA_DIR / "runtime"
LATEST_REL_FILE = DATA_DIR / "latest_relationships.json"
LATEST_NODES_FILE = DATA_DIR / "latest_nodes.json"
MAJOR_COMPANIES_FILE = ROOT / "major_companies.txt"
COMPANY_CATALOG_FILE = ROOT / "company_catalog.json"
LOG_FILE = RUNTIME_DIR / "refresh.log"
STATUS_FILE = RUNTIME_DIR / "refresh_status.json"

RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()

_job_lock = threading.Lock()
_status = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "exit_code": None,
}
_NON_COMPANY_ENTITY_TERMS = {"chatgpt", "gpt-4", "gpt 4", "gpt-4o", "claude", "gemini", "copilot", "assistant"}


def _is_company_like(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered:
        return False
    if lowered in _NON_COMPANY_ENTITY_TERMS:
        return False
    return True


def _infer_node_meta(name: str) -> dict:
    lowered = name.strip().lower()
    if any(k in lowered for k in ("openai", "anthropic", "perplexity", "xai", "hugging face", "mistral")):
        return {"sector": "ai", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("paypal", "stripe", "adyen", "klarna", "visa", "mastercard", "afterpay")):
        return {"sector": "payments", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("fedex", "ups", "dhl", "maersk", "shipbob", "flexport", "fulfillment")):
        return {"sector": "logistics_fulfillment", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("salesforce", "adobe", "oracle", "sap", "servicenow", "hubspot")):
        return {"sector": "enterprise_software", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("meta", "tiktok", "pinterest", "snap")):
        return {"sector": "social_commerce", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("expedia", "booking", "airbnb", "trip", "hopper", "traveloka")):
        return {"sector": "travel_agency", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("quora", "reddit", "stack overflow", "stackoverflow", "q&a")):
        return {"sector": "qa_platform", "is_ecommerce": False, "source": "api_inference"}
    if any(k in lowered for k in ("instacart", "doordash", "uber eats", "delivery hero", "aggregator")):
        return {"sector": "aggregator", "is_ecommerce": True, "source": "api_inference"}
    if any(k in lowered for k in ("shop", "store", "market", "mart", "commerce")):
        return {"sector": "specialized_ecommerce", "is_ecommerce": True, "source": "api_inference"}
    return {"sector": "enabler", "is_ecommerce": False, "source": "api_inference"}


def _save_status() -> None:
    STATUS_FILE.write_text(json.dumps(_status, indent=2), encoding="utf-8")


def _read_json(path: pathlib.Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _tail_log(max_chars: int = 12000) -> str:
    if not LOG_FILE.exists():
        return ""
    text = LOG_FILE.read_text(encoding="utf-8", errors="ignore")
    return text[-max_chars:]


def _refresh_job() -> None:
    try:
        with LOG_FILE.open("w", encoding="utf-8") as lf:
            lf.write("Starting refresh...\n")
        run_refresh()
        _status["exit_code"] = 0
        _status["error"] = None
    except Exception as exc:
        _status["exit_code"] = 1
        _status["error"] = str(exc)
        with LOG_FILE.open("a", encoding="utf-8") as lf:
            lf.write("\nERROR:\n")
            lf.write(traceback.format_exc())
    finally:
        _status["running"] = False
        _status["finished_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        _save_status()


@app.get("/api/data")
def api_data():
    relationships_raw = _read_json(LATEST_REL_FILE, {"relationships": []}).get("relationships", [])
    relationships = [
        r
        for r in relationships_raw
        if _is_company_like(str(r.get("source_actor", ""))) and _is_company_like(str(r.get("target_actor", "")))
    ]
    latest_nodes_payload = _read_json(LATEST_NODES_FILE, {"nodes": [], "node_meta": {}})
    nodes = set(latest_nodes_payload.get("nodes", []))
    node_meta = latest_nodes_payload.get("node_meta", {})
    if not isinstance(node_meta, dict):
        node_meta = {}
    if MAJOR_COMPANIES_FILE.exists():
        for ln in MAJOR_COMPANIES_FILE.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                nodes.add(ln)
    catalog = _read_json(COMPANY_CATALOG_FILE, {"companies": []})
    for item in catalog.get("companies", []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        nodes.add(name)
        node_meta.setdefault(
            name,
            {
                "sector": str(item.get("sector", "enabler")).strip() or "enabler",
                "is_ecommerce": bool(item.get("is_ecommerce", False)),
                "source": "seed_catalog",
            },
        )
    if not nodes:
        for r in relationships:
            if r.get("source_actor"):
                nodes.add(r["source_actor"])
            if r.get("target_actor"):
                nodes.add(r["target_actor"])
    for n in nodes:
        node_meta.setdefault(n, _infer_node_meta(n))
    return {"rows": relationships, "nodes": sorted(nodes), "node_meta": node_meta}


@app.get("/api/refresh_status")
def api_refresh_status():
    payload = dict(_status)
    payload["log_tail"] = _tail_log()
    return payload


@app.post("/api/refresh")
def api_refresh():
    if not os.environ.get("CEREBRAS_API_KEY", "").strip():
        raise HTTPException(status_code=400, detail="CEREBRAS_API_KEY is not set in server environment.")
    with _job_lock:
        if _status["running"]:
            return JSONResponse(status_code=202, content={"ok": True, "message": "Refresh already running."})
        _status["running"] = True
        _status["started_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        _status["finished_at"] = None
        _status["error"] = None
        _status["exit_code"] = None
        _save_status()
        t = threading.Thread(target=_refresh_job, daemon=True)
        t.start()
    return JSONResponse(status_code=202, content={"ok": True, "message": "Refresh started."})


app.mount("/", StaticFiles(directory=str(ROOT / "ui"), html=True), name="ui")

