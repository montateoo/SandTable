(function () {
    "use strict";

    var token = new URLSearchParams(location.search).get("t");
    var btn = document.getElementById("drawBtn");
    var ring = document.getElementById("ringFg");
    var statusEl = document.getElementById("status");
    var hintEl = document.getElementById("hint");

    var RING_CIRCUMFERENCE = 339.3;
    var JOG_INTERVAL_MS = 125; // ~8Hz
    var BASELINE_SAMPLES = 3;

    var holdMs = 3000; // overwritten by /api/config; this is just a safe fallback
    var IDLE_POLL_MS = 2500;
    var holdTimer = null;
    var jogTimer = null;
    var idlePollTimer = null;
    var orientationHandler = null;
    var latestOrientation = null;
    var baseline = null;
    var baselineCount = 0;
    var sessionSecret = null; // identifies our session so another phone with the same QR can't jog/stop it
    var state = "idle"; // idle | holding | active | expired

    function setStatus(text, cls) {
        statusEl.textContent = text;
        statusEl.className = "status" + (cls ? " " + cls : "");
    }

    function goExpired(message) {
        state = "expired";
        stopEverything(false);
        stopIdlePolling();
        btn.classList.add("locked");
        hintEl.style.display = "none";
        setStatus(message || "Sessione scaduta, effettua una nuova scansione del QR", "error");
    }

    if (!token) {
        goExpired("Codice mancante: effettua la scansione del QR sul tavolo");
        return;
    }

    function stopIdlePolling() {
        if (idlePollTimer) { clearInterval(idlePollTimer); idlePollTimer = null; }
    }

    function pollIdleStatus() {
        if (state !== "idle") {
            return;
        }
        fetch("api/status").then(function (r) { return r.json(); }).then(function (data) {
            if (state !== "idle") {
                return; // state moved on while this request was in flight
            }
            if (!data.enabled) {
                btn.classList.add("locked");
                btn.disabled = true;
                hintEl.textContent = "ManualDraw non e' abilitato al momento.";
                setStatus("Non disponibile", "error");
            } else if (data.active) {
                btn.classList.add("locked");
                btn.disabled = true;
                hintEl.textContent = "Qualcun altro sta gia' disegnando. Riprova tra poco.";
                setStatus("Occupato al momento", "error");
            } else {
                btn.classList.remove("locked");
                btn.disabled = false;
                hintEl.textContent = "Tieni premuto 3 secondi, poi inclina il telefono per muovere la pallina.";
                setStatus("Tieni premuto per prendere il controllo");
            }
        }).catch(function () { /* transient network hiccup, next tick retries */ });
    }

    function startIdlePolling() {
        if (idlePollTimer) {
            return;
        }
        pollIdleStatus();
        idlePollTimer = setInterval(pollIdleStatus, IDLE_POLL_MS);
    }

    startIdlePolling();

    fetch("api/config").then(function (r) { return r.json(); }).then(function (data) {
        if (data && data.hold_seconds) {
            holdMs = data.hold_seconds * 1000;
        }
    }).catch(function () { /* keep the fallback */ });

    function resetRing(animated) {
        ring.classList.toggle("filling", !!animated);
        ring.style.transitionDuration = animated ? "150ms" : "0ms";
        ring.style.strokeDashoffset = RING_CIRCUMFERENCE;
    }

    function fillRing() {
        ring.classList.add("filling");
        ring.style.transitionDuration = holdMs + "ms";
        // Force reflow so the browser picks up the dashoffset change as a
        // transition start point rather than jumping straight to the end.
        // eslint-disable-next-line no-unused-expressions
        ring.getBoundingClientRect();
        ring.style.strokeDashoffset = "0";
    }

    function post(path, body) {
        return fetch(path, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(Object.assign({ token: token, session: sessionSecret }, body || {})),
        }).then(function (resp) {
            return resp.json().then(function (data) {
                return { status: resp.status, data: data };
            });
        });
    }

    function onOrientation(e) {
        latestOrientation = { beta: e.beta || 0, gamma: e.gamma || 0 };
        if (baseline === null || baselineCount < BASELINE_SAMPLES) {
            baseline = baseline || { beta: 0, gamma: 0 };
            baseline.beta += latestOrientation.beta;
            baseline.gamma += latestOrientation.gamma;
            baselineCount += 1;
            if (baselineCount === BASELINE_SAMPLES) {
                baseline.beta /= BASELINE_SAMPLES;
                baseline.gamma /= BASELINE_SAMPLES;
            }
        }
    }

    function startOrientationListener() {
        baseline = null;
        baselineCount = 0;
        latestOrientation = null;
        orientationHandler = onOrientation;
        window.addEventListener("deviceorientation", orientationHandler);
    }

    function stopOrientationListener() {
        if (orientationHandler) {
            window.removeEventListener("deviceorientation", orientationHandler);
            orientationHandler = null;
        }
    }

    function sendJog() {
        if (!latestOrientation || baselineCount < BASELINE_SAMPLES) {
            return; // still calibrating the baseline
        }
        var dbeta = latestOrientation.beta - baseline.beta;
        var dgamma = latestOrientation.gamma - baseline.gamma;
        post("api/jog", { dbeta: dbeta, dgamma: dgamma }).then(function (res) {
            if (res.status === 403 || res.status === 409) {
                goExpired(res.data && res.data.message);
            }
        }).catch(function () { /* transient network hiccup, next tick retries */ });
    }

    function activate() {
        post("api/start", {}).then(function (res) {
            if (!res.data || !res.data.ok) {
                setStatus((res.data && res.data.message) || "Impossibile avviare", "error");
                resetRing(false);
                state = "idle";
                pollIdleStatus();
                return;
            }
            sessionSecret = res.data.session;
            state = "active";
            btn.classList.add("locked");
            hintEl.textContent = "Inclina il telefono per muovere la pallina. Rilascia per terminare.";
            setStatus("In controllo — il disegno e' in pausa", "active");
            startOrientationListener();
            jogTimer = setInterval(sendJog, JOG_INTERVAL_MS);
        }).catch(function () {
            setStatus("Errore di rete, riprova", "error");
            resetRing(false);
            state = "idle";
        });
    }

    function stopEverything(sendStop) {
        if (holdTimer) { clearTimeout(holdTimer); holdTimer = null; }
        if (jogTimer) { clearInterval(jogTimer); jogTimer = null; }
        stopOrientationListener();
        resetRing(false);
        btn.classList.remove("locked");
        if (sendStop && (state === "active" || state === "holding")) {
            post("api/stop", {}).catch(function () { /* best effort */ });
        }
        sessionSecret = null;
    }

    function backToIdle() {
        stopEverything(state === "active");
        state = "idle";
        hintEl.textContent = "Tieni premuto 3 secondi, poi inclina il telefono per muovere la pallina.";
        setStatus("Tieni premuto per prendere il controllo");
        pollIdleStatus(); // refresh immediately rather than waiting for the next tick
    }

    function onPressStart(e) {
        if (state === "expired" || btn.disabled) {
            return;
        }
        e.preventDefault();
        if (state === "active") {
            return; // already controlling; release ends it, handled by onPressEnd
        }

        function begin() {
            state = "holding";
            setStatus("Continua a tenere premuto...");
            fillRing();
            holdTimer = setTimeout(activate, holdMs);
        }

        if (typeof DeviceOrientationEvent !== "undefined" &&
            typeof DeviceOrientationEvent.requestPermission === "function") {
            // iOS 13+: must be requested synchronously inside this gesture handler.
            DeviceOrientationEvent.requestPermission().then(function (perm) {
                if (perm === "granted") {
                    begin();
                } else {
                    setStatus("Permesso sensori negato", "error");
                }
            }).catch(function () {
                setStatus("Permesso sensori negato", "error");
            });
        } else {
            begin();
        }
    }

    function onPressEnd() {
        if (state === "holding") {
            backToIdle();
        } else if (state === "active") {
            backToIdle();
        }
    }

    btn.addEventListener("pointerdown", onPressStart);
    window.addEventListener("pointerup", onPressEnd);
    window.addEventListener("pointercancel", onPressEnd);
    document.addEventListener("visibilitychange", function () {
        if (document.hidden && (state === "holding" || state === "active")) {
            backToIdle();
        }
    });
    window.addEventListener("pagehide", function () {
        if (state === "active") {
            // Best-effort synchronous-ish stop; the server watchdog is the real safety net.
            navigator.sendBeacon && navigator.sendBeacon(
                "api/stop",
                new Blob([JSON.stringify({ token: token, session: sessionSecret })], { type: "application/json" })
            );
        }
    });
}());
