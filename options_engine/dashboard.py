"""Small dependency-light dashboard for the Deriv live-data monitor."""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses
from urllib.parse import parse_qs, urlsplit import dataclass, field
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

    def payload(self) -> dict[str, Any]:
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
            "last_tick": self.last_tick,
            "execution": "DEMO_ONLY / LOCKED",
            "real_money": False,
            "stakes": {"1m": "0.50", "5m": "2.00"},
            "martingale": False,
        }


HTML = r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dragon Options Monitor</title><style>body{margin:0;background:#07111d;color:#edf5ff;font:14px system-ui;padding:20px}.wrap{max-width:1100px;margin:auto}.top{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}.card{background:#0d1a29;border:1px solid #20364c;border-radius:14px;padding:16px;margin-top:14px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}.v{font-size:25px;font-weight:800;margin-top:5px}.muted{color:#8da3bb;font-size:11px;text-transform:uppercase}.ok{color:#65dfa0}.safe{color:#ffc96b}.signal{padding:12px;background:#101f31;border-radius:10px;margin-top:8px}.mono{font-family:monospace}@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}} </style></head><body><div class="wrap"><div class="top"><div><div class="muted">DRAGON OPTIONS ENGINE</div><h1>Deriv Live Data Monitor</h1><div class="muted">Read-only market data • demo execution locked</div></div><div id="status" class="safe">CONNECTING</div></div><div class="grid"><div class="card"><div class="muted">Symbol</div><div id="symbol" class="v">--</div></div><div class="card"><div class="muted">Live quote</div><div id="quote" class="v">--</div></div><div class="card"><div class="muted">Ticks</div><div id="ticks" class="v">0</div></div><div class="card"><div class="muted">Execution</div><div class="v safe">DEMO ONLY</div></div></div><div class="card"><div class="muted">Completed candles</div><div class="grid"><div><div>1-minute</div><div id="c1" class="v">0</div></div><div><div>5-minute</div><div id="c5" class="v">0</div></div><div><div>1m signals</div><div id="s1" class="v">0</div></div><div><div>5m signals</div><div id="s5" class="v">0</div></div></div></div><div class="card"><div class="muted">Latest signals</div><div id="signals">Waiting for completed candles…</div></div><div class="card"><div class="muted">Safety</div><div class="ok">Real-money execution: LOCKED</div><div>No automatic contract purchase is performed by this monitor.</div><div>Fixed stakes: 1m = $0.50 • 5m = $2.00 • Martingale = OFF</div></div></div><script>async function load(){try{let r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});let d=await r.json();status.textContent=d.status;status.className=d.status==='LIVE_DATA'?'ok':'safe';symbol.textContent=d.symbol;quote.textContent=d.quote||'--';ticks.textContent=d.tick_count;c1.textContent=d.candles['1']||0;c5.textContent=d.candles['5']||0;s1.textContent=d.signals['1']||0;s5.textContent=d.signals['5']||0;let x=[];for(let tf of [1,5]){let s=d.last_signals[String(tf)]||d.last_signals[tf];if(s)x.push('<div class="signal"><b>'+tf+'m '+s.direction+'</b> • stake $'+s.stake+' • confidence '+s.confidence+' • expiry '+s.expiry_seconds+'s<br><span class="muted">'+s.reason+'</span></div>')}signals.innerHTML=x.join('')||'Waiting for qualifying completed candles…'}catch(e){status.textContent='OFFLINE';status.className='safe'}}load();setInterval(load,1000)</script></body></html>'''


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: DashboardState,
    oauth_login,
    oauth_callback,
) -> None:
    try:
        request = await asyncio.wait_for(reader.readline(), 5)
        target = request.decode("utf-8", "ignore").split(" ")[1]
        path = target.split("?")[0]
        query = parse_qs(urlsplit(target).query)
        while await reader.readline() not in (b"\r\n", b"\n", b""):
            pass
        if path == "/health":
            body = json.dumps(state.payload(), separators=(",", ":")).encode()
            content_type = "application/json"
        elif path == "/auth/deriv/login":
            location = oauth_login()
            head = (
                "HTTP/1.1 302 Found\r\n"
                f"Location: {location}\r\n"
                "Cache-Control: no-store\r\n"
                "Content-Length: 0\r\n\r\n"
            ).encode()
            writer.write(head)
            await writer.drain()
            return
        elif path == "/oauth/deriv/callback":
            error = query.get("error", [None])[0]
            if error:
                body = f"OAuth failed: {error}".encode()
                content_type = "text/plain"
            else:
                code = query.get("code", [None])[0]
                state_token = query.get("state", [None])[0]
                if not code or not state_token:
                    body = b"OAuth callback missing code/state."
                    content_type = "text/plain"
                else:
                    await oauth_callback(code, state_token)
                    body = b"Deriv OAuth authentication successful. Return to the dashboard."
                    content_type = "text/plain"
        else:
            body = HTML.encode()
            content_type = "text/html; charset=utf-8"
        head = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: {content_type}\r\n"
            "Cache-Control: no-store\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()

        writer.write(head + body)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def serve_dashboard(state: DashboardState, oauth_login, oauth_callback) -> asyncio.AbstractServer:
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    return await asyncio.start_server(
        lambda r, w: _handle(r, w, state, oauth_login, oauth_callback),
        host,
        port,
        reuse_address=True,
    )
