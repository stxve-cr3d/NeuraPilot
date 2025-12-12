import os
import re
import json
import time
import base64
from urllib.parse import urlparse
from typing import Any, Dict, List
import smtplib
from email.message import EmailMessage
import secrets
from pathlib import Path
from flask import Flask, request, jsonify, render_template, make_response, g, Response
from dotenv import load_dotenv
from openai import OpenAI

from prompts import load_clients, get_client_id, merge, load_prompt_bundle
from db import connect, init_db, insert_event, insert_lead, list_leads, stats
import stripe

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY","")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET","")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL","http://127.0.0.1:8000")

stripe.api_key = STRIPE_SECRET_KEY

PRICE_MAP = {
  "starter": os.getenv("STRIPE_PRICE_STARTER",""),
  "growth": os.getenv("STRIPE_PRICE_GROWTH",""),
  "pro": os.getenv("STRIPE_PRICE_PRO",""),
}


load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENTS_PATH = Path(BASE_DIR) / "clients.json"
PROMPTS_DIR = Path(BASE_DIR) / "prompts"
CLIENT_TEMPLATE_PATH = PROMPTS_DIR / "client_template.txt"

def public_config(cfg: dict) -> dict:
    # remove secrets before sending to browser
    clean = json.loads(json.dumps(cfg))
    for k in ("widget_key", "allowed_domains", "webhook_url", "lead_email_to"):
        clean.pop(k, None)
    return clean

def load_clients_file() -> dict:
    return json.loads(CLIENTS_PATH.read_text(encoding="utf-8"))

def write_clients_file_atomic(data: dict) -> None:
    tmp = CLIENTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CLIENTS_PATH)

# lock for safe writes (macOS/Linux)
try:
    import fcntl
except Exception:
    fcntl = None

def with_clients_lock(fn):
    lock_path = Path(BASE_DIR) / ".clients.lock"
    with open(lock_path, "w") as lock_file:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            except Exception:
                pass
        return fn()

CLIENT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{2,40}$")

def validate_client_id(raw: str) -> str | None:
    raw = (raw or "").strip()
    if not CLIENT_ID_RE.match(raw):
        return None
    if raw in ("default", "agency"):
        return None
    return raw

def ensure_prompt_file(client_id: str, brand_name: str, demo_link: str) -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    p = PROMPTS_DIR / f"{client_id}.txt"
    if p.exists():
        return
    template = CLIENT_TEMPLATE_PATH.read_text(encoding="utf-8")
    text = (template
        .replace("{{BRAND_NAME}}", brand_name)
        .replace("{{DEMO_LINK}}", demo_link)
    ).strip() + "\n"
    p.write_text(text, encoding="utf-8")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 7  # 7d

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
DEFAULT_DEMO_LINK = os.getenv("DEMO_LINK", "mailto:steve.neuratrade@gmail.com")

DB_PATH = os.getenv("DB_PATH", "neurapilot.sqlite3")
AUTO_INIT_DB = os.getenv("AUTO_INIT_DB", "1") == "1"

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASS", "change-me-now")

client = OpenAI(timeout=20.0, max_retries=1)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
import secrets
from pathlib import Path

CLIENTS_PATH = Path(BASE_DIR) / "clients.json"

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER)
LEAD_EMAIL_FALLBACK = os.getenv("LEAD_EMAIL_FALLBACK", "")
LEAD_EMAIL_SUBJECT = os.getenv("LEAD_EMAIL_SUBJECT", "[NeuraPilot] Neuer Lead: {client_id}")

def send_lead_email(to_addr: str, subject: str, body: str) -> None:
    if not (SMTP_HOST and SMTP_FROM and to_addr):
        return
    try:
        msg = EmailMessage()
        msg["From"] = SMTP_FROM
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=6) as s:
            s.starttls()
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception:
        # niemals Lead speichern blockieren
        return

try:
    import fcntl  # macOS/Linux
except Exception:
    fcntl = None

def load_clients_file() -> dict:
    return json.loads(CLIENTS_PATH.read_text(encoding="utf-8"))

def write_clients_file_atomic(data: dict) -> None:
    tmp = CLIENTS_PATH.with_suffix(".json.tmp")
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    tmp.write_text(txt, encoding="utf-8")
    tmp.replace(CLIENTS_PATH)

def with_clients_lock(fn):
    lock_path = Path(BASE_DIR) / ".clients.lock"
    with open(lock_path, "w") as lock_file:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            except Exception:
                pass
        return fn()


