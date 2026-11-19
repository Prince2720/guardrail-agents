from app.api.theme import CSS as THEME, LOGO

_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Live dashboard | Guardrail Agents</title>
<style>
/*THEME*/
.titlebar{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end;justify-content:space-between;padding:34px 0 18px}
.titlebar h1{font-size:clamp(1.9rem,4vw,2.7rem);letter-spacing:-.02em}
.titlebar p{margin-top:6px}
.status{display:flex;flex-wrap:wrap;gap:8px}
.ledger{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line2);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.k{background:var(--surface);padding:16px 18px}
@media (max-width:760px){.ledger{grid-template-columns:repeat(2,1fr)}.k b{font-size:25px}}
.k b{display:block;font-family:var(--display);font-weight:600;font-size:30px;letter-spacing:-.02em;line-height:1.1}
.k span{display:block;margin-top:4px;font-size:13.5px;color:var(--ink2)}
.k.bad b{color:var(--danger)}.k.warn b{color:var(--warn)}.k.good b{color:var(--safe)}
.two{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));margin-top:14px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin-top:14px}
.two .panel{margin-top:0}
.panel h2{font-size:19px;margin-bottom:12px}
.panel h3{font-size:16px;margin:18px 0 8px}
.gate{display:grid;grid-template-columns:78px 1fr 34px;gap:10px;align-items:center;margin:9px 0}
.gate label{font-family:var(--display);font-weight:600;color:var(--steel);font-size:16px}
.gate i{display:block;height:12px;border-radius:2px;background:var(--steel);min-width:2px}
.gate em{font-style:normal;text-align:right;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-size:14.5px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line2);vertical-align:top}
th{font-weight:600;color:var(--ink2);font-size:13.5px}
td.num{font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:13px;border:1px solid currentColor;white-space:nowrap}
.pill.answered{color:var(--safe)}.pill.blocked{color:var(--danger)}.pill.approval_pending{color:var(--warn)}
.admin>summary{cursor:pointer;font-family:var(--display);font-weight:600;font-size:19px;list-style:none}
.admin>summary::-webkit-details-marker{display:none}
.admin>summary::after{content:"+";float:right;color:var(--ink2);font-weight:400}
.admin[open]>summary::after{content:"\2212"}
.adminbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:14px 0 4px}
input{padding:9px 11px;border:1px solid var(--line);border-radius:8px;background:var(--paper);min-width:240px;max-width:100%}
code{font-family:var(--mono);font-size:12.5px;overflow-wrap:anywhere}
.btn.small{padding:5px 11px;font-size:13.5px}
.foot{margin:34px 0 40px;font-size:14px;color:var(--ink2)}
</style></head>
<body>
<header class="top"><div class="wrap">
  <a class="brand" href="/">__LOGO__Guardrail Agents</a>
  <nav aria-label="Main"><a href="/">Demo</a><a href="/dashboard" aria-current="page">Dashboard</a></nav>
</div></header>

<main class="wrap">
  <div class="titlebar">
    <div><h1>Live dashboard</h1><p class="muted">Every request, block and approval, as it happens.</p></div>
    <div class="status"><span id="fw" class="chip">Firewall ...</span><span id="chain" class="chip">Audit log ...</span></div>
  </div>

  <section class="ledger" id="kpis" aria-label="Key numbers"></section>

  <div class="two">
    <section class="panel"><h2>Where requests were stopped</h2><div id="layers"></div></section>
    <section class="panel"><h2>Why they were stopped</h2><div class="scroll"><table id="reasons"></table></div></section>
  </div>

  <section class="panel"><h2>Recent requests</h2><div class="scroll"><table id="recent"></table></div></section>

  <details class="panel admin">
    <summary>Admin: approvals and quarantine review</summary>
    <div class="adminbar"><label class="sr" for="tok">Admin token</label><input id="tok" type="password" placeholder="Admin token" autocomplete="off"><button class="btn" id="load">Load</button><small id="amsg" class="muted"></small></div>
    <h3>Pending approvals</h3><div class="scroll"><table id="appr"></table></div>
    <h3>Quarantined chunks</h3><div class="scroll"><table id="quar"></table></div>
  </details>
  <p class="foot">Numbers update every few seconds. This page shows counts and reasons, never message content. Data: <code>/metrics</code></p>
</main>

