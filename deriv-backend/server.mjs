import http from "node:http";
import crypto from "node:crypto";

const PORT = Number(process.env.PORT || 10000);
const CLIENT_ID = process.env.DERIV_CLIENT_ID || process.env.DERIV_APP_ID || "";
const DERIV_PAT = process.env.DERIV_PAT || "";
const DERIV_APP_ID = process.env.DERIV_APP_ID || CLIENT_ID || "";
const REDIRECT_URI = process.env.DERIV_REDIRECT_URI || "";
const API_KEY = process.env.DERIV_BACKEND_API_KEY || "";
const LIVE_EXECUTION_ENABLED = process.env.DERIV_LIVE_EXECUTION_ENABLED === "true";

const TRADING_CONFIG = Object.freeze({
  stake: 0.50,
  timeframeMinutes: 5,
  expiryMinutes: 5,
  confidenceMin: 80,
  maxEntries: 5,
  maxRecoveryAttempts: 1,
  thirdMartingale: false,
  newsTrading: false,
  superHighVolatility: false,
  drawdownStopPct: 30,
  liveExecution: false,
  entrySeconds: [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55],
  watchlist: [
    "frxEURUSD","frxGBPUSD","frxUSDJPY","frxAUDUSD","frxUSDCAD",
    "frxUSDCHF","frxEURGBP","frxEURJPY","frxGBPJPY","frxXAUUSD",
    "R_10","R_25","R_50","R_75","R_100","1HZ10V","1HZ25V","1HZ50V","1HZ75V","1HZ100V"
  ],
});

const paperSession = {
  startedAt: new Date().toISOString(),
  entries: 0,
  wins: 0,
  losses: 0,
  recoveryAttempts: 0,
  pnl: 0,
  peakEquity: 0,
  hardStopped: false,
  lastEntry: null,
  signals: [],
};

const candleCache = new Map();

async function marketRequest(payload, timeoutMs = 8000) {
  return wsRequest("wss://ws.derivws.com/websockets/v3?app_id=" + encodeURIComponent(DERIV_APP_ID || "1089"), payload, timeoutMs);
}

async function getCandles(symbol, count = 60) {
  const result = await marketRequest({
    ticks_history: symbol,
    style: "candles",
    granularity: 300,
    count,
    end: "latest",
  });
  const candles = result?.candles || [];
  if (candles.length) candleCache.set(symbol, candles);
  return candles;
}

function calcSignal(candles) {
  if (candles.length < 30) return { direction: null, confidence: 0, reason: "insufficient_data" };
  const closes = candles.map(c => Number(c.close));
  const ema = (period) => {
    const k = 2 / (period + 1);
    let e = closes[0];
    for (let i = 1; i < closes.length; i++) e = closes[i] * k + e * (1 - k);
    return e;
  };
  const e9 = ema(9), e21 = ema(21);
  const gains = [], losses = [];
  for (let i = 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    gains.push(Math.max(d, 0)); losses.push(Math.max(-d, 0));
  }
  const avgGain = gains.slice(-14).reduce((a,b)=>a+b,0) / 14;
  const avgLoss = losses.slice(-14).reduce((a,b)=>a+b,0) / 14;
  const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
  const rsi = 100 - (100 / (1 + rs));
  const last = closes[closes.length - 1];
  const momentum = closes[closes.length - 1] - closes[closes.length - 4];
  let score = 50;
  let direction = null;
  if (e9 > e21) { direction = "CALL"; score += 20; }
  if (e9 < e21) { direction = "PUT"; score += 20; }
  if (direction === "CALL" && rsi >= 50 && rsi <= 70) score += 15;
  if (direction === "PUT" && rsi <= 50 && rsi >= 30) score += 15;
  if (direction === "CALL" && momentum > 0) score += 10;
  if (direction === "PUT" && momentum < 0) score += 10;
  const confidence = Math.min(99, Math.round(score));
  return { direction, confidence, rsi: Number(rsi.toFixed(2)), price: last, ema9: e9, ema21: e21 };
}

