const $ = (id) => document.getElementById(id);
const state = { presets: [], lastResult: null, offline: false };
const fallbackPresets = [
  {id:"mpesa",name:"Add M-Pesa Idempotency Key & Index",description:"Add a nullable request key and index.",currentDdl:"CREATE TABLE payments (id INTEGER PRIMARY KEY, checkout_request_id TEXT NOT NULL, amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING');",targetDdl:"CREATE TABLE payments (id INTEGER PRIMARY KEY, checkout_request_id TEXT NOT NULL, idempotency_key TEXT, amount_cents INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING'); CREATE INDEX idx_payments_idempotency_key ON payments(idempotency_key);"},
  {id:"drop",name:"Drop Legacy Ledger Column (Breaking)",description:"Remove a legacy field.",currentDdl:"CREATE TABLE ledger_entries (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL, legacy_reference TEXT, memo TEXT);",targetDdl:"CREATE TABLE ledger_entries (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL, memo TEXT);"},
  {id:"profile",name:"Split Customer Profile & Add NOT NULL",description:"Add a profile table and required tier.",currentDdl:"CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT NOT NULL, full_name TEXT);",targetDdl:"CREATE TABLE customers (id INTEGER PRIMARY KEY, email TEXT NOT NULL, full_name TEXT, tier TEXT NOT NULL); CREATE TABLE customer_profiles (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, display_name TEXT);"}
];
function toast(message){const el=$("toast");el.textContent=message;el.classList.add("show");clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove("show"),2600);}
function setEditors(current,target){$("currentDdl").value=current;$("targetDdl").value=target;updateCounts();}
function updateCounts(){for(const [id,out] of [["currentDdl","currentCount"],["targetDdl","targetCount"]])$(out).textContent=$ (id).value.length+" CHARACTERS";}
function esc(value){return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function riskClass(risk){return risk==="SAFE_ADDITIVE"?"safe":risk==="CAUTION_LOCK_RISK"?"caution":risk==="BREAKING_DESTRUCTIVE"?"breaking":"neutral";}
function render(result){
 state.lastResult=result;
 const badge=$("riskBadge");badge.textContent=result.risk;badge.className="risk-badge "+riskClass(result.risk);
 $("dryBadge").textContent=result.dryRun?.passed?"SQLITE DRY-RUN PASSED":"DRY-RUN FAILED";$("dryBadge").className="dry-badge "+(result.dryRun?.passed?"pass":"fail");
 $("summaryStats").innerHTML=`<div><strong>${result.tables?.added?.length||0}</strong><span>TABLES ADDED</span></div><div><strong>${result.tables?.removed?.length||0}</strong><span>TABLES REMOVED</span></div><div><strong>${result.changes?.length||0}</strong><span>CHANGE EVENTS</span></div>`;
 const list=$("changeList");
 list.innerHTML=result.changes?.length?result.changes.map(c=>{const symbol=c.kind.includes("added")?"+":c.kind.includes("removed")?"−":"~";return `<div class="change-item"><span class="change-symbol">${symbol}</span><div><strong>${esc(c.table)} · ${esc(c.column||c.index||c.columns?.join(", ")||c.kind.replaceAll("_"," "))}</strong><p>${esc(c.message)}</p></div><span class="severity ${riskClass(c.severity)}">${esc(c.severity)}</span></div>`;}).join(""):'<div class="empty-state">No structural changes detected.</div>';
 $("forwardSql").textContent=result.forwardSql||"-- No forward migration."; $("rollbackSql").textContent=result.rollbackSql||"-- No rollback required.";
 const advice=[];
 if(result.risk==="BREAKING_DESTRUCTIVE")advice.push("Breaking change detected. Confirm every consumer has stopped reading removed or modified columns before contraction.","Prefer an expand → backfill → deploy → contract sequence. Keep a tested backup before removing data.");
 if(result.risk==="CAUTION_LOCK_RISK")advice.push("Potential lock or table-scan risk detected. Estimate table size and write volume before rollout.","For required fields, add nullable first, backfill in batches, then enforce NOT NULL in a later migration.");
 if(result.risk==="SAFE_ADDITIVE")advice.push("Changes appear additive. Verify application compatibility and deploy schema before code that depends on new fields.","Index creation can still be expensive on large production tables; use engine-specific online index features where available.");
 if(!result.dryRun?.passed)advice.push("The generated forward SQL did not pass the SQLite dry-run. Do not execute it; inspect the SQL and error below.");
 $("advice").innerHTML='<div class="advice-icon">⌁</div><h3>Recommended rollout checks</h3><ul>'+advice.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul><p><b>Verifier:</b> '+esc(result.dryRun?.message||"No dry-run result")+'</p>';
}
async function loadPresets(){
 try{const response=await fetch("/api/presets");if(!response.ok)throw Error("API unavailable");const data=await response.json();state.presets=data.presets||fallbackPresets;$("engineStatus").textContent="SchemaDiff Engine: Active • SQLite Dry-Run Verifier Ready";}
 catch{state.offline=true;state.presets=fallbackPresets;$("engineStatus").textContent="Demo Mode: Presets loaded • Python API unavailable";}
 $("presetSelect").innerHTML='<option value="">Choose a migration preset…</option>'+state.presets.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.name)+'</option>').join("");
}
function applyPreset(id){const p=state.presets.find(x=>x.id===id);if(!p)return;setEditors(p.currentDdl,p.targetDdl);toast("Loaded: "+p.name);}
async function compute(){
 const currentDdl=$("currentDdl").value,targetDdl=$("targetDdl").value;
 if(!currentDdl.trim()||!targetDdl.trim()){toast("Enter both current and target DDL first.");return;}
 $("computeBtn").disabled=true;$("computeBtn").textContent="Analyzing…";$("runStatus").textContent="Inspecting SQLite schema catalog…";
 try{
  const response=await fetch("/api/diff",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({currentDdl,targetDdl})});
  const data=await response.json();if(!response.ok)throw Error(data.error||"Diff request failed");render(data);$("runStatus").textContent="Analysis complete · "+new Date().toLocaleTimeString();
 }catch(error){
  if(!state.offline)toast(error.message);
  const result=offlineDiff(currentDdl,targetDdl);render(result);$("runStatus").textContent="Offline heuristic preview · server verification unavailable";
  toast("Showing browser-only preview; SQLite dry-run requires the API.");
 }finally{$("computeBtn").disabled=false;$("computeBtn").innerHTML='<span>↗</span> Compute Diff &amp; Dry-Run';}
}
function offlineDiff(a,b){
 const tables=s=>[...s.matchAll(/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`]?([\w]+)/gi)].map(m=>m[1]);
 const old=tables(a),next=tables(b),added=next.filter(x=>!old.includes(x)),removed=old.filter(x=>!next.includes(x));
 const changes=[...added.map(table=>({table,kind:"table_added",severity:"SAFE_ADDITIVE",message:"Table appears in target DDL (offline text preview only)"})),...removed.map(table=>({table,kind:"table_removed",severity:"BREAKING_DESTRUCTIVE",message:"Table appears removed (offline text preview only)"}))];
 const drop=/DROP\s+(TABLE|COLUMN)/i.test(a+"\n"+b),risk=drop||removed.length?"BREAKING_DESTRUCTIVE":changes.length?"SAFE_ADDITIVE":"CAUTION_LOCK_RISK";
 return {risk,changes,tables:{added,removed},forwardSql:"-- Offline preview only. Reconnect to the Python API for engine-generated SQL.\n-- Target DDL:\n"+b,rollbackSql:"-- Offline preview cannot safely generate rollback SQL.\n-- Preserve a verified backup before applying changes.",dryRun:{passed:false,message:"Not verified: no SQLite engine is available in browser-only mode."}};
}
$("computeBtn").addEventListener("click",compute);
$("presetSelect").addEventListener("change",e=>applyPreset(e.target.value));
$("presetBtn").addEventListener("click",()=>{const p=state.presets[0];if(p)applyPreset(p.id);else toast("Presets are still loading.");});
$("dropBtn").addEventListener("click",()=>{const p=state.presets.find(x=>x.id==="drop-legacy-ledger"||x.id==="drop");if(p)applyPreset(p.id);else setEditors(fallbackPresets[1].currentDdl,fallbackPresets[1].targetDdl);toast("Destructive-drop scenario loaded. Review before analysis.");});
document.querySelectorAll("[data-clear]").forEach(btn=>btn.addEventListener("click",()=>{$(btn.dataset.clear).value="";updateCounts();}));
document.querySelectorAll("[data-copy]").forEach(btn=>btn.addEventListener("click",async()=>{const value=$(btn.dataset.copy).textContent;try{await navigator.clipboard.writeText(value);toast("SQL copied to clipboard.");}catch{toast("Clipboard permission unavailable.");}}));
$("currentDdl").addEventListener("input",updateCounts);$("targetDdl").addEventListener("input",updateCounts);
loadPresets();