# ---------- DB init: safe across multiple gunicorn workers ----------
try:
    import fcntl  # macOS/Linux
except Exception:
    fcntl = None

def init_db_once() -> None:
    if not AUTO_INIT_DB:
        return
    lock_path = os.path.join(BASE_DIR, ".dbinit.lock")
    with open(lock_path, "w") as lock_file:
        if fcntl is not None:
            try:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            except Exception:
                pass
        tmp = connect(DB_PATH)
        try:
            init_db(tmp)
        finally:
            tmp.close()

init_db_once()

def get_db():
    if "db" not in g:
        g.db = connect(DB_PATH)
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# ---------- helpers ----------
def sanitize_history(history: Any, max_turns: int = 12, max_chars: int = 1500) -> List[Dict[str, str]]:
    if not isinstance(history, list):
        return []
    out: List[Dict[str, str]] = []
    for item in history[-max_turns:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str):
            continue
        c = content.strip()
        if c:
            out.append({"role": role, "content": c[:max_chars]})
    return out

import urllib.request

def post_webhook(url: str, payload: dict) -> None:
    if not url:
        return
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=2.5):
            pass
    except Exception:
        # don't break the request if webhook fails
        return

def safe_parse_model_json(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "reply" in data:
            data.setdefault("action", "none")
            data.setdefault("lead", {})
            if not isinstance(data["lead"], dict):
                data["lead"] = {}
            return data
    except Exception:
        pass
    return {"reply": (text or "…").strip(), "action": "none", "lead": {}}

def get_config(client_id: str) -> Dict[str, Any]:
    all_clients = load_clients()
    base = all_clients.get("default", {})
    overrides = all_clients.get(client_id, {})
    cfg = merge(base, overrides)

    demo = cfg.get("links", {}).get("demo", "{{DEMO_LINK}}")
    demo = demo.replace("{{DEMO_LINK}}", DEFAULT_DEMO_LINK)
    cfg.setdefault("links", {})
    cfg["links"]["demo"] = demo
    return cfg

def public_config(cfg: dict) -> dict:
    """
    Remove secrets/internal fields from what the browser gets.
    """
    clean = json.loads(json.dumps(cfg))  # cheap deep copy
    for k in ("widget_key", "allowed_domains", "webhook_url", "lead_email_to"):
        if k in clean:
            del clean[k]
    return clean

def _basic_auth_ok() -> bool:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8")
        user, pw = raw.split(":", 1)
        return user == ADMIN_USER and pw == ADMIN_PASS
    except Exception:
        return False

def require_admin():
    if _basic_auth_ok():
        return None
    resp = make_response("Authentication required", 401)
    resp.headers["WWW-Authenticate"] = 'Basic realm="NeuraPilot Admin"'
    return resp

def _host_from_url(u: str) -> str:
    try:
        p = urlparse(u)
        return (p.netloc or "").lower()
    except Exception:
        return ""

def is_allowed_embed_host(client_cfg: dict) -> bool:
    """
    Check the caller page host (Referer) for /widget.js requests.
    """
    allowed = client_cfg.get("allowed_domains", [])
    if not allowed:
        return True  # dev / no restriction
    ref = request.headers.get("Referer", "") or ""
    host = _host_from_url(ref)
    return any(a.lower() == host or host.endswith("." + a.lower()) for a in allowed)

def verify_widget_key(client_cfg: dict, provided: str | None) -> bool:
    """
    Stronger than Origin: a per-client widget key.
    If cfg has widget_key, it must match.
    """
    required = (client_cfg.get("widget_key") or "").strip()
    if not required:
        return True  # allow if not configured (dev)
    return (provided or "").strip() == required

def frame_ancestors_value(client_cfg: dict) -> str:
    allowed = client_cfg.get("allowed_domains", [])
    if not allowed:
        return "'self'"  # dev
    # Build CSP origins
    origins = ["'self'"]
    for d in allowed:
        d = d.strip()
        if not d:
            continue
        if d.startswith("http://") or d.startswith("https://"):
            origins.append(d)
        else:
            origins.append(f"https://{d}")
            origins.append(f"http://{d}")
    return " ".join(origins)

# ---------- headers ----------
@app.after_request
def add_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Cache-Control"] = "no-store"

    # Default: forbid embedding everywhere
    if request.path != "/embed":
        resp.headers["X-Frame-Options"] = "DENY"

    # CSP differs for embed (must be frameable by customer domains)
    if request.path == "/embed":
        client_id = get_client_id(request.args.get("client"))
        cfg = get_config(client_id)
        fa = frame_ancestors_value(cfg)
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            f"frame-ancestors {fa};"
        )
    else:
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )

    return resp

