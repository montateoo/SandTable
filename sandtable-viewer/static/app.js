(() => {
  const { bedX, bedY, pollMs } = window.VIEWER_CONFIG;

  const canvas = document.getElementById("stage");
  const ctx = canvas.getContext("2d");
  const badgeEl = document.getElementById("badge");
  const filenameEl = document.getElementById("filename");
  const roundEl = document.getElementById("round");
  const etaEl = document.getElementById("eta");
  const pctEl = document.getElementById("pct");
  const fillEl = document.getElementById("progressbar-fill");

  let points = [];          // [[x,y], ...] in bed mm
  let currentPath = null;   // the file path the loaded points belong to
  let printing = false;

  let shownPct = 0;         // smoothly animated 0..100, drives the reveal
  let targetPct = 0;
  let etaSeconds = null;
  let etaTickHandle = null;

  // ---------------------------------------------------------------- sizing
  let sandTile = null;

  function buildSandTile() {
    const s = 96;
    const t = document.createElement("canvas");
    t.width = t.height = s;
    const tc = t.getContext("2d");
    tc.fillStyle = "#241e16";
    tc.fillRect(0, 0, s, s);
    for (let i = 0; i < 420; i++) {
      const x = Math.random() * s, y = Math.random() * s;
      const a = Math.random() * 0.05 + 0.02;
      tc.fillStyle = `rgba(255,235,200,${a})`;
      tc.fillRect(x, y, 1, 1);
    }
    sandTile = ctx.createPattern(t, "repeat");
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.parentElement.getBoundingClientRect();
    const hudH = document.getElementById("hud").offsetHeight;
    const barH = document.getElementById("progressbar").offsetHeight;
    const w = rect.width;
    const h = rect.height - hudH - barH;
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    buildSandTile();
  }
  window.addEventListener("resize", resize);

  function bedTransform() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const pad = 28;
    const scale = Math.min((w - pad * 2) / bedX, (h - pad * 2) / bedY);
    const ox = (w - bedX * scale) / 2;
    const oy = (h - bedY * scale) / 2;
    return { scale, ox, oy };
  }

  // ---------------------------------------------------------------- draw
  let t0 = performance.now();

  function draw() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.fillStyle = sandTile || "#241e16";
    ctx.fillRect(0, 0, w, h);

    const vignette = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * .15, w / 2, h / 2, Math.max(w, h) * .7);
    vignette.addColorStop(0, "rgba(0,0,0,0)");
    vignette.addColorStop(1, "rgba(0,0,0,.55)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, w, h);

    if (!points.length) {
      ctx.fillStyle = "rgba(243,233,210,.35)";
      ctx.font = "15px Segoe UI, sans-serif";
      ctx.textAlign = "center";
      const pulse = 0.5 + 0.5 * Math.sin((performance.now() - t0) / 700);
      ctx.globalAlpha = 0.3 + pulse * 0.3;
      ctx.fillText("waiting for the table to start a pattern…", w / 2, h / 2);
      ctx.globalAlpha = 1;
      return;
    }

    const { scale, ox, oy } = bedTransform();
    const toScreen = (p) => [ox + p[0] * scale, oy + (bedY - p[1]) * scale];

    const revealCount = printing
      ? Math.max(2, Math.floor(points.length * (shownPct / 100)))
      : points.length;

    // ghost: full pattern, faint
    ctx.beginPath();
    points.forEach((p, i) => {
      const [x, y] = toScreen(p);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.strokeStyle = "rgba(232,163,61,.16)";
    ctx.lineWidth = 1;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke();

    if (!printing) return; // idle: ghost-as-final IS the bright reveal, skip the rest

    // bright: drawn-so-far
    const drawn = points.slice(0, revealCount);
    ctx.beginPath();
    drawn.forEach((p, i) => {
      const [x, y] = toScreen(p);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.shadowColor = "rgba(232,163,61,.65)";
    ctx.shadowBlur = 8;
    ctx.strokeStyle = "#f3d9a4";
    ctx.lineWidth = 1.6;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // tracer ball at the tip
    if (drawn.length) {
      const [tx, ty] = toScreen(drawn[drawn.length - 1]);
      const pulse = 2 + Math.sin((performance.now() - t0) / 220) * 1.2;
      const glow = ctx.createRadialGradient(tx, ty, 0, tx, ty, 11 + pulse);
      glow.addColorStop(0, "rgba(255,247,225,.95)");
      glow.addColorStop(0.4, "rgba(232,163,61,.55)");
      glow.addColorStop(1, "rgba(232,163,61,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(tx, ty, 11 + pulse, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#fff7e1";
      ctx.beginPath();
      ctx.arc(tx, ty, 3, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function tick() {
    shownPct += (targetPct - shownPct) * 0.06;
    if (Math.abs(targetPct - shownPct) < 0.05) shownPct = targetPct;
    draw();
    requestAnimationFrame(tick);
  }

  // ---------------------------------------------------------------- ETA
  function renderEta() {
    if (etaSeconds == null || !printing) { etaEl.textContent = ""; return; }
    const s = Math.max(0, Math.round(etaSeconds));
    const m = Math.floor(s / 60), r = s % 60;
    etaEl.textContent = `⏱ ${m}:${String(r).padStart(2, "0")} left`;
  }

  function startEtaTicker() {
    if (etaTickHandle) clearInterval(etaTickHandle);
    etaTickHandle = setInterval(() => {
      if (etaSeconds != null && printing) etaSeconds = Math.max(0, etaSeconds - 1);
      renderEta();
    }, 1000);
  }

  // ---------------------------------------------------------------- polling
  async function loadPath(filePath) {
    const encoded = filePath.split("/").map(encodeURIComponent).join("/");
    const res = await fetch(`/api/path/${encoded}`);
    if (!res.ok) throw new Error("path fetch failed");
    const data = await res.json();
    points = data.points || [];
  }

  async function poll() {
    try {
      const res = await fetch("/api/state");
      const s = await res.json();

      printing = !!s.printing;
      const file = s.file || {};
      const progress = s.progress || {};

      if (printing && file.path) {
        badgeEl.className = "badge " + (s.phase === "draw" ? "badge--draw" : s.phase === "eraser" ? "badge--erase" : "badge--idle");
        badgeEl.textContent = s.phase ? s.phase.toUpperCase() : "PRINTING";
        filenameEl.textContent = file.label || file.name || "—";
        roundEl.textContent = s.round != null && s.rounds != null ? `round ${s.round + 1}/${s.rounds || "?"}` : "";
        const pct = progress.completion || 0;
        targetPct = pct;
        pctEl.textContent = `${Math.round(pct)}%`;
        fillEl.style.width = `${pct}%`;
        etaSeconds = progress.printTimeLeft;
        renderEta();

        if (file.path !== currentPath) {
          currentPath = file.path;
          shownPct = 0; targetPct = pct;
          canvas.style.opacity = 0.15;
          await loadPath(file.path);
          canvas.style.opacity = 1;
        }
      } else {
        badgeEl.className = "badge badge--idle";
        badgeEl.textContent = "IDLE";
        roundEl.textContent = "";
        etaEl.textContent = "";
        pctEl.textContent = "--%";
        fillEl.style.width = "0%";
        if (file.path && file.path !== currentPath) {
          filenameEl.textContent = (file.label || file.name) + " (last pattern)";
          currentPath = file.path;
          await loadPath(file.path);
        } else if (!file.path) {
          filenameEl.textContent = "Waiting for the table…";
        }
      }
    } catch (err) {
      filenameEl.textContent = "Can't reach OctoPrint";
      console.error(err);
    }
  }

  resize();
  startEtaTicker();
  poll();
  setInterval(poll, pollMs);
  requestAnimationFrame(tick);
})();
