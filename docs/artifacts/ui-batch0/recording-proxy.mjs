// Soulmate Path UI batch-0 recording proxy (local instrument, NOT part of the app).
//
// Listens:
//   :3002  browser-facing. /api/* -> 127.0.0.1:8000 (local dev backend), everything
//          else -> 127.0.0.1:3001 (local production build of the frontend).
//   :3005  control plane (curl): /mode/normal|latency|failure, /fresh, /status, /log, /log/reset
//
// HTML responses are injected with a document-start script that:
//   1. installs a minimal React DevTools hook (commit counter per component name),
//   2. rewrites baked https://soulmate.giaogiao.work/api/ fetches to this same-origin
//      proxy (lets the production build pass its config gate while traffic stays local).
//
// Modes (applies to /api/* only):
//   normal   passthrough
//   latency  +500 ms delay before the upstream response is released (injected response latency)
//   failure  upstream connection is destroyed before response (network-level failure)
// Fresh: strips Cookie on /api/* until the next POST /api/soulmate/sessions has passed,
//   forcing the app to bootstrap a brand-new anonymous session.

import http from "node:http";
import fs from "node:fs";

const FRONTEND_UPSTREAM = { host: "127.0.0.1", port: parseInt(process.env.FRONTEND_PORT || "3001", 10) };
const BACKEND_UPSTREAM = { host: "127.0.0.1", port: 8000 };
const BROWSER_PORT = 3002;
const CONTROL_PORT = 3005;
const LOG_PATH = "/tmp/sp-batch0/requests.jsonl";

const state = {
  mode: "normal",
  freshArmed: false,
  counter: 0,
};

