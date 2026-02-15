from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import ssl
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

from cerebras.cloud.sdk import Cerebras

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
RUNTIME_DIR = DATA_DIR / "runtime"
MAJOR_COMPANIES_FILE = ROOT / "major_companies.txt"
COMPANY_CATALOG_FILE = ROOT / "company_catalog.json"
LATEST_REL_FILE = DATA_DIR / "latest_relationships.json"
LATEST_NODES_FILE = DATA_DIR / "latest_nodes.json"
STATE_FILE = DATA_DIR / "persistent_state.json"
SEARCH_HISTORY_FILE = DATA_DIR / "search_history.jsonl"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

REL_TYPES = {
    "acquires",
    "partners_with",
    "integrates_with",
    "uses_services_of",
    "powers",
    "invests_in",
}

REL_SIGNAL = re.compile(
    r"\b(partners? with|partnership|integrat(?:e|es|ed|ion)|acquir(?:e|es|ed|ing|er)|"
    r"invest(?:s|ed|ment)|powered by|powers|uses?)\b",
    re.I,
)
NON_COMPANY_TERMS = {
    "report",
    "survey",
    "article",
    "website",
    "industry",
    "retail media",
    "chatgpt",
    "ecommerce",
}
NON_COMPANY_ENTITIES = {
    "chatgpt",
    "gpt-4",
    "gpt 4",
    "gpt-4o",
    "claude",
    "gemini",
    "copilot",
    "assistant",
    "api",
    "sdk",
    "llm",
}
ALLOWED_SECTORS = {
    "general_ecommerce",
    "specialized_ecommerce",
    "aggregator",
    "travel_agency",
    "qa_platform",
    "ai",
    "payments",
    "enabler",
    "enterprise_software",
    "logistics_fulfillment",
    "social_commerce",
}


def _looks_non_company(name: str) -> bool:
    lowered = re.sub(r"\s+", " ", name.strip().lower())
    if not lowered:
        return True
    if lowered in NON_COMPANY_ENTITIES:
        return True
    if lowered in NON_COMPANY_TERMS:
        return True
    if len(lowered) < 2:
        return True
    if re.search(r"\b(report|survey|article|index|industry|website)\b", lowered):
        return True
    if re.search(r"\b(tool|feature|model|assistant|plugin|extension|api|sdk)\b", lowered):
        return True
    return False


def utc_now() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def log(msg: str) -> None:
    print(f"[{utc_now()}] {msg}", flush=True)


def _ensure_dirs() -> None:
    for p in (DATA_DIR, CACHE_DIR, RUNTIME_DIR, SNAPSHOT_DIR):
        p.mkdir(parents=True, exist_ok=True)