# ---------- routes ----------
@app.get("/")
def index():
    client_id = get_client_id(request.args.get("client"))
    return render_template("index.html", client_id=client_id)

@app.get("/config")
def config():
    client_id = get_client_id(request.args.get("client"))
    cfg = get_config(client_id)
    cfg = public_config(cfg)
    cfg["meta"] = {"clientId": client_id, "model": MODEL}
    return jsonify(cfg)

@app.post("/chat")
def chat():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    history = sanitize_history(data.get("history"))
    client_id = get_client_id(request.args.get("client") or data.get("client"))

    if not message:
        return jsonify({"reply": "Schreib mir kurz, wobei ich helfen kann 🙂", "action": "none", "lead": {}})

    cfg = get_config(client_id)

    # Widget key check (works for iframe integration)
    widget_key = request.args.get("k") or data.get("k") or request.headers.get("X-Widget-Key")
    if not verify_widget_key(cfg, widget_key):
        return jsonify({"reply": "Not allowed", "action": "none", "lead": {}}), 403

    demo_link = cfg["links"]["demo"]
    brand_name = cfg.get("brand", {}).get("name", "NeuraPilot")

    prompt = load_prompt_bundle(client_id, demo_link=demo_link, brand_name=brand_name)
    input_items = history + [{"role": "user", "content": message[:1500]}]

    try:
        resp = client.responses.create(
            model=MODEL,
            instructions=prompt,
            input=input_items,
            temperature=0.4,
            max_output_tokens=450,
        )

        raw = (resp.output_text or "").strip()
        parsed = safe_parse_model_json(raw)

        action = parsed.get("action", "none")
        if action in ("book_demo", "collect_email"):
            insert_event(get_db(), client_id, action)

        if action == "book_demo" and demo_link not in parsed.get("reply", ""):
            parsed["reply"] = f'{parsed.get("reply","").strip()}\n\nDemo-Link: {demo_link}'.strip()

        return jsonify(parsed), 200

    except Exception:
        return jsonify({"reply": "Uff — technisches Problem. Bitte nochmal versuchen.", "action": "none", "lead": {}}), 500

@app.post("/lead")
def lead():
    data = request.get_json(silent=True) or {}
    client_id = get_client_id(request.args.get("client") or data.get("client") or "default")
    cfg = get_config(client_id)

    widget_key = request.args.get("k") or data.get("k") or request.headers.get("X-Widget-Key")
    if not verify_widget_key(cfg, widget_key):
        return jsonify({"ok": False, "error": "Not allowed"}), 403

    email = (data.get("email") or "").strip().lower()
    if not email or len(email) > 180 or not EMAIL_RE.match(email):
        return jsonify({"ok": False, "error": "Invalid email"}), 400

    service = (data.get("service") or "")[:120]
    timing = (data.get("timing") or "")[:120]
    budget = (data.get("budget") or "")[:120]
    source = (data.get("source") or "chat")[:40]
    conversation = (data.get("conversation") or "")[:2000]

    insert_lead(
        get_db(),
        client_id=client_id,
        email=email,
        service=service,
        timing=timing,
        budget=budget,
        source=source,
        conversation=conversation,
    )
    # Email forwarding (optional)
    to_addr = (cfg.get("lead_email_to") or LEAD_EMAIL_FALLBACK or "").strip()
    if to_addr:
        subj = LEAD_EMAIL_SUBJECT.format(client_id=client_id)
        body = (
            f"Client: {client_id}\n"
            f"Email: {email}\n"
            f"Service: {service}\n"
            f"Timing: {timing}\n"
            f"Budget: {budget}\n"
            f"Source: {source}\n"
            f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "Conversation:\n"
            f"{conversation}\n"
        )
        send_lead_email(to_addr, subj, body)

    return jsonify({"ok": True}), 200

@app.get("/admin/clients")
def admin_clients():
    r = require_admin()
    if r is not None:
        return r

    data = load_clients_file()
    out = []
    for cid, cfg in data.items():
        if cid == "default":
            continue
        out.append({
            "client_id": cid,
            "name": (cfg.get("brand", {}) or {}).get("name", cid)
        })
    out.sort(key=lambda x: x["client_id"])
    return jsonify({"clients": out})

