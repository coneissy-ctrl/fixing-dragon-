import http from "node:http";
import crypto from "node:crypto";

const PORT = Number(process.env.PORT || 10000);
const CLIENT_ID = process.env.DERIV_CLIENT_ID || process.env.DERIV_APP_ID || "";
const DERIV_PAT = process.env.DERIV_PAT || "";
const DERIV_APP_ID = process.env.DERIV_APP_ID || CLIENT_ID || "";
const REDIRECT_URI = process.env.DERIV_REDIRECT_URI || "";
const API_KEY = process.env.DERIV_BACKEND_API_KEY || "";
const LIVE_EXECUTION_ENABLED = process.env.DERIV_LIVE_EXECUTION_ENABLED === "true";

const states = new Map();
let session = null;

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

async function derivFetch(path, options = {}) {
  if (!session?.accessToken) throw new Error("Deriv account is not connected");
  const headers = {
    authorization: `Bearer ${session.accessToken}`,
    accept: "application/json",
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
  const data = await r.json();
  if (!r.ok) throw new Error("Unable to read Deriv accounts");
  return data?.data?.accounts || data?.accounts || [];
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

  if (url.pathname === "/health") {
    return json(res, 200, { ok: true, service: "dragon-deriv-options-engine", connected: !!session });
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
    if (!session?.accessToken) return json(res, 200, { connected: false });
    try {
      const account = await connectedAccount();
      const wsUrl = await getOtpUrl(account.accountId);
      const balance = await wsRequest(wsUrl, { balance: 1, subscribe: 0, req_id: 1 });
      return json(res, 200, {
        connected: true,
        loginid: account.loginId,
        account_type: account.accountType,
        currency: balance?.balance?.currency || account.currency,
        scopes: ["trade"],
        live_execution_enabled: LIVE_EXECUTION_ENABLED && account.accountType === "real",
        expires_at: new Date(session.expiresAt).toISOString(),
      });
    } catch (e) {
      return json(res, 200, { connected: false, error: e.message });
    }
  }

  if (!authOK(req)) return json(res, 401, { error: "unauthorized" });
  if (!session?.accessToken) return json(res, 401, { error: "deriv_not_connected" });

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