const INJECTED_SCRIPT = `<script>
(function(){
  window.__SP_PROXY_READY = true;
  window.__SP_JS_ERRORS = [];
  window.addEventListener('error', function(e){ window.__SP_JS_ERRORS.push('error: ' + (e.message||'') + ' | file=' + String(e.filename||'').slice(-90) + ' @' + (e.lineno||0)); });
  window.addEventListener('unhandledrejection', function(e){ window.__SP_JS_ERRORS.push('rejection: ' + String(e.reason && e.reason.message || e.reason).slice(0, 200)); });
  // --- same-origin rewrite for baked production API base URL ---
  var REMOTE = "https://soulmate.giaogiao.work/api/";
  var origFetch = window.fetch && window.fetch.bind(window);
  if (origFetch) {
    window.fetch = function(input, init){
      try {
        if (typeof input === "string" && input.indexOf(REMOTE) === 0) {
          input = location.origin + "/api/" + input.slice(REMOTE.length);
        } else if (input && typeof input === "object" && typeof input.url === "string" && input.url.indexOf(REMOTE) === 0) {
          input = new Request(location.origin + "/api/" + input.url.slice(REMOTE.length), input);
        }
      } catch (e) {}
      return origFetch(input, init);
    };
  }
  // --- fallback-swap observer: full-screen FlowShellFallback sightings ---
  // The route-level fallback renders a role=status spinner as a DIRECT child of
  // the full-viewport gradient host; button spinners never match this pattern.
  window.__SP_FALLBACK_SIGHTINGS = [];
  try {
    const obs = new MutationObserver((muts) => {
      for (const m of muts) {
        for (const n of m.addedNodes || []) {
          if (!(n instanceof HTMLElement)) continue;
          const spinners = n.querySelectorAll ? n.querySelectorAll('[role="status"]') : [];
          const direct = n.matches && n.matches('[role="status"]') ? [n] : [];
          for (const s of [...direct, ...spinners]) {
            const parent = s.parentElement;
            const isFullscreenFallback =
              parent && parent.className && typeof parent.className === "string" &&
              parent.className.includes("sp-fill-vh");
            window.__SP_FALLBACK_SIGHTINGS.push({
              t: Date.now(),
              fullscreen: !!isFullscreenFallback,
              cls: (s.className || "").slice(0, 60),
            });
          }
        }
      }
    });
    obs.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) {}

  // --- minimal React DevTools hook: identify which function components rendered ---
  // React 19 removed the PerformedWork flag, so a component is counted as rendered in
  // a commit when it is newly mounted, or its memoizedProps/memoizedState reference
  // differs from its alternate (double-buffer) copy.
  var injectIdCounter = 0;
  var stats = { total: 0, withRender: 0, byName: {}, last: null, errors: 0, injected: 0 };
  window.__SP_COMMITS = stats;
  function nameOf(type){
    if (type == null) return "(null)";
    if (typeof type === "string") return type;
    if (typeof type === "function") return type.displayName || type.name || "(anonymous)";
    if (typeof type === "object") {
      if (type.displayName) return type.displayName;
      if (type.type) return nameOf(type.type);
      return "(wrapper)";
    }
    return "(other)";
  }
  function rendered(fiber){
    if (fiber.alternate == null) return true;
    return fiber.memoizedProps !== fiber.alternate.memoizedProps ||
           fiber.memoizedState !== fiber.alternate.memoizedState;
  }
  function walk(fiber, counts){
    var n = 0;
    while (fiber != null) {
      if (typeof fiber.type === "function" && rendered(fiber)) {
        var labeled = null;
        if (window.__SP_TARGET_NAMES && typeof window.__SP_TARGET_NAMES.get === "function") {
          labeled = window.__SP_TARGET_NAMES.get(fiber.type);
        }
        var nm = labeled || nameOf(fiber.type);
        counts[nm] = (counts[nm] || 0) + 1;
        n++;
      }
      if (fiber.child != null) n += walk(fiber.child, counts);
      fiber = fiber.sibling;
    }
    return n;
  }
  window.__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
    supportsFiber: true,
    renderers: new Map(),
    inject: function(internals){
      stats.injected++;
      this._internals = internals;
      // React Refresh (dev) expects DevTools-compatible renderer IDs AND a
      // renderers map (hook.renderers.forEach in react-refresh-runtime).
      var id = ++injectIdCounter;
      this.renderers.set(id, internals);
      return id;
    },
    onCommitFiberRoot: function(rendererID, root){
      try {
        var counts = {};
        var renderedCount = 0;
        var c = root && root.current;
        if (c) renderedCount = walk(c, counts);
        stats.total++;
        if (renderedCount > 0) {
          stats.withRender++;
          for (var k in counts) stats.byName[k] = (stats.byName[k] || 0) + counts[k];
          stats.last = { t: Date.now(), rendered: renderedCount, names: Object.keys(counts) };
        }
      } catch (e) { stats.errors++; }
    },
    onCommitFiberUnmount: function(){},
    onPostCommitFiberRoot: function(){}
  };
})();
</script>`;

function log(entry) {
  try {
    fs.appendFileSync(LOG_PATH, JSON.stringify(entry) + "\n");
  } catch {}
}

function pipeWithInjection(upstreamRes, res, isHtml, started, meta) {
  const durMs = Date.now() - started;
  log({ ts: new Date().toISOString(), mode: state.mode, fresh: state.freshArmed, ...meta, status: upstreamRes.statusCode, durMs });
  const headers = { ...upstreamRes.headers };
  delete headers["content-security-policy"];
  delete headers["content-security-policy-report-only"];
  if (isHtml) {
    delete headers["content-length"];
    delete headers["content-encoding"];
    const chunks = [];
    upstreamRes.on("data", (c) => chunks.push(c));
    upstreamRes.on("end", () => {
      let body = Buffer.concat(chunks).toString("utf8");
      if (body.includes("<head>")) {
        body = body.replace("<head>", "<head>" + INJECTED_SCRIPT);
      } else if (body.includes("</head>")) {
        body = body.replace("</head>", INJECTED_SCRIPT + "</head>");
      } else {
        body = INJECTED_SCRIPT + body;
      }
      headers["content-type"] = "text/html; charset=utf-8";
      res.writeHead(upstreamRes.statusCode, headers);
      res.end(body);
    });
    upstreamRes.resume();
    return;
  }
  res.writeHead(upstreamRes.statusCode, headers);
  upstreamRes.pipe(res);
}