@app.post("/admin/create-client")
def admin_create_client():
    r = require_admin()
    if r is not None:
        return r

    payload = request.get_json(silent=True) or {}

    raw_id = payload.get("client_id")
    client_id = validate_client_id(raw_id)
    if not client_id:
        return jsonify({"ok": False, "error": "Invalid client_id (use a-z A-Z 0-9 _ -)"}), 400

    brand_name = (payload.get("brand_name") or client_id).strip()
    demo_link = (payload.get("demo_link") or DEFAULT_DEMO_LINK).strip()

    allowed_domains = payload.get("allowed_domains") or []
    if not isinstance(allowed_domains, list):
        return jsonify({"ok": False, "error": "allowed_domains must be a list"}), 400
    allowed_domains = [str(d).strip() for d in allowed_domains if str(d).strip()]

    widget_key = secrets.token_urlsafe(24)

    theme = payload.get("theme") if isinstance(payload.get("theme"), dict) else {}
    copy = payload.get("copy") if isinstance(payload.get("copy"), dict) else {}
    webhook_url = (payload.get("webhook_url") or "").strip()
    lead_email_to = (payload.get("lead_email_to") or "").strip()
    logo_text = (payload.get("logo_text") or "NP").strip()

    base_url = request.host_url.rstrip("/")

    def _op():
        data = load_clients_file()
        if client_id in data:
            return {"ok": False, "error": "Client already exists"}

        data[client_id] = {
            "brand": {"name": brand_name, "logoText": logo_text},
            "links": {"demo": demo_link},
            "allowed_domains": allowed_domains,
            "widget_key": widget_key,
            "theme": theme,
            "copy": copy,
            "webhook_url": webhook_url,
            "lead_email_to": lead_email_to
        }

        write_clients_file_atomic(data)
        ensure_prompt_file(client_id, brand_name, demo_link)
        return {"ok": True}

    res = with_clients_lock(_op)
    if not res.get("ok"):
        return jsonify(res), 400

    snippet = f'''<script
  src="{base_url}/widget.js"
  data-client="{client_id}"
  data-key="{widget_key}"
  data-position="right"
  data-accent="{(theme.get("accentB") or "#22d3ee")}">
</script>'''

    return jsonify({
        "ok": True,
        "client_id": client_id,
        "widget_key": widget_key,
        "snippet": snippet,
        "preview_url": f"{base_url}/?client={client_id}",
    }), 200

@app.post("/admin/update-client")
def admin_update_client():
    r = require_admin()
    if r is not None:
        return r

    payload = request.get_json(silent=True) or {}
    client_id = validate_client_id(payload.get("client_id"))
    if not client_id:
        return jsonify({"ok": False, "error": "invalid client_id"}), 400

    def _op():
        data = load_clients_file()
        if client_id not in data:
            return {"ok": False, "error": "client not found"}

        c = data[client_id]

        if "allowed_domains" in payload:
            ad = payload["allowed_domains"]
            if not isinstance(ad, list):
                return {"ok": False, "error": "allowed_domains must be list"}
            c["allowed_domains"] = [str(d).strip() for d in ad if str(d).strip()]

        if "demo_link" in payload:
            c.setdefault("links", {})
            c["links"]["demo"] = str(payload["demo_link"]).strip()

        if "brand_name" in payload or "logo_text" in payload:
            c.setdefault("brand", {})
            if "brand_name" in payload:
                c["brand"]["name"] = str(payload["brand_name"]).strip()
            if "logo_text" in payload:
                c["brand"]["logoText"] = str(payload["logo_text"]).strip()

        if "theme" in payload and isinstance(payload["theme"], dict):
            c["theme"] = payload["theme"]

        if "webhook_url" in payload:
            c["webhook_url"] = str(payload["webhook_url"]).strip()

        if "lead_email_to" in payload:
            c["lead_email_to"] = str(payload["lead_email_to"]).strip()

        data[client_id] = c
        write_clients_file_atomic(data)
        return {"ok": True}

    res = with_clients_lock(_op)
    return jsonify(res), (200 if res.get("ok") else 400)