def _read_json(path: pathlib.Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: pathlib.Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_jsonl(path: pathlib.Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def read_seed_companies() -> list[str]:
    if COMPANY_CATALOG_FILE.exists():
        payload = _read_json(COMPANY_CATALOG_FILE, {"companies": []})
        out = []
        for item in payload.get("companies", []):
            name = str(item.get("name", "")).strip()
            if name:
                out.append(name)
        if out:
            return out
    if not MAJOR_COMPANIES_FILE.exists():
        return []
    return [
        line.strip()
        for line in MAJOR_COMPANIES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def read_company_metadata() -> dict[str, dict[str, Any]]:
    payload = _read_json(COMPANY_CATALOG_FILE, {"companies": []})
    meta: dict[str, dict[str, Any]] = {}
    for item in payload.get("companies", []):
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        meta[name] = {
            "sector": str(item.get("sector", "enabler")).strip() or "enabler",
            "is_ecommerce": bool(item.get("is_ecommerce", False)),
            "source": "seed_catalog",
        }
    return meta


def infer_node_meta(name: str) -> dict[str, Any]:
    lowered = name.strip().lower()
    if any(k in lowered for k in ("openai", "anthropic", "perplexity", "xai", "hugging face", "mistral")):
        return {"sector": "ai", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("paypal", "stripe", "adyen", "klarna", "visa", "mastercard", "afterpay")):
        return {"sector": "payments", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("fedex", "ups", "dhl", "maersk", "shipbob", "flexport", "fulfillment")):
        return {"sector": "logistics_fulfillment", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("salesforce", "adobe", "oracle", "sap", "servicenow", "hubspot")):
        return {"sector": "enterprise_software", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("meta", "tiktok", "pinterest", "snap")):
        return {"sector": "social_commerce", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("expedia", "booking", "airbnb", "trip", "hopper", "traveloka")):
        return {"sector": "travel_agency", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("quora", "reddit", "stack overflow", "stackoverflow", "q&a")):
        return {"sector": "qa_platform", "is_ecommerce": False, "source": "name_inference"}
    if any(k in lowered for k in ("instacart", "doordash", "uber eats", "delivery hero", "aggregator")):
        return {"sector": "aggregator", "is_ecommerce": True, "source": "name_inference"}
    if any(k in lowered for k in ("shop", "store", "market", "mart", "commerce")):
        return {"sector": "specialized_ecommerce", "is_ecommerce": True, "source": "name_inference"}
    return {"sector": "enabler", "is_ecommerce": False, "source": "name_inference"}


def llm_classify_company(company: str, model: str) -> dict[str, Any]:
    key = hashlib.sha1(f"c|{company}|{model}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if isinstance(cached, dict):
        sector = str(cached.get("sector", "other")).strip()
        if sector in ALLOWED_SECTORS:
            return {
                "sector": sector,
                "is_ecommerce": bool(cached.get("is_ecommerce", False)),
                "source": str(cached.get("source", "llm_cached")),
            }

    snippets = []
    try:
        for item in fetch_rss(f'"{company}" company business model', days=3650, max_per_query=2):
            snippets.append(f"- {item.get('title','')} | {item.get('description','')}")
    except Exception:
        snippets = []
    context = "\n".join(snippets[:2]) if snippets else "- No web snippets available"

    system = "Classify company into one market sector and ecommerce boolean. Return strict JSON only."
    user = f"""Return JSON:
{{
                "sector": "general_ecommerce|specialized_ecommerce|aggregator|travel_agency|qa_platform|ai|payments|enabler|enterprise_software|logistics_fulfillment|social_commerce",
  "is_ecommerce": true,
  "confidence": 0.0
}}
Company: {company}
Context:
{context}
Rules:
- Choose one sector only from allowed list
- Use best-fit classification
- If uncertain, choose 'enabler'"""
    result = cerebras_json(system, user, model)
    sector = str(result.get("sector", "enabler")).strip()
    is_ecommerce = bool(result.get("is_ecommerce", False))
    try:
        confidence = float(result.get("confidence", 0))
    except Exception:
        confidence = 0.0
    if sector not in ALLOWED_SECTORS or confidence < 0.55:
        inferred = infer_node_meta(company)
        _cache_set(key, inferred)
        return inferred
    payload = {"sector": sector, "is_ecommerce": is_ecommerce, "source": "llm_profile_search"}
    _cache_set(key, payload)
    return payload


def llm_is_company_entity(name: str, model: str) -> bool:
    if _looks_non_company(name):
        return False
    key = hashlib.sha1(f"v|{name}|{model}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if isinstance(cached, bool):
        return cached
    if isinstance(cached, dict) and "is_company" in cached:
        return bool(cached.get("is_company", False))

    snippets = []
    try:
        for item in fetch_rss(f'"{name}" company', days=3650, max_per_query=2):
            snippets.append(f"- {item.get('title','')} | {item.get('description','')}")
    except Exception:
        snippets = []
    context = "\n".join(snippets[:2]) if snippets else "- No web snippets available"

    system = "Determine if the entity name is an actual company/legal entity. Return strict JSON."
    user = f"""Return JSON:
{{
  "is_company": true,
  "confidence": 0.0
}}
Entity: {name}
Context:
{context}
Rules:
- A product/model/tool/assistant is NOT a company
- Return false if uncertain"""
    result = cerebras_json(system, user, model)
    is_company = bool(result.get("is_company", False))
    try:
        confidence = float(result.get("confidence", 0))
    except Exception:
        confidence = 0.0
    final = bool(is_company and confidence >= 0.6)
    _cache_set(key, {"is_company": final, "confidence": confidence, "source": "llm_company_validation"})
    return final


def _google_rss_url(query: str, days: int) -> str:
    params = {"q": f"{query} when:{days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _normalize_pub_date(pub_date: str) -> str:
    if not pub_date:
        return dt.date.today().isoformat()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return dt.datetime.strptime(pub_date, fmt).date().isoformat()
        except ValueError:
            pass
    return dt.date.today().isoformat()


def fetch_rss(query: str, days: int, max_per_query: int) -> list[dict[str, str]]:
    req = urllib.request.Request(_google_rss_url(query, days), headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_bytes = resp.read()
    except Exception:
        context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=20, context=context) as resp:
            xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    out: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:max_per_query]:
        source = ""
        source_el = item.find("{http://search.yahoo.com/mrss/}source")
        if source_el is not None and source_el.text:
            source = source_el.text.strip()
        out.append(
            {
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "description": _clean_html(item.findtext("description") or ""),
                "publisher": source,
                "announcement_date": _normalize_pub_date(item.findtext("pubDate") or ""),
            }
        )
    return out


def cerebras_json(system_prompt: str, user_prompt: str, model: str) -> dict[str, Any]:
    api_key = (os.environ.get("CEREBRAS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("CEREBRAS_API_KEY is required")

    client = Cerebras(api_key=api_key)
    completion = client.chat.completions.create(
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        model=model,
        max_completion_tokens=1000,
        temperature=0.2,
        top_p=1,
        stream=False,
    )
    content = (completion.choices[0].message.content or "").strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def _cache_get(cache_key: str) -> Any:
    path = CACHE_DIR / f"{cache_key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_set(cache_key: str, payload: Any) -> None:
    (CACHE_DIR / f"{cache_key}.json").write_text(json.dumps(payload), encoding="utf-8")


def llm_queries(company: str, known_nodes: list[str], model: str, max_queries: int) -> list[str]:
    key = hashlib.sha1(f"q|{company}|{model}|{','.join(known_nodes[:80])}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if isinstance(cached, list) and cached:
        return cached[:max_queries]

    system = "Generate focused web search queries to find explicit business relationships."
    user = f"""Return JSON: {{"queries":["..."]}}
Focus company: {company}
Known graph nodes: {json.dumps(known_nodes[:120])}
Rules:
- Return 1 to {max_queries} concise queries
- Prioritize ecommerce, payments, retail, shopping, fulfillment, agentic commerce
- Target explicit relationships: partnership, integration, acquisition, investment, powering, usage
- Avoid stock/earnings style queries"""
    result = cerebras_json(system, user, model)
    queries = [str(q).strip() for q in (result.get("queries") or []) if str(q).strip()]
    if not queries:
        queries = [f"{company} ecommerce partnership"]
    queries = queries[:max_queries]
    _cache_set(key, queries)
    return queries


def llm_extract(article: dict[str, str], focus_company: str, known_nodes: list[str], model: str) -> list[dict[str, Any]]:
    key_input = f"e|{focus_company}|{model}|{article.get('link')}|{article.get('title')}|{article.get('description')}"
    key = hashlib.sha1(key_input.encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if isinstance(cached, list):
        return cached

    system = "Extract only explicit company-to-company business relationships. Return strict JSON."
    user = f"""Return JSON:
{{
  "relationships": [
    {{
      "source_actor": "Company A",
      "target_actor": "Company B",
      "relationship_type": "acquires|partners_with|integrates_with|uses_services_of|powers|invests_in",
      "is_direct_relationship": true,
      "explicit": true,
      "confidence": 0.0,
      "evidence_quote": "short quote from title/description"
    }}
  ]
}}

Focus company: {focus_company}
Known nodes: {json.dumps(known_nodes[:220])}
Title: {article.get("title","")}
Description: {article.get("description","")}
Rules:
- No co-mentions
- Include only explicit relationship claims in title/description
- Use company names only
- If two entities are just mentioned in the same report/site with no direct business tie, return nothing
- Return empty list when uncertain"""

    result = cerebras_json(system, user, model)
    relationships = result.get("relationships") if isinstance(result, dict) else []
    if not isinstance(relationships, list):
        relationships = []
    _cache_set(key, relationships)
    return relationships


def _valid_rel(raw: dict[str, Any]) -> dict[str, str] | None:
    src = str(raw.get("source_actor", "")).strip()
    tgt = str(raw.get("target_actor", "")).strip()
    rel_type = str(raw.get("relationship_type", "")).strip()
    is_direct = bool(raw.get("is_direct_relationship", False))
    explicit = bool(raw.get("explicit", False))
    try:
        confidence = float(raw.get("confidence", 0))
    except Exception:
        confidence = 0.0
    if not src or not tgt or src == tgt:
        return None
    if _looks_non_company(src) or _looks_non_company(tgt):
        return None
    if rel_type not in REL_TYPES:
        return None
    if not is_direct or not explicit or confidence < 0.7:
        return None
    return {"source_actor": src, "target_actor": tgt, "relationship_type": rel_type}


def _edge_id(src: str, tgt: str, rel_type: str, source_url: str) -> str:
    digest = hashlib.sha1(f"{src}|{tgt}|{rel_type}|{source_url}".encode("utf-8")).hexdigest()[:14]
    return f"E{digest}"


def run_refresh(
    *,
    days: int = 120,
    max_per_query: int = 4,
    expansion_rounds: int = 1,
    max_queries_per_node: int = 2,
    llm_model: str = "llama3.1-8b",
) -> dict[str, Any]:
    _ensure_dirs()
    state = _read_json(STATE_FILE, {"known_nodes": [], "seen_urls": []})

    seeds = read_seed_companies()
    seed_signature = hashlib.sha1("|".join(sorted(seeds)).encode("utf-8")).hexdigest()
    if state.get("seed_signature") != seed_signature:
        state["known_nodes"] = []
        state["seen_urls"] = []
        state["seed_signature"] = seed_signature
        log("seed catalog changed: resetting cached node/url state")
    node_meta = read_company_metadata()
    known_nodes: set[str] = set(seeds)
    seen_urls: set[str] = set(state.get("seen_urls", []))
    frontier: set[str] = set(seeds)
    seen_edges: set[tuple[str, str, str, str]] = set()
    rows: list[dict[str, str]] = []
    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    log(
        f"run={run_id} start seeds={len(seeds)} days={days} max_per_query={max_per_query} "
        f"rounds={expansion_rounds} queries_per_node={max_queries_per_node} model={llm_model}"
    )

    for round_idx in range(max(1, expansion_rounds)):
        if not frontier:
            break
        next_frontier: set[str] = set()
        log(f"run={run_id} round={round_idx+1} frontier={len(frontier)}")
        for company in sorted(frontier):
            try:
                queries = llm_queries(company, sorted(known_nodes), llm_model, max_queries_per_node)
            except Exception as exc:
                log(f"run={run_id} query_generation_failed company={company} err={exc}")
                queries = [f"{company} ecommerce partnership"]
            log(f"run={run_id} company={company} queries={len(queries)}")
            for query in queries:
                _append_jsonl(
                    SEARCH_HISTORY_FILE,
                    {"ts": utc_now(), "run_id": run_id, "company": company, "query": query, "event": "query"},
                )
                try:
                    articles = fetch_rss(query, days, max_per_query)
                except Exception as exc:
                    log(f"run={run_id} rss_failed query={query!r} err={exc}")
                    continue
                _append_jsonl(
                    SEARCH_HISTORY_FILE,
                    {
                        "ts": utc_now(),
                        "run_id": run_id,
                        "company": company,
                        "query": query,
                        "event": "fetched",
                        "article_count": len(articles),
                    },
                )
                log(f"run={run_id} query={query!r} articles={len(articles)}")
                for article in articles:
                    url = article.get("link", "")
                    if not url or url in seen_urls:
                        continue
                    combined_text = f"{article.get('title','')} {article.get('description','')}"
                    if not REL_SIGNAL.search(combined_text):
                        continue
                    seen_urls.add(url)
                    try:
                        raw_relationships = llm_extract(article, company, sorted(known_nodes), llm_model)
                    except Exception as exc:
                        log(f"run={run_id} extraction_failed url={url!r} err={exc}")
                        continue
                    for raw in raw_relationships:
                        rel = _valid_rel(raw)
                        if rel is None:
                            continue
                        src = rel["source_actor"]
                        tgt = rel["target_actor"]
                        if not llm_is_company_entity(src, llm_model) or not llm_is_company_entity(tgt, llm_model):
                            continue
                        if src not in known_nodes and tgt not in known_nodes:
                            continue
                        if src not in known_nodes:
                            known_nodes.add(src)
                            next_frontier.add(src)
                            node_meta.setdefault(src, llm_classify_company(src, llm_model))
                        if tgt not in known_nodes:
                            known_nodes.add(tgt)
                            next_frontier.add(tgt)
                            node_meta.setdefault(tgt, llm_classify_company(tgt, llm_model))
                        edge_key = (src, tgt, rel["relationship_type"], url)
                        if edge_key in seen_edges:
                            continue
                        seen_edges.add(edge_key)
                        rows.append(
                            {
                                "id": _edge_id(src, tgt, rel["relationship_type"], url),
                                "source_actor": src,
                                "target_actor": tgt,
                                "relationship_type": rel["relationship_type"],
                                "announcement_date": article.get("announcement_date", dt.date.today().isoformat()),
                                "source_url": url,
                                "source_title": article.get("title", ""),
                                "publisher": article.get("publisher", ""),
                            }
                        )
                        log(
                            f"run={run_id} edge_added src={src!r} tgt={tgt!r} "
                            f"type={rel['relationship_type']!r}"
                        )
        frontier = next_frontier

    rows.sort(key=lambda r: (r["announcement_date"], r["id"]), reverse=True)
    payload_rel = {"updated_at": utc_now(), "relationships": rows}
    payload_nodes = {"updated_at": utc_now(), "nodes": sorted(known_nodes), "node_meta": node_meta}
    _write_json(LATEST_REL_FILE, payload_rel)
    _write_json(LATEST_NODES_FILE, payload_nodes)
    _write_json(
        SNAPSHOT_DIR / f"relationships_{run_id}.json",
        {"updated_at": utc_now(), "relationships": rows, "nodes": sorted(known_nodes)},
    )
    state["known_nodes"] = sorted(known_nodes)
    state["seen_urls"] = sorted(seen_urls)[-20000:]
    state["seed_signature"] = seed_signature
    _write_json(STATE_FILE, state)
    log(f"run={run_id} completed relationships={len(rows)} nodes={len(known_nodes)}")
    return {"relationships": rows, "nodes": sorted(known_nodes)}