function forward(req, res, upstream, isApi) {
  const started = Date.now();
  state.counter++;
  const headers = { ...req.headers };
  headers.host = `${upstream.host}:${upstream.port}`;
  // Serve everything uncompressed so the HTML injection can operate on plain text
  // and pass-through responses keep their declared content-length.
  delete headers["accept-encoding"];
  let stripCookie = false;
  if (isApi && state.freshArmed) {
    stripCookie = true;
    delete headers.cookie;
  }
  const meta = { method: req.method, url: req.url, cookieStripped: stripCookie };
  if (state.mode === "failure" && isApi) {
    const durMs = Date.now() - started;
    log({ ts: new Date().toISOString(), mode: state.mode, fresh: state.freshArmed, ...meta, status: "CONNECTION_DESTROYED", durMs });
    req.resume();
    res.destroy();
    return;
  }
  const proxyReq = http.request(
    { host: upstream.host, port: upstream.port, path: req.url, method: req.method, headers },
    (upstreamRes) => {
      if (isApi && state.freshArmed && req.method === "POST" && req.url.startsWith("/api/soulmate/sessions")) {
        state.freshArmed = false; // new session bootstrapped; stop stripping cookies
      }
      const isHtml = (upstreamRes.headers["content-type"] || "").includes("text/html");
      if (state.mode === "latency" && isApi) {
        setTimeout(() => pipeWithInjection(upstreamRes, res, isHtml, started, meta), 500);
      } else {
        pipeWithInjection(upstreamRes, res, isHtml, started, meta);
      }
    }
  );
  proxyReq.on("error", (err) => {
    const durMs = Date.now() - started;
    log({ ts: new Date().toISOString(), mode: state.mode, fresh: state.freshArmed, ...meta, status: "UPSTREAM_ERROR", durMs, error: String(err) });
    if (!res.headersSent) res.writeHead(502, { "content-type": "application/json" });
    res.end(JSON.stringify({ error: "proxy upstream error" }));
  });
  req.pipe(proxyReq);
}

http
  .createServer((req, res) => {
    if (req.url.startsWith("/api/")) forward(req, res, BACKEND_UPSTREAM, true);
    else forward(req, res, FRONTEND_UPSTREAM, false);
  })
  .listen(BROWSER_PORT, "127.0.0.1", () => console.log(`browser proxy on :${BROWSER_PORT}`));

http
  .createServer((req, res) => {
    const json = (obj) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify(obj));
    };
    if (req.url.startsWith("/mode/")) {
      const m = req.url.split("/mode/")[1];
      if (["normal", "latency", "failure"].includes(m)) {
        state.mode = m;
        return json({ mode: state.mode, freshArmed: state.freshArmed });
      }
      return json({ error: "unknown mode" });
    }
    if (req.url === "/fresh") {
      state.freshArmed = true;
      return json({ freshArmed: state.freshArmed, mode: state.mode });
    }
    if (req.url === "/status") return json(state);
    if (req.url === "/log/reset") {
      try { fs.writeFileSync(LOG_PATH, ""); } catch {}
      return json({ logReset: true });
    }
    if (req.url.startsWith("/log")) {
      const n = parseInt(new URL(req.url, "http://x").searchParams.get("n") || "40", 10);
      let lines = [];
      try {
        lines = fs.readFileSync(LOG_PATH, "utf8").trim().split("\n").filter(Boolean).slice(-n);
      } catch {}
      res.writeHead(200, { "content-type": "text/plain" });
      return res.end(lines.join("\n") || "(empty)");
    }
    res.writeHead(404);
    res.end();
  })
  .listen(CONTROL_PORT, "127.0.0.1", () => console.log(`control plane on :${CONTROL_PORT}`));