@app.post("/admin/rotate-key")
def admin_rotate_key():
    r = require_admin()
    if r is not None:
        return r

    payload = request.get_json(silent=True) or {}
    client_id = validate_client_id(payload.get("client_id"))
    if not client_id:
        return jsonify({"ok": False, "error": "invalid client_id"}), 400

    new_key = secrets.token_urlsafe(24)

    def _op():
        data = load_clients_file()
        if client_id not in data:
            return {"ok": False, "error": "client not found"}
        data[client_id]["widget_key"] = new_key
        write_clients_file_atomic(data)
        return {"ok": True}

    res = with_clients_lock(_op)
    if not res.get("ok"):
        return jsonify(res), 400

    return jsonify({"ok": True, "client_id": client_id, "widget_key": new_key}), 200

@app.get("/admin")
def admin():
    r = require_admin()
    if r is not None:
        return r
    return render_template("admin.html")

from db import kpi  # oben import ergänzen

@app.get("/admin/data")
def admin_data():
    r = require_admin()
    if r is not None:
        return r

    cid = request.args.get("client") or ""
    cid = get_client_id(cid) if cid else None

    db = get_db()
    return jsonify({
        "client": cid or "",
        "stats": stats(db, client_id=cid),
        "kpi": kpi(db, days=7, client_id=cid),
        "leads": list_leads(db, limit=200, client_id=cid),
    })

PROMPTS_DIR = Path(BASE_DIR) / "prompts"
CLIENT_TEMPLATE_PATH = PROMPTS_DIR / "client_template.txt"

def ensure_prompt_file(client_id: str, brand_name: str, demo_link: str) -> None:
    p = PROMPTS_DIR / f"{client_id}.txt"
    if p.exists():
        return
    template = CLIENT_TEMPLATE_PATH.read_text(encoding="utf-8")
    text = (template
        .replace("{{BRAND_NAME}}", brand_name)
        .replace("{{DEMO_LINK}}", demo_link)
    ).strip() + "\n"
    p.write_text(text, encoding="utf-8")

@app.get("/admin/export.csv")
def admin_export():
    r = require_admin()
    if r is not None:
        return r

    cid = request.args.get("client") or ""
    cid = get_client_id(cid) if cid else None
    rows = list_leads(get_db(), limit=5000, client_id=cid)
    header = "id,ts,client_id,email,service,timing,budget,source\n"
    lines = [header]

    for row in rows:
        def esc(v: Any) -> str:
            s = str(v or "").replace('"', '""')
            return f'"{s}"'
        lines.append(",".join([
            esc(row.get("id")),
            esc(row.get("ts")),
            esc(row.get("client_id")),
            esc(row.get("email")),
            esc(row.get("service")),
            esc(row.get("timing")),
            esc(row.get("budget")),
            esc(row.get("source")),
        ]) + "\n")

    resp = make_response("".join(lines))
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = "attachment; filename=neurapilot-leads.csv"
    return resp

@app.get("/health")
def health():
    return jsonify({"status": "ok", "ts": int(time.time())})

# ---------- Widget integration ----------
@app.get("/widget.js")
def widget_js():
    client_id = get_client_id(request.args.get("client") or request.args.get("c"))
    cfg = get_config(client_id)

    # Only serve widget script to allowed customer domains (via Referer)
    if not is_allowed_embed_host(cfg):
        return Response("/* not allowed */", mimetype="application/javascript", status=403)

    js = r"""
(function(){
  const s = document.currentScript;
  const client = (s && s.dataset.client) ? s.dataset.client : "default";
  const key = (s && s.dataset.key) ? s.dataset.key : "";
  const pos = (s && s.dataset.position) ? s.dataset.position : "right";
  const accent = (s && s.dataset.accent) ? s.dataset.accent : "";

  const btn = document.createElement("button");
  btn.innerText = "Chat";
  btn.style.position = "fixed";
  btn.style.bottom = "18px";
  btn.style[pos] = "18px";
  btn.style.zIndex = "999999";
  btn.style.border = "1px solid rgba(255,255,255,.18)";
  btn.style.borderRadius = "14px";
  btn.style.padding = "12px 14px";
  btn.style.fontWeight = "800";
  btn.style.cursor = "pointer";
  btn.style.background = accent || "rgba(255,255,255,.92)";
  btn.style.color = "#0b1020";

  const wrap = document.createElement("div");
  wrap.style.position = "fixed";
  wrap.style.bottom = "72px";
  wrap.style[pos] = "18px";
  wrap.style.width = "380px";
  wrap.style.height = "560px";
  wrap.style.zIndex = "999999";
  wrap.style.display = "none";
  wrap.style.borderRadius = "18px";
  wrap.style.overflow = "hidden";
  wrap.style.boxShadow = "0 24px 70px rgba(0,0,0,.45)";
  wrap.style.border = "1px solid rgba(255,255,255,.12)";

  const iframe = document.createElement("iframe");
  const base = s.src.replace(/\/widget\.js(\?.*)?$/, "");
  const qs = `client=${encodeURIComponent(client)}&k=${encodeURIComponent(key)}`;
  iframe.src = `${base}/embed?${qs}`;
  iframe.style.width = "100%";
  iframe.style.height = "100%";
  iframe.style.border = "0";
  wrap.appendChild(iframe);

  btn.addEventListener("click", () => {
    wrap.style.display = (wrap.style.display === "none") ? "block" : "none";
  });

  document.body.appendChild(btn);
  document.body.appendChild(wrap);
})();
"""
    resp = Response(js, mimetype="application/javascript")
    resp.headers["Cache-Control"] = "public, max-age=3600"  # ok to cache a bit
    return resp