async function scanWatchlist() {
  const results = [];
  for (const symbol of TRADING_CONFIG.watchlist) {
    try {
      const candles = await getCandles(symbol);
      const signal = calcSignal(candles);
      results.push({ symbol, ...signal, eligible: signal.confidence >= TRADING_CONFIG.confidenceMin });
    } catch (e) {
      results.push({ symbol, eligible: false, confidence: 0, error: e.message });
    }
  }
  paperSession.signals = results;
  return results;
}

function isEntryTime(date = new Date()) {
  return TRADING_CONFIG.entrySeconds.includes(date.getSeconds()) && date.getMilliseconds() < 1500;
}

function drawdownPct() {
  const peak = Math.max(0.01, paperSession.peakEquity);
  return Math.max(0, ((peak - Math.min(peak, paperSession.pnl)) / peak) * 100);
}

async function paperCycle() {
  if (paperSession.hardStopped) return;
  if (!isEntryTime()) return;
  if (paperSession.entries >= TRADING_CONFIG.maxEntries) return;
  const signals = await scanWatchlist();
  const candidates = signals.filter(s => s.eligible && (s.direction === "CALL" || s.direction === "PUT"));
  candidates.sort((a,b) => b.confidence - a.confidence);
  const pick = candidates[0];
  if (!pick) return;
  paperSession.entries += 1;
  paperSession.lastEntry = {
    at: new Date().toISOString(),
    symbol: pick.symbol,
    direction: pick.direction,
    stake: TRADING_CONFIG.stake,
    expiryMinutes: TRADING_CONFIG.expiryMinutes,
    confidence: pick.confidence,
    mode: "paper",
  };
  paperSession.peakEquity = Math.max(paperSession.peakEquity, paperSession.pnl + TRADING_CONFIG.stake);
}

const states = new Map();
let session = null;

// 30-second execution-readiness cycle. This refreshes account connectivity
// and prepares executor state; it does not place trades automatically.
const EXECUTOR_INTERVAL_MS = 30_000;
let executorTimer = null;
let executorRunning = false;
const executorState = {
  intervalSeconds: 30,
  running: false,
  lastRunAt: null,
  nextRunAt: null,
  lastStatus: "starting",
  lastError: null,
  cycles: 0,
};

async function executorCycle() {
  if (executorRunning) return;
  executorRunning = true;
  executorState.running = true;
  executorState.lastRunAt = new Date().toISOString();
  executorState.nextRunAt = new Date(Date.now() + EXECUTOR_INTERVAL_MS).toISOString();
  executorState.lastError = null;
  try {
    if (!authToken()) {
      executorState.lastStatus = "waiting_for_connection";
      return;
    }
    const account = await connectedAccount();
    executorState.lastStatus = account.accountType === "real" ? "ready" : "demo_account";
    executorState.cycles += 1;
  } catch (e) {
    executorState.lastStatus = "error";
    executorState.lastError = e.message;
  } finally {
    executorRunning = false;
    executorState.running = false;
  }
}

function startExecutor() {
  if (executorTimer) return;
  executorState.nextRunAt = new Date(Date.now() + EXECUTOR_INTERVAL_MS).toISOString();
  executorTimer = setInterval(() => executorCycle().catch(() => {}), EXECUTOR_INTERVAL_MS);
  executorCycle().catch(() => {});
}

startExecutor();
const PAPER_SCAN_INTERVAL_MS = 1000;
let paperTimer = null;
function startPaperEngine() {
  if (paperTimer) return;
  paperTimer = setInterval(() => paperCycle().catch(() => {}), PAPER_SCAN_INTERVAL_MS);
}
startPaperEngine();


function json(res, status, body) {
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": process.env.FRONTEND_ORIGIN || "*",
    "access-control-allow-headers": "content-type, authorization",
    "access-control-allow-methods": "GET,POST,OPTIONS",
  });
  res.end(JSON.stringify(body));
}