<script>
const $=s=>document.querySelector(s);
const esc=t=>String(t==null?"":t).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const time=ts=>new Date(ts*1000).toLocaleTimeString();
const LAYERS=[["ingress","Ingress"],["context","Context"],["tools","Tools"],["egress","Egress"]];
async function metrics(){
  const m=await (await fetch("/metrics")).json();
  const on=String(m.firewall.enabled).toLowerCase()!=="false";
  $("#fw").textContent="Firewall "+(on?"on ("+m.firewall.layers+")":"off");$("#fw").className="chip "+(on?"ok":"bad");
  $("#chain").textContent=m.audit_chain.ok?"Audit log intact ("+m.audit_chain.events+" events)":"Audit log TAMPERED at #"+m.audit_chain.first_bad_id;
  $("#chain").className="chip "+(m.audit_chain.ok?"ok":"bad");
  const pct=m.total?Math.round(100*m.blocked/m.total):0;
  const k=[["Requests",m.total,""],["Answered",m.answered,"good"],["Blocked",m.blocked+" ("+pct+"%)",m.blocked?"bad":""],["Awaiting approval",m.approval_pending,m.approval_pending?"warn":""],
    ["Quarantined chunks",m.quarantined_chunks,m.quarantined_chunks?"warn":""],["Sent with firewall off",m.firewall_off_requests||0,""],
    ["Private values removed (in / out)",m.redactions.input+" / "+m.redactions.output,""],["Latency mean / p95",m.latency_ms.mean+" / "+m.latency_ms.p95+" ms",""]];
  $("#kpis").innerHTML=k.map(x=>'<div class="k '+x[2]+'"><b>'+esc(x[1])+'</b><span>'+esc(x[0])+'</span></div>').join("");
  const mx=Math.max(1,...Object.values(m.blocked_by_layer));
  $("#layers").innerHTML=LAYERS.map(([k,n])=>{const v=m.blocked_by_layer[k]||0;return'<div class="gate"><label>'+n+'</label><i style="width:'+Math.max(2,Math.round(100*v/mx))+'%"></i><em>'+v+'</em></div>';}).join("");
  $("#reasons").innerHTML="<tr><th>Reason</th><th>Count</th></tr>"+(m.top_reasons.map(r=>"<tr><td>"+esc(r.reason)+'</td><td class="num">'+r.count+"</td></tr>").join("")||'<tr><td colspan="2" class="muted">Nothing blocked yet</td></tr>');
  $("#recent").innerHTML="<tr><th>Time</th><th>User</th><th>Outcome</th><th>Gate</th><th>Reason</th><th>ms</th></tr>"+
    (m.recent.map(r=>"<tr><td>"+time(r.ts)+"</td><td>"+esc(r.user)+'</td><td><span class="pill '+esc(r.outcome)+'">'+esc(String(r.outcome).replace("_"," "))+"</span></td><td>"+esc(r.layer||"")+"</td><td>"+esc(r.reason||"")+'</td><td class="num">'+esc(r.ms)+"</td></tr>").join("")||'<tr><td colspan="6" class="muted">No requests yet. Run an attack on the demo page.</td></tr>');
}
const H=()=>({"X-Admin-Token":$("#tok").value});
async function admin(){
  $("#amsg").textContent="";
  const a=await fetch("/approvals?status=pending",{headers:H()});
  if(!a.ok){$("#amsg").textContent=a.status===401?"That token was not accepted.":a.status===503?"Admin access is not configured on this server.":"Request failed ("+a.status+").";return;}
  const ap=await a.json();
  $("#appr").innerHTML="<tr><th>#</th><th>User</th><th>Tool</th><th>Arguments</th><th></th></tr>"+(ap.map(x=>"<tr><td>"+x.id+"</td><td>"+esc(x.user_id)+"</td><td>"+esc(x.tool)+"</td><td><code>"+esc(JSON.stringify(x.args))+'</code></td><td><button class="btn small" data-a="approve" data-id="'+x.id+'">Approve</button> <button class="btn small" data-a="deny" data-id="'+x.id+'">Deny</button></td></tr>').join("")||'<tr><td colspan="5" class="muted">Nothing pending</td></tr>');
  const q=await (await fetch("/quarantine",{headers:H()})).json();
  $("#quar").innerHTML="<tr><th>Source</th><th>Reason</th><th>Snippet</th><th></th></tr>"+(q.map(x=>"<tr><td>"+esc(x.source)+"</td><td>"+esc(x.reason)+"</td><td><code>"+esc((x.snippet||"").slice(0,120))+"</code></td><td>"+(x.released?'<span class="muted">released</span>':'<button class="btn small" data-q="'+esc(x.hash)+'">Release</button>')+"</td></tr>").join("")||'<tr><td colspan="4" class="muted">Nothing quarantined</td></tr>');
}
document.addEventListener("click",async e=>{
  const t=e.target;
  if(t.id==="load")return admin();
  if(t.dataset.a){await fetch("/approvals/"+t.dataset.id+"/"+t.dataset.a,{method:"POST",headers:H()});admin();metrics();}
  if(t.dataset.q){await fetch("/quarantine/"+t.dataset.q+"/release",{method:"POST",headers:H()});admin();}
});
metrics();setInterval(metrics,4000);
</script></body></html>"""

HTML = _PAGE.replace("/*THEME*/", THEME).replace("__LOGO__", LOGO)
