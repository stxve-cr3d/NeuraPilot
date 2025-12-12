/* static/app.js */
(() => {
  const $ = (id) => document.getElementById(id);

  const els = {
    msgs: $("msgs"),
    input: $("input"),
    send: $("send"),
    typing: $("typing"),
    actions: $("actions"),
    actionDemo: $("actionDemo"),
    leadbar: $("leadbar"),
    leadEmail: $("leadEmail"),
    leadSend: $("leadSend"),
    leadHint: $("leadHint"),
    brandName: $("brandName"),
    brandSub: $("brandSub"),
  };

  // ---- client + key ----
  function getClientId() {
    const fromBody = document.body?.getAttribute("data-client");
    if (fromBody) return fromBody;
    const url = new URL(window.location.href);
    return url.searchParams.get("client") || "default";
  }

  function getKey() {
    const url = new URL(window.location.href);
    return url.searchParams.get("k") || "";
  }

  const clientId = getClientId();
  const widgetKey = getKey();

  function qs() {
    const p = new URLSearchParams();
    if (clientId && clientId !== "default") p.set("client", clientId);
    if (widgetKey) p.set("k", widgetKey);
    const s = p.toString();
    return s ? `?${s}` : "";
  }

  // ---- state ----
  const STORE_KEY = `np_history_${clientId}`;
  const CFG_KEY = `np_cfg_${clientId}`;
  const CFG_TTL_MS = 10 * 60 * 1000;

  let history = [];
  let cfg = null;
  let lastLead = {};

  // ---- helpers UI ----
  function scrollToBottom() {
    if (!els.msgs) return;
    els.msgs.scrollTop = els.msgs.scrollHeight;
  }

  function escapeHtml(s) {
    return String(s || "").replace(/[&<>"']/g, (m) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[m]));
  }

  function renderMarkdownLite(text) {
    // very light: convert line breaks to <br>, auto-link URLs
    const safe = escapeHtml(text);
    const linked = safe.replace(
      /(https?:\/\/[^\s<]+)/g,
      (m) => `<a href="${m}" target="_blank" rel="noopener">${m}</a>`
    );
    return linked.replace(/\n/g, "<br>");
  }

  function addBubble(role, text) {
    if (!els.msgs) return;
    const wrap = document.createElement("div");
    wrap.className = `msg msg--${role}`;

    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.innerHTML = renderMarkdownLite(text);

    wrap.appendChild(bubble);
    els.msgs.appendChild(wrap);
    scrollToBottom();
  }

  function setTyping(on) {
    if (!els.typing) return;
    els.typing.hidden = !on;
    if (on) scrollToBottom();
  }

  function showActionDemo(on) {
    if (!els.actions || !els.actionDemo) return;
    els.actions.hidden = !on;
  }

  function toggleLeadbar(on) {
    if (els.leadbar) els.leadbar.hidden = !on;
    if (els.leadHint) els.leadHint.hidden = !on;
    if (on && els.leadEmail) setTimeout(() => els.leadEmail.focus(), 50);
  }

  function saveHistory() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(history.slice(-30)));
    } catch (_) {}
  }

  function loadHistory() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      return parsed.filter(x => x && (x.role === "user" || x.role === "assistant") && typeof x.content === "string");
    } catch (_) {
      return [];
    }
  }

  function transcript(maxTurns = 10) {
    return history.slice(-maxTurns).map(x => `${x.role}: ${x.content}`).join("\n");
  }

  // ---- config caching ----
  function loadConfigCache() {
    try {
      const raw = localStorage.getItem(CFG_KEY);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (!obj || typeof obj !== "object") return null;
      if (!obj.ts || !obj.value) return null;
      if (Date.now() - obj.ts > CFG_TTL_MS) return null;
      return obj.value;
    } catch (_) {
      return null;
    }
  }

  function saveConfigCache(value) {
    try {
      localStorage.setItem(CFG_KEY, JSON.stringify({ ts: Date.now(), value }));
    } catch (_) {}
  }

  async function fetchConfig() {
    const cached = loadConfigCache();
    if (cached) return cached;

    const res = await fetch(`/config?client=${encodeURIComponent(clientId)}`, { method: "GET" });
    const data = await res.json();
    saveConfigCache(data);
    return data;
  }

  // ---- theme + branding ----
  function applyTheme(c) {
    const t = (c && c.theme) ? c.theme : {};
    const root = document.documentElement;

    // Use your existing CSS variables; only set if present
    if (t.accentA) root.style.setProperty("--accentA", t.accentA);
    if (t.accentB) root.style.setProperty("--accentB", t.accentB);
    if (t.bgA) root.style.setProperty("--bgA", t.bgA);
    if (t.bgB) root.style.setProperty("--bgB", t.bgB);
  }

  function applyBranding(c) {
    const w = (c && c.widget) ? c.widget : {};
    const brand = (c && c.brand) ? c.brand : {};

    const title = w.title || brand.name || "NeuraPilot";
    const subtitle = w.subtitle || "Antwortet • qualifiziert • bucht Termine";

    if (els.brandName) els.brandName.textContent = title;
    if (els.brandSub) els.brandSub.textContent = subtitle;

    // set demo link if present
    const demo = (c && c.links && c.links.demo) ? c.links.demo : "";
    if (els.actionDemo && demo) els.actionDemo.href = demo;
  }

