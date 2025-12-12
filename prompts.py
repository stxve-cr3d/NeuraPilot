from __future__ import annotations
from pathlib import Path
import json
import re
import time
from typing import Any, Dict, Tuple

BASE_DIR = Path(__file__).resolve().parent
PROMPT_DIR = BASE_DIR / "prompts"
CLIENTS_PATH = BASE_DIR / "clients.json"

SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,40}$")

# --- tiny file cache (mtime-based) ---
_file_cache: Dict[str, Tuple[float, str]] = {}
_json_cache: Tuple[float, Dict[str, Any]] | None = None

def _read_text_cached(path: Path) -> str:
    key = str(path)
    mtime = path.stat().st_mtime
    cached = _file_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    text = path.read_text(encoding="utf-8")
    _file_cache[key] = (mtime, text)
    return text

def _read_json_cached(path: Path) -> Dict[str, Any]:
    global _json_cache
    mtime = path.stat().st_mtime
    if _json_cache and _json_cache[0] == mtime:
        return _json_cache[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _json_cache = (mtime, data)
    return data

def load_clients() -> Dict[str, Any]:
    return _read_json_cached(CLIENTS_PATH)

def get_client_id(raw: str | None) -> str:
    if not raw:
        return "default"
    raw = raw.strip()
    if SAFE_ID.match(raw):
        return raw
    return "default"

def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dict b into a (non-destructive)."""
    out = dict(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out

def resolve_placeholders(text: str, *, demo_link: str, brand_name: str) -> str:
    return (
        text.replace("{{DEMO_LINK}}", demo_link)
            .replace("{{BRAND_NAME}}", brand_name)
            .strip()
    )

def load_prompt_bundle(client_id: str, *, demo_link: str, brand_name: str) -> str:
    """
    Compose: core.txt + optional <client_id>.txt + optional agency_sales.txt based on client.
    """
    core = _read_text_cached(PROMPT_DIR / "core.txt")

    parts = [core]

    # if a client-specific prompt exists, include it
    if client_id != "default":
        p = PROMPT_DIR / f"{client_id}.txt"
        if p.exists():
            parts.append(_read_text_cached(p))

    # always include the agency module for default + agency unless overridden
    # (you can change this logic later)
    if (PROMPT_DIR / "agency_sales.txt").exists():
        parts.append(_read_text_cached(PROMPT_DIR / "agency_sales.txt"))

    full = "\n\n".join(parts)
    return resolve_placeholders(full, demo_link=demo_link, brand_name=brand_name)