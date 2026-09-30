"""Small dependency-light dashboard for the Deriv live-data monitor."""
from __future__ import annotations

import asyncio
import html
import json
import os
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit
from typing import Any


@dataclass
class DashboardState:
    symbol: str = "R_100"
    status: str = "STARTING"
    connected_at: float | None = None
    updated_at: float | None = None
    last_tick_at: float | None = None
    quote: str | None = None
    tick_count: int = 0
    candles: dict[int, int] = field(default_factory=lambda: {1: 0, 5: 0})
    signals: dict[int, int] = field(default_factory=lambda: {1: 0, 5: 0})
    last_signals: dict[int, dict[str, Any]] = field(default_factory=dict)
    last_tick: dict[str, Any] | None = None
    auth_error: str | None = None
    account_id: str | None = None
    account_mode: str = "demo"
    live_execution_enabled: bool = False
    balance: str | None = None
    balance_updated_at: float | None = None
    balance_error: str | None = None

    def payload(self) -> dict[str, Any]:
        authenticated = self.status in {"AUTHENTICATED_READ_ONLY", "LIVE_ACCOUNT_CONNECTED"}
        execution = (
            "REAL_ENABLED / AUTHENTICATED"
            if self.account_mode == "real" and self.live_execution_enabled and authenticated
            else "REAL_ENABLED / AUTH_REQUIRED"
            if self.account_mode == "real" and self.live_execution_enabled
            else "DEMO / AUTHENTICATED"
            if authenticated
            else "AUTH_REQUIRED"
        )
        return {
            "status": self.status,
            "symbol": self.symbol,
            "connected_at": self.connected_at,
            "updated_at": self.updated_at,
            "last_tick_at": self.last_tick_at,
            "quote": self.quote,
            "tick_count": self.tick_count,
            "candles": self.candles,
            "signals": self.signals,
            "last_signals": self.last_signals,
            "execution": execution,
            "real_money": self.account_mode == "real" and self.live_execution_enabled,
            "authenticated": authenticated,
            "account_id": (f"...{self.account_id[-4:]}" if self.account_id else None),
            "account_mode": self.account_mode,
            "live_execution_enabled": self.live_execution_enabled,
            "balance": self.balance,
            "balance_updated_at": self.balance_updated_at,
            "balance_error": self.balance_error,
            "auth_error": self.auth_error,
            "stakes": {"1m": "0.50", "5m": "2.00"},
            "martingale": False,
        }


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dragon Options Engine</title>
<style>
body{margin:0;background:#07111d;color:#edf5ff;font:14px system-ui;padding:20px}
.wrap{max-width:1100px;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.card{background:#0d1a29;border:1px solid #20364c;border-radius:14px;padding:16px;margin-top:14px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.v{font-size:25px;font-weight:800;margin-top:5px}
.muted{color:#8da3bb;font-size:11px;text-transform:uppercase}.ok{color:#65dfa0}.safe{color:#ffc96b}.danger{color:#ff7b7b}
.signal{padding:12px;background:#101f31;border-radius:10px;margin-top:8px}.mono{font-family:monospace;word-break:break-word}
@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}}a{color:#65dfa0;font-weight:800}
</style></head>
<body><div class="wrap">
<div class="top"><div><div class="muted">DRAGON OPTIONS ENGINE</div><h1>Deriv Options Engine</h1>
<div class="muted">Live market data - authenticated account channel when connected</div></div>
<div id="status" class="safe">CONNECTING</div></div>
<div class="grid">
<div class="card"><div class="muted">Symbol</div><div id="symbol" class="v">--</div></div>
<div class="card"><div class="muted">Live quote</div><div id="quote" class="v">--</div></div>
<div class="card"><div class="muted">Ticks</div><div id="ticks" class="v">0</div></div>
<div class="card"><div class="muted">Execution</div><div id="execution" class="v safe">AUTH REQUIRED</div></div>
<div class="card"><div class="muted">Real balance</div><div id="balance" class="v">--</div><div id="balanceMeta" class="muted">Connect Deriv</div></div>
</div>
<div class="card"><div class="muted">Completed candles</div><div class="grid">
<div><div>1-minute</div><div id="c1" class="v">0</div></div>
<div><div>5-minute</div><div id="c5" class="v">0</div></div>
<div><div>1m signals</div><div id="s1" class="v">0</div></div>
<div><div>5m signals</div><div id="s5" class="v">0</div></div>
</div></div>
<div class="card"><div class="muted">Deriv account</div>
<div><a href="/auth/deriv/login">CONNECT DERIV ACCOUNT</a></div>
<div id="account">Not authenticated</div>
<div id="authmsg">OAuth authorization is required before account-scoped operations.</div>
<div>Configured stakes: 1m = $0.50 - 5m = $2.00 - Martingale = OFF</div>
</div>
<div class="card"><div class="muted">Latest signals</div><div id="signals">Waiting for completed candles...</div></div>
</div>
<script>
async function load(){
try{
let r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});let d=await r.json();
status.textContent=d.status;
status.className=d.status==='LIVE_DATA'||d.status==='LIVE_ACCOUNT_CONNECTED'||d.status==='AUTHENTICATED_READ_ONLY'?'ok':'safe';
symbol.textContent=d.symbol;quote.textContent=d.quote||'--';ticks.textContent=d.tick_count;execution.textContent=d.execution;
execution.className='v '+(d.real_money&&d.authenticated?'ok':'safe');
balance.textContent=d.balance!==null&&d.balance!==undefined?(String(d.balance)+' USD'):'--';
balanceMeta.textContent=d.balance_updated_at?'Live balance - '+new Date(d.balance_updated_at*1000).toLocaleTimeString():(d.balance_error||'Connect Deriv');
c1.textContent=d.candles['1']||0;c5.textContent=d.candles['5']||0;s1.textContent=d.signals['1']||0;s5.textContent=d.signals['5']||0;
account.textContent=(d.account_id?'Account '+d.account_id+' - ':'')+String(d.account_mode||'demo').toUpperCase()+(d.authenticated?' - AUTHENTICATED':' - NOT AUTHENTICATED');
authmsg.textContent=d.auth_error?'Last OAuth/API error: '+d.auth_error:'OAuth/account authentication status is shown above.';
let x=[];
for(let tf of [1,5]){
let s=d.last_signals[String(tf)]||d.last_signals[tf];
if(s)x.push('<div class="signal"><b>'+tf+'m '+s.direction+'</b> - stake $'+s.stake+' - confidence '+s.confidence+' - expiry '+s.expiry_seconds+'s<br><span class="muted">'+s.reason+'</span></div>')
}
signals.innerHTML=x.join('')||'Waiting for qualifying completed candles...'
}catch(e){status.textContent='OFFLINE';status.className='danger'}
}
load();setInterval(load,1000)
</script></body></html>"""


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: DashboardState,
    oauth_login,
    oauth_callback,
    oauth_status,
) -> None:
    try:
        request = await asyncio.wait_for(reader.readline(), 5)
        parts = request.decode("utf-8", "ignore").split(" ")
        if len(parts) < 2:
            return
        target = parts[1]
        path = urlsplit(target).path
        query = parse_qs(urlsplit(target).query)
        while await reader.readline() not in (b"
", b"
", b""):
            pass

        if path == "/account/balance":
            payload = state.payload()
            if not payload["authenticated"]:
                body = json.dumps({"authenticated": False, "balance": None, "error": "Deriv OAuth authentication required"}, separators=(",", ":")).encode()
            else:
                body = json.dumps({
                    "authenticated": True,
                    "account_id": payload["account_id"],
                    "account_mode": payload["account_mode"],
                    "balance": payload["balance"],
                    "updated_at": payload["balance_updated_at"],
                    "error": payload.get("balance_error"),
                }, separators=(",", ":")).encode()
            content_type = "application/json"
        elif path == "/health":
            body = json.dumps(state.payload(), separators=(",", ":")).encode()
            content_type = "application/json"
        elif path in {"/auth/deriv/login", "/oauth/deriv/start"}:
            return_to = query.get("return_to", [None])[0]
            location = oauth_login(return_to)
            head = (
                "HTTP/1.1 302 Found
"
                f"Location: {location}
"
                "Cache-Control: no-store
"
                "Content-Length: 0

"
            ).encode()
            writer.write(head)
            await writer.drain()
            return
        elif path == "/oauth/deriv/status":
            body = json.dumps(oauth_status(), separators=(",", ":")).encode()
            content_type = "application/json"
        elif path == "/oauth/deriv/callback":
            error = query.get("error", [None])[0]
            if error:
                description = query.get("error_description", [""])[0]
                state.auth_error = f"{error}: {description}" if description else error
                body = f"OAuth failed: {html.escape(state.auth_error)}".encode()
                content_type = "text/html; charset=utf-8"
            else:
                code = query.get("code", [None])[0]
                state_token = query.get("state", [None])[0]
                if not code or not state_token:
                    state.auth_error = "OAuth callback missing code/state"
                    body = state.auth_error.encode()
                    content_type = "text/plain"
                else:
                    try:
                        await oauth_callback(code, state_token)
                        state.auth_error = None
                        owner = getattr(oauth_callback, "__self__", None)
                        destination = getattr(owner, "oauth_return_url", None)
                        if destination:
                            sep = "&" if "?" in destination else "?"
                            location = destination + sep + "status=success"
                            head = (
                                "HTTP/1.1 302 Found
"
                                f"Location: {location}
"
                                "Cache-Control: no-store
"
                                "Content-Length: 0

"
                            ).encode()
                            writer.write(head)
                            await writer.drain()
                            return
                        body = b"Deriv OAuth authentication successful. Return to the dashboard."
                    except Exception as exc:
                        state.auth_error = f"{type(exc).__name__}: {exc}"
                        body = f"Deriv OAuth authentication failed: {html.escape(state.auth_error)}".encode()
                    content_type = "text/html; charset=utf-8"
        else:
            body = HTML.encode()
            content_type = "text/html; charset=utf-8"

        head = (
            "HTTP/1.1 200 OK
"
            f"Content-Type: {content_type}
"
            "Cache-Control: no-store
"
            f"Content-Length: {len(body)}
"
            "Connection: close

"
        ).encode()
        writer.write(head + body)
        await writer.drain()
    except Exception as exc:
        print(f"DASHBOARD_REQUEST_ERROR type={type(exc).__name__} error={exc}", flush=True)
    finally:
        writer.close()
        await writer.wait_closed()


async def serve_dashboard(
    state: DashboardState,
    oauth_login,
    oauth_callback,
    oauth_status,
) -> asyncio.AbstractServer:
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    return await asyncio.start_server(
        lambda r, w: _handle(r, w, state, oauth_login, oauth_callback, oauth_status),
        host,
        port,
        reuse_address=True,
    )