@app.get("/embed")
def embed():
    client_id = get_client_id(request.args.get("client"))
    return render_template("embed.html", client_id=client_id)


@app.post("/billing/checkout")
def billing_checkout():
    data = request.get_json(silent=True) or {}
    plan = (data.get("plan") or "starter").strip()
    price_id = PRICE_MAP.get(plan)
    if not price_id:
        return jsonify({"ok": False, "error": "Invalid plan"}), 400

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{PUBLIC_BASE_URL}/after-checkout?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{PUBLIC_BASE_URL}/pricing?canceled=1",
        allow_promotion_codes=True,
        client_reference_id=f"np_{int(time.time())}",
        metadata={"plan": plan},
    )
    return jsonify({"ok": True, "url": session.url})

@app.get("/after-checkout")
def after_checkout():
    session_id = request.args.get("session_id","").strip()
    if not session_id:
        return "Missing session_id", 400

    s = stripe.checkout.Session.retrieve(session_id, expand=["customer", "subscription"])
    email = (s.get("customer_details") or {}).get("email") or ""
    plan = (s.get("metadata") or {}).get("plan") or "starter"

    # TODO: in billing_accounts upsert: status 'pending', session_id, email, customer, subscription
    # Danach render onboarding form:
    return render_template("onboard.html", email=email, plan=plan, session_id=session_id)

@app.post("/onboard")
def onboard():
    data = request.get_json(silent=True) or {}
    session_id = (data.get("session_id") or "").strip()

    # verify paid session (defensive)
    s = stripe.checkout.Session.retrieve(session_id, expand=["subscription"])
    if s.get("payment_status") not in ("paid", "no_payment_required"):
        return jsonify({"ok": False, "error": "Not paid"}), 402

    email = ((s.get("customer_details") or {}).get("email") or "").strip().lower()
    plan = (s.get("metadata") or {}).get("plan") or "starter"

    # take onboarding inputs
    client_id = (data.get("client_id") or "").strip()
    domains = data.get("allowed_domains") or []
    demo_link = (data.get("demo_link") or DEFAULT_DEMO_LINK).strip()
    lead_email_to = (data.get("lead_email_to") or email).strip()
    brand_name = (data.get("brand_name") or client_id).strip()
    theme = data.get("theme") if isinstance(data.get("theme"), dict) else {}

    # create tenant via your existing create-client logic (same as /admin/create-client)
    # widget_key generated + clients.json written + prompt file created
    # return snippet

    # IMPORTANT: mark billing_accounts status active + store client_id
    return jsonify({"ok": True, "client_id": client_id, "snippet": "...", "widget_key": "..."})

@app.post("/stripe/webhook")
def stripe_webhook():
    payload = request.data
    sig = request.headers.get("Stripe-Signature","")

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "bad signature", 400

    t = event["type"]
    obj = event["data"]["object"]

    # 1) Checkout abgeschlossen => aktivieren
    if t == "checkout.session.completed":
        # obj.id, obj.customer, obj.subscription
        # set billing_accounts status='active'
        pass

    # 2) Subscription canceled/updated => deaktivieren
    if t in ("customer.subscription.deleted", "customer.subscription.updated"):
        # if canceled or unpaid -> set status accordingly
        pass

    return "ok", 200

@app.post("/billing/portal")
def billing_portal():
    data = request.get_json(silent=True) or {}
    customer_id = (data.get("stripe_customer_id") or "").strip()
    if not customer_id:
        return jsonify({"ok": False, "error": "missing customer"}), 400

    ps = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{PUBLIC_BASE_URL}/account"
    )
    return jsonify({"ok": True, "url": ps.url})