function renderPricing(c) {
  const el =
    document.getElementById("pricingGrid") ||
    document.getElementById("pricingCards") ||
    document.getElementById("pricing");

  if (!el) return;

  const p = c && c.pricing ? c.pricing : null;

  // Fallback, falls keine pricing in config
  if (!p || (!Array.isArray(p.plans) && !Array.isArray(p))) return;

  const plans = Array.isArray(p) ? p : (p.plans || []);
  if (!plans.length) return;

  el.innerHTML = ""; // reset

  for (const plan of plans) {
    const name = plan.name || "Plan";
    const price = plan.price ?? "";
    const period = plan.period || (p.period || "/Monat");
    const tagline = plan.tagline || "";
    const features = Array.isArray(plan.features) ? plan.features : [];
    const ctaText = plan.cta_text || "Demo buchen";
    const ctaLink =
      plan.cta_link ||
      (c.links && c.links.demo) ||
      "#";

    const card = document.createElement("div");
    card.className = "box"; // nutzt dein bestehendes Card-Design

    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px">
        <div>
          <div style="font-weight:900;font-size:1.1rem">${escapeHtml(name)}</div>
          ${tagline ? `<div style="color:var(--muted);font-weight:650;margin-top:6px">${escapeHtml(tagline)}</div>` : ""}
        </div>
        <div style="text-align:right">
          <div style="font-weight:950;font-size:1.35rem">${escapeHtml(String(price))}</div>
          <div style="color:var(--muted);font-weight:650">${escapeHtml(period)}</div>
        </div>
      </div>

      ${features.length ? `
        <ul style="margin:12px 0 0;padding-left:18px;color:var(--muted);font-weight:650;line-height:1.55">
          ${features.map(f => `<li>${escapeHtml(String(f))}</li>`).join("")}
        </ul>
      ` : ""}

      <div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn btn--small" href="${escapeHtml(ctaLink)}" target="_blank" rel="noopener">
          ${escapeHtml(ctaText)}
        </a>
      </div>
    `;

    el.appendChild(card);
  }
}

  function maybeGreeting(c) {
    const w = (c && c.widget) ? c.widget : {};
    const greeting = (w.greeting || "").trim();
    if (!greeting) return;

    // only if no prior history
    if (history.length === 0) {
      addBubble("assistant", greeting);
      history.push({ role: "assistant", content: greeting });
      saveHistory();
    }
  }

function getUtm() {
  try {
    const url = new URL(window.location.href);
    const utm = {
      source: url.searchParams.get("utm_source") || "",
      campaign: url.searchParams.get("utm_campaign") || "",
      medium: url.searchParams.get("utm_medium") || "",
      content: url.searchParams.get("utm_content") || "",
      term: url.searchParams.get("utm_term") || "",
    };
    if (!Object.values(utm).some(Boolean)) return null;
    return utm;
  } catch (_) {
    return null;
  }
}

  // ---- chat ----
  async function send() {
    const msg = (els.input?.value || "").trim();
    if (!msg) return;

    els.input.value = "";
    addBubble("user", msg);
    history.push({ role: "user", content: msg });
    saveHistory();

    setTyping(true);
    if (els.send) els.send.disabled = true;

    try {
      const res = await fetch(`/chat${qs()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg,
          history,
          client: clientId,
          k: widgetKey
        })
      });

      const data = await res.json();
      setTyping(false);

      if (!res.ok) {
        addBubble("assistant", data.reply || "Not allowed / Fehler.");
        return;
      }

      const reply = (data.reply || "…").trim();
      addBubble("assistant", reply);
      history.push({ role: "assistant", content: reply });
      saveHistory();

      lastLead = data.lead || {};

      // action handling
      const action = data.action || "none";
      if (action === "book_demo") {
        showActionDemo(true);
        toggleLeadbar(false);
      } else if (action === "collect_email") {
        showActionDemo(false);
        toggleLeadbar(true);
      } else {
        // leave as-is
      }

    } catch (e) {
      setTyping(false);
      addBubble("assistant", "Netzwerkfehler — bitte nochmal versuchen.");
    } finally {
      if (els.send) els.send.disabled = false;
    }
  }

  async function submitLead() {
    const email = (els.leadEmail?.value || "").trim().toLowerCase();
    if (!email || !email.includes("@")) {
      addBubble("assistant", "Magst du mir deine E-Mail im Format name@firma.de schicken?");
      return;
    }

    if (els.leadSend) els.leadSend.disabled = true;

    try {
      const payload = {
  client: clientId,
  k: widgetKey,
  email,
  service: lastLead.service || "",
  timing: lastLead.timing || "",
  budget: lastLead.budget || "",
  source: "chat",
  conversation: transcript(10),
  utm: getUtm() || undefined
};

      const res = await fetch(`/lead${qs()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (!res.ok || !data.ok) {
        addBubble("assistant", "Hmm — das hat gerade nicht geklappt. Versuch’s bitte nochmal.");
        return;
      }

      addBubble("assistant", "Perfekt ✅ Soll ich dir auch direkt einen Termin-Link schicken?");
      toggleLeadbar(false);
      showActionDemo(true);
      if (els.leadEmail) els.leadEmail.value = "";

    } catch (_) {
      addBubble("assistant", "Netzwerkfehler — bitte nochmal versuchen.");
    } finally {
      if (els.leadSend) els.leadSend.disabled = false;
    }
  }

  // ---- init ----
  async function init() {
    // restore history
    history = loadHistory();

    // render history
    if (els.msgs && history.length > 0) {
      els.msgs.innerHTML = "";
      for (const h of history) addBubble(h.role === "user" ? "user" : "assistant", h.content);
    }

    // load config and apply
    try {
      cfg = await fetchConfig();
      applyTheme(cfg);
      applyBranding(cfg);
      renderPricing(cfg);

      // greeting only if new user/no history
      maybeGreeting(cfg);

      // action demo link hidden by default unless set
      showActionDemo(false);
      toggleLeadbar(false);
    } catch (_) {
      // config fail shouldn't break chat
    }

    // wire events
    if (els.send) els.send.addEventListener("click", send);
    if (els.input) {
      els.input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") send();
      });
    }

    if (els.leadSend) els.leadSend.addEventListener("click", submitLead);
    if (els.leadEmail) {
      els.leadEmail.addEventListener("keydown", (e) => {
        if (e.key === "Enter") submitLead();
      });
    }
  }

  const url = new URL(location.href);
payload.utm = {
  source: url.searchParams.get("utm_source") || "",
  campaign: url.searchParams.get("utm_campaign") || "",
  adset: url.searchParams.get("utm_adset") || "",
  content: url.searchParams.get("utm_content") || ""
};

  document.addEventListener("DOMContentLoaded", init);
})();