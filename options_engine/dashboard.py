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
    candle_data: dict[int, list[dict[str, Any]]] = field(default_factory=lambda: {1: [], 5: []})

    def payload(self) -> dict[str, Any]:
        authenticated = self.status in {"AUTHENTICATED_READ_ONLY", "LIVE_ACCOUNT_CONNECTED"}
        if self.account_mode == "real" and self.live_execution_enabled:
            execution = "REAL_ENABLED / AUTHENTICATED" if authenticated else "REAL_ENABLED / AUTH_REQUIRED"
        elif authenticated:
            execution = "DEMO / AUTHENTICATED"
        else:
            execution = "AUTH_REQUIRED"
        return {
            "status": self.status, "symbol": self.symbol, "connected_at": self.connected_at,
            "updated_at": self.updated_at, "last_tick_at": self.last_tick_at,
            "quote": self.quote, "tick_count": self.tick_count, "candles": self.candles,
            "signals": self.signals, "last_signals": self.last_signals, "execution": execution,
            "real_money": self.account_mode == "real" and self.live_execution_enabled,
            "authenticated": authenticated,
            "account_id": f"...{self.account_id[-4:]}" if self.account_id else None,
            "account_mode": self.account_mode, "live_execution_enabled": self.live_execution_enabled,
            "balance": self.balance, "balance_updated_at": self.balance_updated_at,
            "balance_error": self.balance_error, "auth_error": self.auth_error,
            "candle_data": self.candle_data,
            "stakes": {"30s": "0.25", "1m": "0.25", "5m": "2.00"}, "martingale": False,
        }


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>deriveonly | Deriv Options</title>
<style>
:root{--bg:#07101a;--panel:#0c1825;--panel2:#101f2e;--line:#1d3449;--text:#eef6ff;--muted:#7f97ae;--green:#35e59a;--amber:#ffc857;--red:#ff6878;--blue:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 85% -10%,#12314b 0,transparent 35%),var(--bg);color:var(--text);font:14px Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}
.wrap{max-width:1320px;margin:auto;padding:20px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:18px}
.brand{display:flex;align-items:center;gap:12px}.logo{width:42px;height:42px;border-radius:12px;background:#10283b;border:1px solid #28516e;display:grid;place-items:center;font-weight:900;color:var(--green)}
h1{font-size:23px;margin:0}.sub{color:var(--muted);font-size:12px;margin-top:3px}
.pill{border:1px solid var(--line);background:#0c1a27;border-radius:999px;padding:9px 13px;font-weight:800;font-size:12px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:7px;background:var(--amber)}.online .dot{background:var(--green)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:linear-gradient(180deg,#0d1a28,#0a1521);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 8px 30px #0003}.label{color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase}.value{font-size:27px;font-weight:850;margin-top:8px;letter-spacing:-.02em}.small{font-size:12px;color:var(--muted);margin-top:5px}.green{color:var(--green)}.amber{color:var(--amber)}.red{color:var(--red)}
.span2{grid-column:span 2}.span4{grid-column:span 4}.section{margin-top:14px}.sectionTitle{display:flex;justify-content:space-between;align-items:center;margin:0 0 10px;font-size:13px;font-weight:800}
.market{display:grid;grid-template-columns:1.3fr .7fr;gap:12px}.quote{font-size:46px;font-weight:900;margin:7px 0}.chartWrap{height:330px;margin-top:12px;background:#08131e;border:1px solid #193249;border-radius:12px;overflow:hidden}.chartWrap canvas{width:100%;height:100%;display:block}
.rows{display:grid;gap:9px}.row{display:flex;justify-content:space-between;gap:12px;padding:11px 0;border-bottom:1px solid #183047}.row:last-child{border-bottom:0}.row b{font-weight:750}.status{font-weight:850}
.signal{background:var(--panel2);border:1px solid #234058;border-radius:13px;padding:14px}.signalHead{display:flex;justify-content:space-between;align-items:center}.direction{font-size:20px;font-weight:900}.meta{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.tag{background:#0b1723;border:1px solid #20384e;border-radius:8px;padding:6px 8px;color:#b8c9d9;font-size:11px}.reason{color:var(--muted);font-size:12px;margin-top:10px;line-height:1.45}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}a.btn{display:inline-block;text-decoration:none;color:var(--text);border:1px solid #2a4c64;background:#102438;border-radius:10px;padding:10px 13px;font-weight:800;font-size:12px}a.btn.primary{border-color:#276d57;background:#0d3027;color:var(--green)}
.health{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.healthItem{padding:12px;background:#0a1521;border:1px solid #193249;border-radius:11px}.healthItem b{display:block;margin-top:5px}
footer{color:#61798e;text-align:center;font-size:10px;padding:18px 0}
@media(max-width:900px){.grid{grid-template-columns:repeat(2,1fr)}.span4{grid-column:span 2}.market{grid-template-columns:1fr}.health{grid-template-columns:repeat(2,1fr)}}
@media(max-width:560px){.wrap{padding:13px}.grid{grid-template-columns:1fr 1fr;gap:8px}.card{padding:13px;border-radius:13px}.value{font-size:22px}.quote{font-size:36px}.health{grid-template-columns:1fr 1fr}}
</style></head>
<body><div class="wrap">
<header class="top">
<div class="brand"><div class="logo">D</div><div><h1>deriveonly</h1><div class="sub">Live Deriv Options Control Center</div></div></div>
<div id="topStatus" class="pill"><span class="dot"></span>CONNECTING</div>
</header>

<div class="grid">
<div class="card"><div class="label">Account Balance</div><div id="balance" class="value">--</div><div id="balanceMeta" class="small">Waiting for live account data</div></div>
<div class="card"><div class="label">Execution</div><div id="execution" class="value amber">--</div><div id="execMeta" class="small">Authentication status</div></div>
<div class="card"><div class="label">Symbol</div><div id="symbol" class="value">--</div><div class="small">Live market stream</div></div>
<div class="card"><div class="label">Ticks</div><div id="ticks" class="value">0</div><div id="tickAge" class="small">Waiting for tick</div></div>
</div>

<div class="section market">
<div class="card"><div class="label">Gold XAU/USD</div><div id="quote" class="quote">--</div><div class="small">Live regular-options underlying</div><div class="chartWrap"><canvas id="chart"></canvas></div><div class="small">1-minute candlesticks · live</div></div>
<div class="card"><div class="label">Trading Configuration</div><div class="rows">
<div class="row"><span>Entry duration</span><b>30 seconds</b></div>
<div class="row"><span>30s stake</span><b>$0.25</b></div>
<div class="row"><span>1m stake</span><b>$0.25</b></div>
<div class="row"><span>5m stake</span><b>$2.00</b></div>
<div class="row"><span>Martingale</span><b class="green">OFF</b></div>
</div></div>
</div>

<div class="section"><div class="sectionTitle"><span>Strategy & Signals</span><span id="signalCount" class="small">0 signals</span></div>
<div class="grid">
<div class="card span2"><div class="label">1 Minute Engine</div><div id="sig1" class="signal"><div class="small">Waiting for qualifying candle...</div></div></div>
<div class="card span2"><div class="label">5 Minute Engine</div><div id="sig5" class="signal"><div class="small">Waiting for qualifying candle...</div></div></div>
</div></div>

<div class="section"><div class="sectionTitle"><span>Engine Activity</span></div>
<div class="grid">
<div class="card"><div class="label">1m Candles</div><div id="c1" class="value">0</div></div>
<div class="card"><div class="label">5m Candles</div><div id="c5" class="value">0</div></div>
<div class="card"><div class="label">1m Signals</div><div id="s1" class="value">0</div></div>
<div class="card"><div class="label">5m Signals</div><div id="s5" class="value">0</div></div>
</div></div>

<div class="section"><div class="sectionTitle"><span>System Health</span><span id="refresh" class="small">Updating every second</span></div>
<div class="card"><div class="health">
<div class="healthItem"><div class="label">Deriv API</div><b id="hAuth">--</b></div>
<div class="healthItem"><div class="label">Live Tick Stream</div><b id="hTicks">--</b></div>
<div class="healthItem"><div class="label">Balance</div><b id="hBalance">--</b></div>
<div class="healthItem"><div class="label">Last Update</div><b id="hUpdate">--</b></div>
</div><div class="actions"><a class="btn primary" href="/auth/deriv/login">CONNECT DERIV ACCOUNT</a><a class="btn" href="/account/balance">ACCOUNT BALANCE API</a><a class="btn" href="/health">ENGINE HEALTH API</a></div></div></div>

<footer>deriveonly · live status is read from the running Deriv engine · no credentials are displayed</footer>
</div>
<script>
const bars=[];
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function setText(id,v){const e=document.getElementById(id);if(e)e.textContent=v;}
function signalHtml(s){
 if(!s||s.error)return '<div class="small">'+esc(s?.error||'Waiting for qualifying candle...')+'</div>';
 const d=String(s.direction||'SIGNAL').toUpperCase(), cls=d==='CALL'?'green':d==='PUT'?'red':'amber';
 return '<div class="signalHead"><span class="direction '+cls+'">'+esc(d)+'</span><span class="small">'+esc(s.expiry_seconds||30)+'s expiry</span></div>'+
 '<div class="meta"><span class="tag">Stake $'+esc(s.stake)+'</span><span class="tag">Confidence '+esc(s.confidence)+'</span></div>'+
 '<div class="reason">'+esc(s.reason||'Signal generated')+'</div>'+
 (s.execution?'<div class="small green" style="margin-top:9px">Execution response received</div>':'')+
 (s.execution_error?'<div class="small red" style="margin-top:9px">Execution error: '+esc(s.execution_error)+'</div>':'');
}
function drawChart(cs){
 const canvas=document.getElementById('chart'); if(!canvas)return;
 const rect=canvas.getBoundingClientRect(), dpr=window.devicePixelRatio||1;
 canvas.width=Math.max(1,rect.width*dpr); canvas.height=Math.max(1,rect.height*dpr);
 const ctx=canvas.getContext('2d'); ctx.scale(dpr,dpr);
 const W=rect.width,H=rect.height,pad={l:8,r:8,t:12,b:20};
 ctx.clearRect(0,0,W,H);
 if(!cs.length){ctx.fillStyle='#7f97ae';ctx.font='12px system-ui';ctx.fillText('Waiting for Gold candles...',16,28);return;}
 const data=cs.slice(-60), lo=Math.min(...data.map(x=>x.low)), hi=Math.max(...data.map(x=>x.high)), range=Math.max(hi-lo,1e-9);
 const step=(W-pad.l-pad.r)/data.length, y=v=>pad.t+(hi-v)/range*(H-pad.t-pad.b);
 ctx.strokeStyle='#193249';ctx.lineWidth=1;
 for(let i=0;i<5;i++){const gy=pad.t+i*(H-pad.t-pad.b)/4;ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(W-pad.r,gy);ctx.stroke();}
 data.forEach((x,i)=>{const px=pad.l+i*step+step/2, up=x.close>=x.open;ctx.strokeStyle=up?'#35e59a':'#ff6878';ctx.fillStyle=ctx.strokeStyle;ctx.beginPath();ctx.moveTo(px,y(x.high));ctx.lineTo(px,y(x.low));ctx.stroke();const top=y(Math.max(x.open,x.close)),bot=y(Math.min(x.open,x.close));ctx.fillRect(px-step*.31,top,Math.max(2,step*.62),Math.max(1,bot-top));});
 const last=data[data.length-1];ctx.fillStyle='#eef6ff';ctx.font='11px system-ui';ctx.fillText('Close '+Number(last.close).toFixed(2),W-95,12);
}
async function load(){
 try{
  const r=await fetch('/health?ts='+Date.now(),{cache:'no-store'});const d=await r.json();
  const live=['LIVE_DATA','LIVE_ACCOUNT_CONNECTED','AUTHENTICATED_READ_ONLY'].includes(d.status);
  const real=!!(d.real_money&&d.authenticated);
  const top=document.getElementById('topStatus');top.className='pill '+(live?'online':'');top.innerHTML='<span class="dot"></span>'+esc(d.status);
  setText('balance',d.balance!=null?d.balance+' USD':'--');
  setText('balanceMeta',d.balance_updated_at?'Live · '+new Date(d.balance_updated_at*1000).toLocaleTimeString():(d.balance_error||'Waiting for live account data'));
  setText('execution',d.execution||'--');document.getElementById('execution').className='value '+(real?'green':'amber');
  setText('execMeta',real?'Real execution enabled':'Authentication / execution status');
  setText('symbol',d.symbol||'--');setText('quote',d.quote||'--');setText('ticks',d.tick_count||0);
  const age=d.last_tick_at?Math.max(0,Date.now()/1000-d.last_tick_at):null;setText('tickAge',age!=null?'Last tick '+age.toFixed(1)+'s ago':'Waiting for tick');
  setText('c1',d.candles?.['1']||0);setText('c5',d.candles?.['5']||0);setText('s1',d.signals?.['1']||0);setText('s5',d.signals?.['5']||0);
  const total=(d.signals?.['1']||0)+(d.signals?.['5']||0);setText('signalCount',total+' signals');
  setText('hAuth',d.authenticated?'CONNECTED':'NOT CONNECTED');document.getElementById('hAuth').className=d.authenticated?'green':'amber';
  setText('hTicks',age!=null&&age<10?'HEALTHY':'WAITING');document.getElementById('hTicks').className=age!=null&&age<10?'green':'amber';
  setText('hBalance',d.balance!=null?'LIVE':'UNAVAILABLE');document.getElementById('hBalance').className=d.balance!=null?'green':'amber';
  setText('hUpdate',d.updated_at?new Date(d.updated_at*1000).toLocaleTimeString():'--');
  setText('refresh','Updated '+new Date().toLocaleTimeString());
  setText('sig1','');document.getElementById('sig1').innerHTML=signalHtml(d.last_signals?.['1']||d.last_signals?.[1]);
  document.getElementById('sig5').innerHTML=signalHtml(d.last_signals?.['5']||d.last_signals?.[5]);
  drawChart(d.candle_data?.['1']||d.candle_data?.[1]||[]);
 }catch(e){const top=document.getElementById('topStatus');top.className='pill';top.innerHTML='<span class="dot"></span>OFFLINE';}
}
load();setInterval(load,1000);
</script></body></html>"""


def _response(status: str, body: bytes, content_type: str = "text/plain") -> bytes:
    return (
        f"HTTP/1.1 {status}\r\n"
        f"Content-Type: {content_type}\r\n"
        "Cache-Control: no-store\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode() + body


async def _handle(reader, writer, state, oauth_login, oauth_callback, oauth_status) -> None:
    try:
        request = await asyncio.wait_for(reader.readline(), 5)
        parts = request.decode("utf-8", "ignore").split(" ")
        if len(parts) < 2:
            return
        target = parts[1]
        parsed = urlsplit(target)
        path, query = parsed.path, parse_qs(parsed.query)
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        if path == "/account/balance":
            p = state.payload()
            body = json.dumps({
                "authenticated": p["authenticated"],
                "account_id": p["account_id"],
                "account_mode": p["account_mode"],
                "balance": p["balance"] if p["authenticated"] else None,
                "updated_at": p["balance_updated_at"] if p["authenticated"] else None,
                "error": p["balance_error"] if p["authenticated"] else "Deriv OAuth authentication required",
            }, separators=(",", ":")).encode()
            writer.write(_response("200 OK", body, "application/json"))
        elif path == "/health":
            writer.write(_response("200 OK", json.dumps(state.payload(), separators=(",", ":")).encode(), "application/json"))
        elif path in {"/auth/deriv/login", "/oauth/deriv/start"}:
            location = oauth_login(query.get("return_to", [None])[0])
            writer.write(_response("302 Found", b"", "text/plain").replace(b"Content-Length: 0", f"Location: {location}\r\nContent-Length: 0".encode(), 1))
        elif path == "/oauth/deriv/status":
            writer.write(_response("200 OK", json.dumps(oauth_status(), separators=(",", ":")).encode(), "application/json"))
        elif path == "/oauth/deriv/callback":
            error = query.get("error", [None])[0]
            if error:
                state.auth_error = f"{error}: {query.get('error_description', [''])[0]}"
                body = f"OAuth failed: {html.escape(state.auth_error)}".encode()
            else:
                code, token = query.get("code", [None])[0], query.get("state", [None])[0]
                if not code or not token:
                    state.auth_error = "OAuth callback missing code/state"
                    body = state.auth_error.encode()
                else:
                    try:
                        await oauth_callback(code, token)
                        state.auth_error = None
                        owner = getattr(oauth_callback, "__self__", None)
                        destination = getattr(owner, "oauth_return_url", None)
                        if destination:
                            sep = "&" if "?" in destination else "?"
                            writer.write(_response("302 Found", b"", "text/plain").replace(b"Content-Length: 0", f"Location: {destination}{sep}status=success\r\nContent-Length: 0".encode(), 1))
                            await writer.drain()
                            return
                        body = b"Deriv OAuth authentication successful. Return to the dashboard."
                    except Exception as exc:
                        state.auth_error = f"{type(exc).__name__}: {exc}"
                        body = f"Deriv OAuth authentication failed: {html.escape(state.auth_error)}".encode()
            writer.write(_response("200 OK", body, "text/html; charset=utf-8"))
        else:
            writer.write(_response("200 OK", HTML.encode(), "text/html; charset=utf-8"))
        await writer.drain()
    except Exception as exc:
        print(f"DASHBOARD_REQUEST_ERROR type={type(exc).__name__} error={exc}", flush=True)
    finally:
        writer.close()
        await writer.wait_closed()


async def serve_dashboard(state, oauth_login, oauth_callback, oauth_status):
    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "10000"))
    return await asyncio.start_server(
        lambda r, w: _handle(r, w, state, oauth_login, oauth_callback, oauth_status),
        host, port, reuse_address=True,
    )