function redirect(res, url) {
  res.writeHead(302, { location: url, "cache-control": "no-store" });
  res.end();
}

function authOK(req) {
  if (!API_KEY) return true;
  return req.headers.authorization === `Bearer ${API_KEY}`;
}

async function body(req) {
  let data = "";
  for await (const chunk of req) data += chunk;
  if (!data) return {};
  try { return JSON.parse(data); } catch { return {}; }
}

function pkceVerifier() {
  return crypto.randomBytes(48).toString("base64url");
}

function pkceChallenge(verifier) {
  return crypto.createHash("sha256").update(verifier).digest("base64url");
}

function randomState() {
  return crypto.randomBytes(32).toString("base64url");
}

function authToken() {
  const pat = String(DERIV_PAT || "").trim();
  const oauth = String(session?.accessToken || "").trim();
  return pat || oauth || "";
}

function authMode() {
  if (String(DERIV_PAT || "").trim()) return "pat";
  if (session?.accessToken) return "oauth";
  return "none";
}

async function derivFetch(path, options = {}) {
  const token = authToken();
  if (!token) throw new Error("Deriv account is not connected");
  const headers = {
    authorization: `Bearer ${token}`,
    accept: "application/json",
    ...(DERIV_PAT ? { "Deriv-App-ID": DERIV_APP_ID } : {}),
    ...(options.headers || {}),
  };
  return fetch("https://api.derivws.com" + path, { ...options, headers });
}

async function getOtpUrl(accountId) {
  const r = await derivFetch(`/trading/v1/options/accounts/${encodeURIComponent(accountId)}/otp`, { method: "POST" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok || !data?.data?.url) {
    const detail = data?.errors?.[0]?.message || data?.error?.message || data?.message || `HTTP ${r.status}`;
    throw new Error(`Deriv OTP generation failed: ${detail}`);
  }
  return data.data.url;
}

async function wsRequest(url, payload, timeoutMs = 10000) {
  const ws = new WebSocket(url);
  return await new Promise((resolve, reject) => {
    let timer;
    const finish = (fn, value) => {
      clearTimeout(timer);
      try { ws.close(); } catch {}
      fn(value);
    };
    timer = setTimeout(() => finish(reject, new Error("Deriv WebSocket timeout")), timeoutMs);
    ws.onerror = () => finish(reject, new Error("Deriv WebSocket connection failed"));
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(String(event.data));
        if (msg.error) finish(reject, new Error(msg.error.message || "Deriv request failed"));
        else finish(resolve, msg);
      } catch {
        finish(reject, new Error("Invalid Deriv WebSocket response"));
      }
    };
    ws.onopen = () => ws.send(JSON.stringify(payload));
  });
}

async function accounts() {
  const r = await derivFetch("/trading/v1/options/accounts");
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const detail = data?.errors?.[0]?.message || data?.error?.message || data?.message || `HTTP ${r.status}`;
    throw new Error(`Unable to read Deriv accounts: ${detail}`);
  }
  const accounts = data?.data?.accounts || data?.accounts || data?.data || [];
  return Array.isArray(accounts) ? accounts : [accounts].filter(Boolean);
}

async function connectedAccount() {
  const list = await accounts();
  const account = list.find(a => a.account_id || a.loginid);
  if (!account) throw new Error("No Deriv Options account found");
  return {
    accountId: account.account_id || account.loginid,
    loginId: account.loginid || account.account_id || null,
    accountType: String(account.account_type || "").toLowerCase().includes("real") ? "real" : "demo",
    currency: account.currency || null,
  };
}

async function callbackRedirect(returnTo, params) {
  const u = new URL(returnTo);
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return u.toString();
}

