from __future__ import annotations
import json, os, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ENGINE_URL=os.getenv("ENGINE_URL","https://deriveonlyrender.onrender.com").rstrip("/")

HTML="""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>deriveonly — Live Test Dashboard</title>
<style>
:root{--bg:#f5f7fa;--card:#fff;--line:#e5e9ef;--text:#17212b;--muted:#6b7785;--green:#12805c;--red:#c63c4b;--amber:#a66a00}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px Inter,system-ui,sans-serif}.wrap{max-width:1450px;margin:auto;padding:22px}
.top{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.brand h1{margin:0;font-size:25px}.brand p{margin:4px 0 0;color:var(--muted)}
.badge{padding:8px 12px;border-radius:20px;border:1px solid var(--line);background:#fff;font-weight:800}.live{color:var(--green)}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:15px}.label{font-size:10px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);font-weight:800}.value{font-size:25px;font-weight:850;margin-top:7px}.sub{font-size:12px;color:var(--muted);margin-top:5px}.span3{grid-column:span 3}.span6{grid-column:span 6}
.section{margin-top:14px}.title{font-size:14px;font-weight:850;margin-bottom:9px}.table{width:100%;border-collapse:collapse}.table th,.table td{text-align:left;padding:10px;border-bottom:1px solid var(--line);font-size:12px}.table th{color:var(--muted);font-size:10px;text-transform:uppercase}.wait{color:var(--muted)}.ready{color:var(--green)}.blocked,.loss{color:var(--red)}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.kpi{padding:11px;border:1px solid var(--line);border-radius:10px}.kpi b{display:block;margin-top:5px;font-size:17px}
.signal{display:flex;justify-content:space-between;align-items:center;border:1px solid var(--line);border-radius:12px;padding:13px;margin-top:8px}.dir{font-size:20px;font-weight:900}.put{color:var(--red)}.call{color:var(--green)}
.note{padding:11px 13px;background:#fff9e8;border:1px solid #f1dfab;border-radius:10px;color:#765300;font-size:12px}
@media(max-width:1000px){.grid{grid-template-columns:repeat(3,1fr)}.span6,.span3{grid-column:span 3}}@media(max-width:650px){.wrap{padding:12px}.grid{grid-template-columns:1fr 1fr}.span6,.span3{grid-column:span 2}}
</style></head><body><div class="wrap">
<div class="top"><div class="brand"><h1>deriveonly</h1><p>Live 2-hour paper-test dashboard · 20-instrument scanner</p></div><div id="status" class="badge">CONNECTING</div></div>
<div class="grid">
<div class="card"><div class="label">Account Balance</div><div id="balance" class="value">--</div><div id="balanceSub" class="sub">Live account stream</div></div>
<div class="card"><div class="label">Session P&L</div><div id="pnl" class="value">$0.00</div><div class="sub">Paper-test tracking</div></div>
<div class="card"><div class="label">Drawdown</div><div id="dd" class="value">0%</div><div class="sub">30% hard stop</div></div>
<div class="card"><div class="label">Entries</div><div id="entries" class="value">0 / 5</div><div class="sub">Maximum 5</div></div>
<div class="card"><div class="label">Wins / Losses</div><div id="wl" class="value">0 / 0</div><div class="sub">Paper results</div></div>
<div class="card"><div class="label">Test Clock</div><div id="clock" class="value">00:00:00</div><div class="sub">2-hour window</div></div>
</div>
<div class="section"><div class="title">Risk & Strategy</div><div class="grid">
<div class="card"><div class="kpis"><div class="kpi"><span class="label">Compounding</span><b>5% balance</b></div><div class="kpi"><span class="label">Recovery</span><b>Max 2 attempts</b></div><div class="kpi"><span class="label">3rd Martingale</span><b class="loss">OFF</b></div></div></div>
<div class="card"><div class="kpis"><div class="kpi"><span class="label">Chart</span><b>5 minutes</b></div><div class="kpi"><span class="label">Expiry</span><b>15 minutes</b></div><div class="kpi"><span class="label">Confidence</span><b>≥ 80</b></div></div></div>
<div class="card"><div class="kpis"><div class="kpi"><span class="label">News</span><b class="loss">BLOCKED</b></div><div class="kpi"><span class="label">Extreme volatility</span><b class="loss">BLOCKED</b></div><div class="kpi"><span class="label">Entry grid</span><b>Every 5m</b></div></div></div>
</div></div>
<div class="section"><div class="title">20-Instrument Watchlist</div><div class="card"><table class="table"><thead><tr><th>Instrument</th><th>Setup</th><th>Direction</th><th>Confidence</th><th>Volatility</th><th>Status</th></tr></thead><tbody id="watch"></tbody></table></div></div>
<div class="section"><div class="grid"><div class="card span3"><div class="title">Live Signal</div><div id="signal"><span class="wait">Scanning...</span></div></div>
<div class="card span3"><div class="title">Engine Health</div><div class="kpis"><div class="kpi"><span class="label">Deriv API</span><b id="api">--</b></div><div class="kpi"><span class="label">Ticks</span><b id="ticks">--</b></div><div class="kpi"><span class="label">Symbol</span><b id="symbol">--</b></div></div></div></div></div>
<div class="section"><div class="title">Trade History</div><div class="card"><table class="table"><thead><tr><th>Time</th><th>Instrument</th><th>Direction</th><th>Confidence</th><th>Stake</th><th>Result</th><th>P&L</th></tr></thead><tbody id="history"><tr><td colspan="7" class="wait">Waiting for paper-test entries...</td></tr></tbody></table></div></div>
<div class="section"><div class="note">Read-only dashboard for the 2-hour paper test. It does not place real-money orders.</div></div>
</div>
<script>
const names=["XAU/USD","EUR/USD","GBP/USD","USD/JPY","AUD/USD","USD/CAD","USD/CHF","NZD/USD","EUR/GBP","EUR/JPY","GBP/JPY","AUD/JPY","CAD/JPY","CHF/JPY","NZD/JPY","EUR/AUD","EUR/CAD","GBP/AUD","GBP/CAD","AUD/CAD"];
let history=[],seen={},started=Date.now();
const $=id=>document.getElementById(id);
function esc(v){return String(v??"").replace(/[&<>\"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[m]));}
function watch(d){let s=d.last_signals?.["5"]||d.last_signals?.[5];$("watch").innerHTML=names.map((n,i)=>{let q=i===0?s:null,c=q?.confidence??"--",dir=q?.direction??"—",ok=q&&Number(c)>=80;return "<tr><td><b>"+n+"</b></td><td>"+(q?"Reversal":"Scanning")+"</td><td>"+dir+"</td><td>"+c+"</td><td>"+(i===0?"Live":"—")+"</td><td class='"+(ok?"ready":"wait")+"'>"+(ok?"READY":"WAIT")+"</td></tr>";}).join("");}
function signal(d){let s=d.last_signals?.["5"]||d.last_signals?.[5];if(!s){$("signal").innerHTML="<span class='wait'>No qualifying 5-minute signal.</span>";return}let dir=String(s.direction||"WAIT").toUpperCase();$("signal").innerHTML="<div class='signal'><div><div class='dir "+(dir==="CALL"?"call":"put")+"'>"+esc(dir)+"</div><div class='sub'>"+esc(s.reason||"5m reversal setup")+"</div></div><div><b>Confidence "+esc(s.confidence)+"</b><div class='sub'>Stake "+esc(s.stake??"—")+" · Expiry 15m</div></div></div>";}
function historyAdd(d){let s=d.last_signals?.["5"]||d.last_signals?.[5];if(!s)return;let key=JSON.stringify([s.direction,s.confidence,s.execution?.contract_id,s.execution_result]);if(seen[key])return;seen[key]=1;if(s.execution||s.execution_result){history.unshift({time:new Date().toLocaleTimeString(),asset:s.symbol||d.symbol||"—",direction:s.direction||"—",confidence:s.confidence??"—",stake:s.stake??"—",result:s.execution_result||"OPEN",pnl:"—"});history=history.slice(0,20)}$("history").innerHTML=history.length?history.map(x=>"<tr><td>"+x.time+"</td><td>"+esc(x.asset)+"</td><td>"+esc(x.direction)+"</td><td>"+esc(x.confidence)+"</td><td>"+esc(x.stake)+"</td><td>"+esc(x.result)+"</td><td>"+esc(x.pnl)+"</td></tr>").join(""):"<tr><td colspan='7' class='wait'>Waiting for paper-test entries...</td></tr>";$("entries").textContent=history.length+" / 5";}
async function load(){try{let r=await fetch("/api/health?ts="+Date.now(),{cache:"no-store"}),d=await r.json();$("status").textContent=d.status||"LIVE";$("status").className="badge live";$("balance").textContent=d.balance!=null?d.balance+" USD":"--";$("balanceSub").textContent=d.balance_updated_at?"Updated "+new Date(d.balance_updated_at*1000).toLocaleTimeString():"No account balance";$("api").textContent=d.authenticated?"CONNECTED":"LIVE DATA";$("ticks").textContent=d.tick_count??0;$("symbol").textContent=d.symbol||"--";watch(d);signal(d);historyAdd(d);}catch(e){$("status").textContent="ENGINE OFFLINE";$("status").className="badge";$("api").textContent="OFFLINE";}}
function timer(){let s=Math.min(7200,Math.floor((Date.now()-started)/1000));$("clock").textContent=[Math.floor(s/3600),Math.floor(s%3600/60),s%60].map(x=>String(x).padStart(2,"0")).join(":");}
setInterval(load,1000);setInterval(timer,1000);load();timer();
</script></body></html>"""

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api/health"):
            try:
                req=urllib.request.Request(ENGINE_URL+"/health",headers={"User-Agent":"deriveonly-test-dashboard/1.0"})
                with urllib.request.urlopen(req,timeout=5) as r: body=r.read()
                self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
            except Exception as exc:
                self.send_response(502);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(json.dumps({"status":"ENGINE_OFFLINE","error":str(exc)}).encode())
            return
        if self.path=="/health":
            self.send_response(200);self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(b'{"status":"OK"}');return
        body=HTML.encode();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(body)
    def log_message(self,fmt,*args):pass

if __name__=="__main__":
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
