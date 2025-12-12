/* widget.js */
(function () {
  const s = document.currentScript;
  if (!s) return;

  const client = (s.dataset.client || "default").trim();
  const key = (s.dataset.key || "").trim();

  const pos = (s.dataset.position || "right").trim();  // "right" | "left"
  const accent = (s.dataset.accent || "").trim();
  const buttonText = (s.dataset.buttonText || s.dataset.button || "Chat").trim();

  const width = Math.max(300, Math.min(520, parseInt(s.dataset.width || "380", 10) || 380));
  const height = Math.max(420, Math.min(760, parseInt(s.dataset.height || "560", 10) || 560));

  const base = s.src.replace(/\/widget\.js(\?.*)?$/, "");

  // CSS (scoped-ish)
  const style = document.createElement("style");
  style.textContent = `
    .npw-btn{
      position:fixed; bottom:18px; ${pos}:18px;
      z-index:999999;
      border:1px solid rgba(255,255,255,.18);
      border-radius:14px;
      padding:12px 14px;
      font-weight:800;
      cursor:pointer;
      background:${accent || "rgba(255,255,255,.92)"};
      color:${accent ? "#0b1020" : "#0b1020"};
      box-shadow: 0 18px 50px rgba(0,0,0,.35);
      backdrop-filter: blur(8px);
    }
    .npw-wrap{
      position:fixed; bottom:72px; ${pos}:18px;
      width:${width}px; height:${height}px;
      z-index:999999;
      display:none;
      border-radius:18px;
      overflow:hidden;
      border:1px solid rgba(255,255,255,.12);
      box-shadow: 0 24px 70px rgba(0,0,0,.45);
      background: rgba(0,0,0,.25);
    }
    .npw-top{
      position:absolute; top:10px; right:10px;
      z-index:2;
      display:flex; gap:8px;
    }
    .npw-x{
      width:34px; height:34px;
      border-radius:12px;
      border:1px solid rgba(255,255,255,.14);
      background: rgba(0,0,0,.35);
      color: rgba(255,255,255,.9);
      font-weight:900;
      cursor:pointer;
    }
    .npw-frame{
      position:absolute; inset:0;
      width:100%; height:100%;
      border:0;
      background: transparent;
    }
    @media (max-width: 520px){
      .npw-wrap{ width: min(92vw, ${width}px); height: min(72vh, ${height}px); ${pos}: 10px; bottom: 70px; }
      .npw-btn{ ${pos}: 10px; }
    }
  `;
  document.head.appendChild(style);

  // button
  const btn = document.createElement("button");
  btn.className = "npw-btn";
  btn.type = "button";
  btn.textContent = buttonText;

  // wrapper
  const wrap = document.createElement("div");
  wrap.className = "npw-wrap";

  const top = document.createElement("div");
  top.className = "npw-top";

  const x = document.createElement("button");
  x.className = "npw-x";
  x.type = "button";
  x.textContent = "×";
  x.title = "Close";

  top.appendChild(x);
  wrap.appendChild(top);

  // iframe
  const iframe = document.createElement("iframe");
  iframe.className = "npw-frame";
  const qs = new URLSearchParams();
  qs.set("client", client);
  if (key) qs.set("k", key);
  iframe.src = `${base}/embed?${qs.toString()}`;
  wrap.appendChild(iframe);

  function toggle(open) {
    const isOpen = wrap.style.display === "block";
    const next = typeof open === "boolean" ? open : !isOpen;
    wrap.style.display = next ? "block" : "none";
  }

  btn.addEventListener("click", () => toggle());
  x.addEventListener("click", () => toggle(false));

  document.body.appendChild(btn);
  document.body.appendChild(wrap);
})();