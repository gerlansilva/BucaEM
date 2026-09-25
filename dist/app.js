const $=s=>document.querySelector(s);
const state={journals:[],articles:[],filtered:[],limit:30};

function esc(s){return String(s??"").replace(/[&<>"']/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[m]));}
function arr(v){return Array.isArray(v)?v:(v?[v]:[]);}
function text(a){
  return [
    a.title,a.titleOriginal,a.titleEn,
    arr(a.authors).join(" "),a.abstract,a.abstractOriginal,a.abstractEn,
    arr(a.keywords).join(" "),arr(a.keywordsOriginal).join(" "),arr(a.keywordsEn).join(" ")
  ].filter(Boolean).join(" ").toLowerCase();
}
function tokenize(q){
  const out=[];let i=0;
  while(i<q.length){
    if(/\s/.test(q[i])){i++;continue}
    if(q[i]==='"'){let j=i+1;while(j<q.length&&q[j]!=='"')j++;out.push({t:"TERM",v:q.slice(i+1,j)});i=j+1;continue}
    if("()".includes(q[i])){out.push({t:q[i],v:q[i]});i++;continue}
    let j=i;while(j<q.length&&!/\s|\(|\)/.test(q[j]))j++;
    const w=q.slice(i,j),u=w.toUpperCase();
    out.push({t:["AND","OR","NOT"].includes(u)?u:"TERM",v:w});i=j;
  }
  return out;
}
function compile(q){
  const ts=tokenize(q);let p=0;
  const term=t=>hay=>hay.includes(t.v.toLowerCase());
  function primary(){
    if(ts[p]?.t==="("){p++;const f=or();if(ts[p]?.t===")")p++;return f}
    if(ts[p]?.t==="NOT"){p++;const f=primary();return h=>!f(h)}
    const t=ts[p++];return t?.t==="TERM"?term(t):()=>true;
  }
  function and(){let f=primary();while(p<ts.length&&(ts[p].t==="AND"||ts[p].t==="TERM"||ts[p].t==="NOT"||ts[p].t==="(")){if(ts[p].t==="AND")p++;const g=primary(),old=f;f=h=>old(h)&&g(h)}return f}
  function or(){let f=and();while(ts[p]?.t==="OR"){p++;const g=and(),old=f;f=h=>old(h)||g(h)}return f}
  try{return or()}catch{return h=>h.includes(q.toLowerCase())}
}
function renderCard(a){
  const j=state.journals.find(x=>x.id===a.journal);
  const journal=j?.name||a.journal||"";
  const authors=arr(a.authors).join("; ");
  const kws=arr(a.keywordsOriginal?.length?a.keywordsOriginal:a.keywords);
  const hasEn=!!(a.titleEn||a.abstractEn||arr(a.keywordsEn).length);
  return `<article class="card">
    <h4>${esc(a.titleOriginal||a.title||"Untitled")}</h4>
    <div class="meta">${esc(journal)} · ${esc(a.year||"n.d.")}${a.language?` · ${esc(a.language)}`:""}</div>
    ${authors?`<div class="authors">${esc(authors)}</div>`:""}
    ${a.abstractOriginal||a.abstract?`<div class="abstract">${esc(a.abstractOriginal||a.abstract)}</div>`:"<div class='abstract'>Abstract not available in the source metadata.</div>"}
    ${kws.length?`<div class="chips">${kws.slice(0,10).map(x=>`<span class="chip">${esc(x)}</span>`).join("")}</div>`:""}
    <div class="english">
      ${hasEn?`<details><summary>English metadata</summary>
        ${a.titleEn?`<p><strong>Title:</strong> ${esc(a.titleEn)}</p>`:""}
        ${a.abstractEn?`<p><strong>Abstract:</strong> ${esc(a.abstractEn)}</p>`:""}
        ${arr(a.keywordsEn).length?`<p><strong>Keywords:</strong> ${esc(arr(a.keywordsEn).join("; "))}</p>`:""}
      </details>`:`<span class="pending">English metadata not available in the source.</span>`}
    </div>
    <div class="actions">
      ${a.doi?`<a target="_blank" rel="noopener" href="https://doi.org/${encodeURIComponent(a.doi)}">DOI</a>`:""}
      ${a.url?`<a target="_blank" rel="noopener" href="${esc(a.url)}">Article page</a>`:""}
      ${a.pdf?`<a target="_blank" rel="noopener" href="${esc(a.pdf)}">PDF</a>`:""}
    </div>
  </article>`;
}
function apply(){
  const q=$("#q").value.trim(), pred=q?compile(q):()=>true;
  const journal=$("#journal").value, lang=$("#language").value, type=$("#type").value;
  const yf=Number($("#yearFrom").value||0), yt=Number($("#yearTo").value||9999), oa=$("#oa").checked;
  state.filtered=state.articles.filter(a=>{
    const y=Number(a.year||0);
    return pred(text(a)) && (!journal||a.journal===journal) && (!lang||String(a.language||a.languageCode)===lang)
      && (!type||String(a.type||"")===type) && (!yf||y>=yf) && (!yt||y<=yt) && (!oa||a.openAccess===true);
  });
  const sort=$("#sort").value;
  state.filtered.sort((a,b)=>sort==="oldest"?(a.year||0)-(b.year||0):sort==="title"?String(a.title||"").localeCompare(String(b.title||"")):(b.year||0)-(a.year||0));
  state.limit=30;render();
}
function render(){
  $("#resultCount").textContent=`${state.filtered.length.toLocaleString()} results`;
  $("#cards").innerHTML=state.filtered.slice(0,state.limit).map(renderCard).join("")||"<div class='card'>No results.</div>";
  $("#moreBtn").hidden=state.limit>=state.filtered.length;
}
async function init(){
  const [manifest,journals]=await Promise.all([fetch("./data/catalog.json").then(r=>r.json()),fetch("./data/journals.json").then(r=>r.json())]);
  state.journals=journals;
  const chunks=manifest.chunks||[];
  const batches=await Promise.all(chunks.map(x=>fetch("./data/"+x).then(r=>r.json())));
  state.articles=batches.flat();
  $("#stats").textContent=`${state.articles.length.toLocaleString()} indexed records · ${state.journals.length} registered journals`;
  const js=[...new Map(state.journals.map(j=>[j.id,j])).values()].sort((a,b)=>String(a.name).localeCompare(String(b.name)));
  $("#journal").innerHTML='<option value="">All journals</option>'+js.map(j=>`<option value="${esc(j.id)}">${esc(j.name)}</option>`).join("");
  const langs=[...new Set(state.articles.map(a=>a.language||a.languageCode).filter(Boolean))].sort();
  $("#language").innerHTML='<option value="">All languages</option>'+langs.map(x=>`<option>${esc(x)}</option>`).join("");
  const types=[...new Set(state.articles.map(a=>a.type).filter(Boolean))].sort();
  $("#type").innerHTML='<option value="">All types</option>'+types.map(x=>`<option>${esc(x)}</option>`).join("");
  state.filtered=[...state.articles];render();
}
$("#searchBtn").onclick=apply;$("#q").addEventListener("keydown",e=>{if(e.key==="Enter")apply()});
["journal","language","type","yearFrom","yearTo","oa","sort"].forEach(id=>$("#"+id).addEventListener("change",apply));
$("#clearBtn").onclick=()=>{["q","journal","language","type","yearFrom","yearTo"].forEach(id=>$("#"+id).value="");$("#oa").checked=false;apply()};
$("#moreBtn").onclick=()=>{state.limit+=30;render()};
$("#aboutBtn").onclick=()=>$("#about").showModal();$("#closeAbout").onclick=()=>$("#about").close();
init().catch(e=>{$("#stats").textContent="Could not load catalogue.";console.error(e)});