async function handle(req, res) {
  if (req.method === "OPTIONS") return json(res, 204, {});
  const url = new URL(req.url, "http://localhost");

  if (url.pathname === "/api/deriv/config" && req.method === "GET") {
    return json(res, 200, { ...TRADING_CONFIG, mode: "paper", live_execution_enabled: false });
  }

  if (url.pathname === "/api/deriv/session" && req.method === "GET") {
    return json(res, 200, {
      ...paperSession,
      drawdown_pct: Number(drawdownPct().toFixed(2)),
      remaining_entries: Math.max(0, TRADING_CONFIG.maxEntries - paperSession.entries),
      next_entry_window: TRADING_CONFIG.entrySeconds,
      mode: "paper",
      live_execution_enabled: false,
    });
  }

  if (url.pathname === "/api/deriv/signals" && req.method === "GET") {
    try {
      const signals = await scanWatchlist();
      return json(res, 200, { generatedAt: new Date().toISOString(), signals, config: TRADING_CONFIG });
    } catch (e) {
      return json(res, 502, { error: e.message });
    }
  }

  if (url.pathname === "/api/deriv/paper/cycle" && req.method === "POST") {
    try {
      await paperCycle();
      return json(res, 200, { ok: true, session: paperSession, config: TRADING_CONFIG });
    } catch (e) {
      return json(res, 502, { error: e.message });
    }
  }

  if (url.pathname === "/api/deriv/executor/status" && req.method === "GET") {
    return json(res, 200, { ...executorState, intervalMs: EXECUTOR_INTERVAL_MS });
  }

  if (url.pathname === "/dashboard" && req.method === "GET") {
    res.writeHead(200, {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": process.env.FRONTEND_ORIGIN || "*",
    });
    return res.end(`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DerivOnly Live Dashboard</title>
<style>
body{margin:0;background:#0b1020;color:#eef2ff;font:14px system-ui,Segoe UI,sans-serif}
.wrap{max-width:1400px;margin:auto;padding:22px}.top{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}
h1{margin:0;font-size:25px}.muted{color:#9aa6bf}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:18px 0}
.card{background:#121a2d;border:1px solid #24304a;border-radius:14px;padding:16px}.big{font-size:25px;font-weight:700;margin-top:7px}
.ok{color:#55e39a}.warn{color:#ffd166}.danger{color:#ff6b7a}
table{width:100%;border-collapse:collapse}.card table{margin-top:8px}th,td{text-align:left;padding:9px;border-bottom:1px solid #202b43}th{color:#9aa6bf;font-weight:500}
.pill{display:inline-block;padding:5px 9px;border-radius:99px;background:#1b2740}.bar{height:8px;background:#202b43;border-radius:9px;overflow:hidden}.fill{height:100%;background:#55e39a}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.grid{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<div class="top"><div><h1>DerivOnly — Live Paper Dashboard</h1><div class="muted">5-minute CALL / PUT engine · live market data · real execution OFF</div></div><div id="clock" class="pill">--</div></div>
<div class="grid">
<div class="card"><div class="muted">MODE</div><div class="big ok">PAPER</div></div>
<div class="card"><div class="muted">STAKE</div><div class="big">$0.50</div></div>
<div class="card"><div class="muted">ENTRIES</div><div class="big" id="entries">0 / 5</div></div>
<div class="card"><div class="muted">DRAWDOWN</div><div class="big" id="dd">0%</div></div>
</div>
<div class="grid">
<div class="card"><div class="muted">5-MIN EXPIRY</div><div class="big">ACTIVE</div></div>
<div class="card"><div class="muted">CONFIDENCE</div><div class="big">≥80</div></div>
<div class="card"><div class="muted">RECOVERY</div><div class="big">1 MAX</div></div>
<div class="card"><div class="muted">3RD MARTINGALE</div><div class="big ok">OFF</div></div>
</div>
<div class="card"><h3>Session</h3><div id="session">Loading...</div></div>
<div class="card" style="margin-top:12px"><h3>20-Instrument Watchlist</h3><table><thead><tr><th>Instrument</th><th>Signal</th><th>Confidence</th><th>Price</th><th>Status</th></tr></thead><tbody id="rows"></tbody></table></div>
</div>
<script>
const $=id=>document.getElementById(id);
async function get(p){const r=await fetch(p,{cache:"no-store"});return r.json()}
async function refresh(){
 try{
  const [cfg,sess,sig]=await Promise.all([get("/api/deriv/config"),get("/api/deriv/session"),get("/api/deriv/signals")]);
  $("entries").textContent=sess.entries+" / "+cfg.maxEntries;
  $("dd").textContent=(sess.drawdown_pct||0).toFixed(1)+"%";
  $("session").innerHTML="<span class='pill'>Last entry: "+(sess.lastEntry?sess.lastEntry.symbol+" · "+sess.lastEntry.direction+" · "+sess.lastEntry.confidence+"%":"none")+"</span> <span class='pill'>Recovery: "+sess.recoveryAttempts+" / "+cfg.maxRecoveryAttempts+"</span> <span class='pill'>Hard stop: "+(sess.hardStopped?"YES":"NO")+"</span>";
  $("rows").innerHTML=sig.signals.map(s=>"<tr><td>"+s.symbol+"</td><td>"+(s.direction||"—")+"</td><td>"+(s.confidence||0)+"%</td><td>"+(s.price??"—")+"</td><td>"+(s.eligible?"<span class='ok'>ELIGIBLE</span>":"<span class='muted'>WAIT</span>")+"</td></tr>").join("");
  $("clock").textContent=new Date().toLocaleTimeString();
 }catch(e){$("session").textContent="Dashboard data error: "+e.message}
}
refresh();setInterval(refresh,5000);setInterval(()=>{$("clock").textContent=new Date().toLocaleTimeString()},1000);
</script></body></html>`);
  }

  if (url.pathname === "/health") {
    return json(res, 200, {
      ok: true,
      service: "dragon-deriv-options-engine",
      connected: !!authToken(),
      auth_mode: authMode(),
      pat_configured: !!String(DERIV_PAT || "").trim(),
      app_id_configured: !!String(DERIV_APP_ID || "").trim(),
      live_execution_enabled: LIVE_EXECUTION_ENABLED,
    });
  }

  if (url.pathname === "/oauth/deriv/start" && req.method === "GET") {
    if (!CLIENT_ID || !REDIRECT_URI) return json(res, 503, { error: "Deriv OAuth is not configured" });
    const returnTo = url.searchParams.get("return_to") || process.env.OAUTH_RETURN_TO || process.env.FRONTEND_ORIGIN;
    if (!returnTo) return json(res, 400, { error: "return_to is required; set OAUTH_RETURN_TO or FRONTEND_ORIGIN" });
    const scope = url.searchParams.get("scope") || "trade";
    const state = randomState();
    const verifier = pkceVerifier();
    states.set(state, { verifier, returnTo, createdAt: Date.now() });
    const auth = new URL("https://auth.deriv.com/oauth2/auth");
    auth.searchParams.set("response_type", "code");
    auth.searchParams.set("client_id", CLIENT_ID);
    auth.searchParams.set("redirect_uri", REDIRECT_URI);
    auth.searchParams.set("scope", scope);
    auth.searchParams.set("state", state);
    auth.searchParams.set("code_challenge", pkceChallenge(verifier));
    auth.searchParams.set("code_challenge_method", "S256");
    return redirect(res, auth.toString());
  }

  if (url.pathname === "/oauth/deriv/callback" && req.method === "GET") {
    const state = url.searchParams.get("state");
    const code = url.searchParams.get("code");
    const pending = state ? states.get(state) : null;
    if (!pending || Date.now() - pending.createdAt > 10 * 60 * 1000) {
      return json(res, 400, { error: "invalid_state" });
    }
    states.delete(state);
    if (!code) {
      const error = url.searchParams.get("error") || "missing_code";
      const detail = url.searchParams.get("error_description") || "";
      return redirect(res, await callbackRedirect(pending.returnTo, { error, detail }));
    }

    const tokenBody = new URLSearchParams({
      grant_type: "authorization_code",
      client_id: CLIENT_ID,
      code,
      code_verifier: pending.verifier,
      redirect_uri: REDIRECT_URI,
    });
    const tokenRes = await fetch("https://auth.deriv.com/oauth2/token", {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
      body: tokenBody,
    });
    const token = await tokenRes.json().catch(() => ({}));
    if (!tokenRes.ok || !token.access_token) {
      console.error("Deriv OAuth token exchange failed:", JSON.stringify(token));
      return redirect(res, await callbackRedirect(pending.returnTo, {
        error: "token_exchange_failed",
        detail: token?.error_description || token?.error || `HTTP ${tokenRes.status}`,
      }));
    }

    session = { accessToken: token.access_token, expiresAt: Date.now() + Number(token.expires_in || 3600) * 1000 };
    console.log("Deriv OAuth authorization completed successfully");
    return redirect(res, await callbackRedirect(pending.returnTo, { status: "success" }));
  }

  if (url.pathname === "/oauth/deriv/status" && req.method === "GET") {
    if (!authOK(req)) return json(res, 401, { error: "unauthorized" });
    if (!authToken()) return json(res, 200, { connected: false, auth_mode: "none" });
    try {
      const account = await connectedAccount();
      const wsUrl = await getOtpUrl(account.accountId);
      const balance = await wsRequest(wsUrl, { balance: 1, subscribe: 0, req_id: 1 });
      return json(res, 200, {
        connected: true,
        loginid: account.loginId,
        account_type: account.accountType,
        currency: balance?.balance?.currency || account.currency,
        auth_mode: authMode(),
        scopes: ["trade"],
        live_execution_enabled: LIVE_EXECUTION_ENABLED && account.accountType === "real",
        expires_at: DERIV_PAT ? null : (session?.expiresAt ? new Date(session.expiresAt).toISOString() : null),
      });
    } catch (e) {
      return json(res, 200, { connected: false, error: e.message });
    }
  }

  if (!authOK(req)) return json(res, 401, { error: "unauthorized" });
  if (!authToken()) return json(res, 401, {
    error: "deriv_not_connected",
    auth_mode: authMode(),
    pat_configured: !!String(DERIV_PAT || "").trim(),
    app_id_configured: !!String(DERIV_APP_ID || "").trim(),
  });

  if (url.pathname === "/api/deriv/balance" && req.method === "GET") {
    const account = await connectedAccount();
    const wsUrl = await getOtpUrl(account.accountId);
    const result = await wsRequest(wsUrl, { balance: 1, subscribe: 0, req_id: 1 });
    return json(res, 200, result);
  }

  if (url.pathname === "/api/deriv/proposal" && req.method === "POST") {
    const input = await body(req);
    const account = await connectedAccount();
    const wsUrl = await getOtpUrl(account.accountId);
    return json(res, 200, await wsRequest(wsUrl, { ...input, proposal: 1, req_id: 1 }));
  }

  if (url.pathname === "/api/deriv/buy" && req.method === "POST") {
    if (!LIVE_EXECUTION_ENABLED) return json(res, 403, { error: "live_execution_disabled" });
    const input = await body(req);
    const account = await connectedAccount();
    if (account.accountType !== "real") return json(res, 403, { error: "real_account_required" });
    const wsUrl = await getOtpUrl(account.accountId);
    return json(res, 200, await wsRequest(wsUrl, { ...input, req_id: 1 }));
  }

  if (url.pathname === "/api/deriv/disconnect" && req.method === "POST") {
    session = null;
    return json(res, 200, { disconnected: true });
  }

  return json(res, 404, { error: "not_found" });
}

const server = http.createServer((req, res) => {
  handle(req, res).catch((e) => {
    console.error("Deriv engine error:", e.message);
    json(res, 500, { error: "internal_error" });
  });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`Dragon Deriv Options Engine listening on 0.0.0.0:${PORT}`);
});
