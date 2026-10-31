const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = (path, params = {}) => fetch(`/api/${path}?${new URLSearchParams(params)}`).then((r) => r.json());
// 只有 http(s) 来源才渲染为链接
const safeUrl = (u) => (/^https?:\/\//.test(u || "") ? esc(u) : "");
const CALLI = ["书法", "书画", "篆刻", "未标注"];
const ALL_DOMAINS = ["书法", "书画", "篆刻", "绘画", "学术", "其他", "未标注"];

const EXAMPLES = ["王羲之的老师是谁", "张旭的弟子有哪些", "颜真卿的师承谱系", "兰亭集序是谁写的", "祭侄文稿藏在哪里", "宋朝擅长草书的书法家有哪些", "唐朝有多少书法家", "隶书作品有哪些", "颜真卿的同门", "王献之和锺繇有什么关系"];
const SAMPLE_SPARQL = `# 师从领域为“书法”的关系及其证据句
SELECT ?学生 ?老师 ?证据 WHERE {
  ?st rdf:predicate shufa:studiedUnder ;
      rdf:subject ?s ; rdf:object ?t ;
      shufa:relationDomain "书法" ;
      shufa:evidence ?证据 .
  ?s cns:name ?学生 .
  ?t cns:name ?老师 .
} LIMIT 20`;

/* ---------- 标签页 ---------- */
let analysisLoaded = false, networkLoaded = false;
function showTab(name) {
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === name));
  if (name === "analysis" && !analysisLoaded) { analysisLoaded = true; loadAnalysis(); }
  if (name === "network" && !networkLoaded) { networkLoaded = true; loadNetwork(); }
  try { localStorage.setItem("tab", name); } catch (e) {}
}
$("tabs").addEventListener("click", (e) => { if (e.target.dataset.tab) showTab(e.target.dataset.tab); });

/* ---------- 证据和实体链接 ---------- */
function tags(x) {
  const out = [];
  if (x.label) out.push(`<span class="tag">${esc(x.label)}</span>`);
  if (x.domain) out.push(`<span class="tag ${CALLI.slice(0, 3).includes(x.domain) ? "calli" : ""}">${esc(x.domain)}</span>`);
  if (x.method) out.push(`<span class="tag">${esc(x.method)}</span>`);
  return out.join("");
}
function sourceLink(x) {
  const u = safeUrl(x.source);
  return u ? ` <a href="${u}" target="_blank" rel="noopener">来源</a>` : "";
}
function entityLink(name, id) {
  return id ? `<button class="link" data-entity="${esc(id)}">${esc(name)}</button>` : `<span>${esc(name)}</span>`;
}
function itemHtml(x) {
  const via = x.via ? `<span class="hint"> 经 ${esc(x.via)}</span>` : "";
  const ev = x.evidence ? `<p class="evidence">${esc(x.evidence)}${sourceLink(x)}</p>` : (x.source ? `<p class="evidence">无证据句，取自结构化数据。${sourceLink(x)}</p>` : "");
  return `<div class="item">${entityLink(x.name, x.id)}${via} ${tags(x)}${ev}</div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-entity]");
  if (b) openEntity(b.dataset.entity);
});

/* ---------- 问答 ---------- */
$("examples").innerHTML = EXAMPLES.map((q) => `<button type="button">${esc(q)}</button>`).join("");
$("examples").addEventListener("click", (e) => { if (e.target.tagName === "BUTTON") { $("askInput").value = e.target.textContent; ask(); } });
$("askForm").addEventListener("submit", (e) => { e.preventDefault(); ask(); });
async function ask() {
  const q = $("askInput").value.trim();
  if (!q) return;
  $("askResult").innerHTML = `<p class="hint">正在查询</p>`;
  const r = await api("ask", { q });
  if (r.error) { $("askResult").innerHTML = `<div class="answer unknown"><p class="text">查询出错：${esc(r.error)}</p></div>`; return; }
  const ents = r.entities.map((x) => `<button class="result" data-entity="${esc(x.id)}"><b>${esc(x.name)}</b><span class="tag">${esc(x.typeLabel)}</span>${x.life ? `<span class="hint">${esc(x.life)}</span>` : ""}<p>${esc(x.description)}</p></button>`).join("");
  const shown = r.items.slice(0, 60);
  const items = shown.map(itemHtml).join("");
  $("askResult").innerHTML = `
    <div class="answer ${esc(r.status)}">
      <p class="meta">问题类型：${esc(r.intent)}</p>
      <p class="text">${esc(r.answer)}</p>
      ${r.note ? `<p class="hint">${esc(r.note)}</p>` : ""}
      ${r.sparql ? `<details><summary>查看生成的 SPARQL</summary><pre>${esc(r.sparql)}</pre></details>` : ""}
    </div>
    ${items ? `<div class="card">${items}${r.items.length > shown.length ? `<p class="hint">只显示前 ${shown.length} 项，共 ${r.items.length} 项。</p>` : ""}</div>` : ""}
    ${ents}`;
}

/* ---------- 检索 ---------- */
$("searchForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("searchInput").value.trim();
  if (!q) return;
  const r = await api("search", { q, type: $("searchType").value });
  $("searchResult").innerHTML = `<p class="hint">找到 ${r.results.length} 个实体${r.results.length === 40 ? "（只显示前 40 个）" : ""}。</p>` +
    r.results.map((x) => `<button class="result" data-entity="${esc(x.id)}"><b>${esc(x.name)}</b><span class="tag">${esc(x.typeLabel)}</span>${x.dynasty.map((d) => `<span class="tag">${esc(d)}</span>`).join("")}${x.life ? `<span class="hint">${esc(x.life)}</span>` : ""}${x.description ? `<p>${esc(x.description)}</p>` : ""}</button>`).join("");
});

/* ---------- 实体详情 ---------- */
$("drawerClose").addEventListener("click", () => $("drawer").classList.remove("on"));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("drawer").classList.remove("on"); });
async function openEntity(id) {
  const x = await api("entity", { id });
  if (x.error) return;
  const groups = {};
  x.relations.forEach((r) => (groups[r.label] = groups[r.label] || []).push(r));
  const facts = [x.life && `生卒：${x.life}`, x.gender && `性别：${x.gender}`, x.birthPlace && `出生地：${x.birthPlace}`, x.alternateName.length && `字号：${x.alternateName.join("、")}`].filter(Boolean);
  const canMap = ["Calligrapher", "Person"].includes(x.type);
  $("drawerBody").innerHTML = `
    <h2>${esc(x.name)}</h2>
    <p class="meta"><span class="tag">${esc(x.typeLabel)}</span>${x.dynasty.map((d) => `<span class="tag">${esc(d)}</span>`).join("")}</p>
    ${facts.length ? `<p class="meta">${facts.map(esc).join(" · ")}</p>` : ""}
    ${x.description ? `<p class="desc">${esc(x.description)}</p>` : `<p class="hint">没有简介。${canMap ? "这个人物是作为其他人物的老师或学生被提到的。" : ""}</p>`}
    <p class="meta">
      ${canMap ? `<button class="link" id="toNet">看师承网络</button> · ` : ""}
      ${safeUrl(x.url) ? `<a href="${safeUrl(x.url)}" target="_blank" rel="noopener">维基百科</a>` : ""}
      ${safeUrl(x.sameAs) ? ` · <a href="${safeUrl(x.sameAs)}" target="_blank" rel="noopener">Wikidata</a>` : ""}
    </p>
    ${Object.entries(groups).map(([label, rs]) => `<h3>${esc(label)}（${rs.length}）</h3>` + rs.slice(0, 40).map((r) => itemHtml({ name: r.name, id: r.id, domain: r.domain, method: r.method, evidence: r.evidence, source: r.source })).join("") + (rs.length > 40 ? `<p class="hint">只显示前 40 项。</p>` : "")).join("")}`;
  const btn = $("toNet");
  if (btn) btn.addEventListener("click", () => { $("netInput").value = x.name; networkLoaded = true; showTab("network"); loadNetwork(x.id); $("drawer").classList.remove("on"); });
  $("drawer").classList.add("on");
  $("drawer").scrollTop = 0;
}

/* ---------- 师承网络 ---------- */
$("domains").innerHTML = "领域：" + ALL_DOMAINS.map((d) => `<label><input type="checkbox" value="${d}" ${CALLI.includes(d) ? "checked" : ""}> ${d}</label>`).join("");
$("domains").addEventListener("change", () => loadNetwork(currentCenter));
$("netDepth").addEventListener("change", () => { if (currentCenter) loadNetwork(currentCenter); });
$("netForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("netInput").value.trim();
  if (!q) return loadNetwork(null);
  const r = await api("search", { q });
  const person = r.results.find((x) => ["Calligrapher", "Person"].includes(x.type));
  if (!person) { $("netHint").textContent = `图谱里没有找到人物“${q}”。`; return; }
  $("netInput").value = person.name;
  loadNetwork(person.id);
});
let currentCenter = null, stopSim = null;
async function loadNetwork(id) {
  currentCenter = id || null;
  const domains = [...$("domains").querySelectorAll("input:checked")].map((i) => i.value).join(",");
  const params = { depth: $("netDepth").value, domains };
  if (id) params.id = id;
  const data = domains ? await api("network", params) : { nodes: [], links: [] };
  const center = data.nodes.find((n) => n.center);
  const isolated = id && data.links.length === 0;
  $("netHint").textContent = isolated ? "在所选领域内，这个人物没有师承连接。可以勾选更多领域再看。" :
    `${center ? center.name + "的" : "连接最多人物的"}网络：${data.nodes.length} 人，${data.links.length} 条关系。`;
  drawNetwork(data);
}
function drawNetwork({ nodes, links }) {
  if (stopSim) stopSim();
  const svg = $("netSvg");
  const W = svg.clientWidth || 900, H = svg.clientHeight || 560;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const NS = "http://www.w3.org/2000/svg";
  svg.innerHTML = `<defs><marker id="arrow" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L8 4L0 8z"/></marker></defs>`;
  const byId = new Map(nodes.map((n, i) => {
    const a = i * 2.399963, r = 14 * Math.sqrt(i + 1); // 向日葵排布，确定性的初始位置
    n.x = W / 2 + r * Math.cos(a); n.y = H / 2 + r * Math.sin(a); n.vx = 0; n.vy = 0;
    n.r = n.center ? 9 : Math.min(4 + Math.sqrt(n.degree) * 1.6, 12);
    return [n.id, n];
  }));
  const edges = links.map((l) => ({ ...l, s: byId.get(l.source), t: byId.get(l.target) }));
  const lineEls = edges.map((l) => {
    const el = document.createElementNS(NS, "line");
    if (l.predicate === "emulated") el.setAttribute("class", "emulated");
    el.setAttribute("marker-end", "url(#arrow)");
    svg.appendChild(el);
    el.addEventListener("mouseenter", (e) => tip(e, `${l.s.name} ${l.label} ${l.t.name}（${l.domain}）`));
    el.addEventListener("mouseleave", hideTip);
    return el;
  });
  const showAllLabels = nodes.length <= 70;
  const nodeEls = nodes.map((n) => {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("r", n.r);
    c.setAttribute("class", (n.type === "Calligrapher" ? "calligrapher " : "") + (n.center ? "center" : ""));
    const t = document.createElementNS(NS, "text");
    t.textContent = showAllLabels || n.degree >= 4 || n.center ? n.name : "";
    svg.appendChild(c); svg.appendChild(t);
    c.addEventListener("mouseenter", (e) => tip(e, `${n.name}（${n.degree} 条关系）`));
    c.addEventListener("mouseleave", hideTip);
    let moved = false;
    c.addEventListener("pointerdown", (e) => {
      e.preventDefault(); moved = false; n.fixed = true; c.setPointerCapture(e.pointerId); wake();
      const move = (ev) => {
        moved = true;
        const box = svg.getBoundingClientRect();
        n.x = (ev.clientX - box.left) * W / box.width; n.y = (ev.clientY - box.top) * H / box.height;
        wake();
      };
      const up = () => { c.removeEventListener("pointermove", move); c.removeEventListener("pointerup", up); if (!moved) { n.fixed = false; openEntity(n.id); } };
      c.addEventListener("pointermove", move); c.addEventListener("pointerup", up);
    });
    return { c, t };
  });
  let alpha = 1, raf = null, stopped = false;
  function step() {
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      let dx = b.x - a.x, dy = b.y - a.y, d2 = dx * dx + dy * dy || 1;
      if (d2 > 160000) continue;
      const f = 4200 / d2 * alpha, d = Math.sqrt(d2);
      dx /= d; dy /= d;
      a.vx -= dx * f; a.vy -= dy * f; b.vx += dx * f; b.vy += dy * f;
    }
    edges.forEach((l) => {
      let dx = l.t.x - l.s.x, dy = l.t.y - l.s.y; const d = Math.hypot(dx, dy) || 1;
      const f = (d - 96) * 0.05 * alpha; dx /= d; dy /= d;
      l.s.vx += dx * f; l.s.vy += dy * f; l.t.vx -= dx * f; l.t.vy -= dy * f;
    });
    nodes.forEach((n) => {
      n.vx += (W / 2 - n.x) * 0.006 * alpha; n.vy += (H / 2 - n.y) * 0.009 * alpha;
      if (!n.fixed) { n.x += n.vx; n.y += n.vy; }
      n.vx *= 0.82; n.vy *= 0.82;
      n.x = Math.max(16, Math.min(W - 16, n.x)); n.y = Math.max(16, Math.min(H - 16, n.y));
    });
  }
  function paint() {
    edges.forEach((l, i) => {
      const dx = l.t.x - l.s.x, dy = l.t.y - l.s.y, d = Math.hypot(dx, dy) || 1;
      lineEls[i].setAttribute("x1", l.s.x); lineEls[i].setAttribute("y1", l.s.y);
      lineEls[i].setAttribute("x2", l.t.x - dx / d * (l.t.r + 3)); lineEls[i].setAttribute("y2", l.t.y - dy / d * (l.t.r + 3));
    });
    nodes.forEach((n, i) => {
      nodeEls[i].c.setAttribute("cx", n.x); nodeEls[i].c.setAttribute("cy", n.y);
      nodeEls[i].t.setAttribute("x", n.x + n.r + 3); nodeEls[i].t.setAttribute("y", n.y + 4);
    });
  }
  function tick() {
    if (stopped) return;
    step(); paint();
    alpha *= 0.985;
    raf = alpha > 0.02 ? requestAnimationFrame(tick) : null;
  }
  function wake() { alpha = Math.max(alpha, 0.3); if (!raf) raf = requestAnimationFrame(tick); }
  // 先在后台收敛，再显示，避免一开始节点乱飞
  for (let i = 0; i < 180; i++) { step(); alpha *= 0.985; }
  paint();
  stopSim = () => { stopped = true; if (raf) cancelAnimationFrame(raf); };
}
function tip(e, text) {
  const t = $("tip"); t.textContent = text; t.style.display = "block";
  t.style.left = Math.min(e.clientX + 12, innerWidth - 290) + "px"; t.style.top = e.clientY - 34 + "px";
}
function hideTip() { $("tip").style.display = "none"; }

/* ---------- 分析 ---------- */
async function loadAnalysis() {
  const a = await api("analysis");
  const max = Math.max(...a.dynastyCount.map((d) => d.count));
  const cross = new Map(a.cross.map((c) => [c.dynasty + "|" + c.script, c.count]));
  const cmax = Math.max(...a.cross.map((c) => c.count), 1);
  const level = (v) => (v === 0 ? 0 : Math.min(4, Math.ceil(Math.sqrt(v / cmax) * 4)));
  $("analysisBody").innerHTML = `
    <div class="stat">
      <div><b>${a.lineageNodes}</b><span>师承网络人物</span></div>
      <div><b>${a.lineageEdges}</b><span>师承和取法关系</span></div>
      <div><b>${a.components}</b><span>互不相连的群体</span></div>
      <div><b>${a.largestComponent}</b><span>最大群体人数</span></div>
    </div>
    <p class="hint">网络分析只用 ${a.domainsUsed.join("、")} 领域的关系。排名反映图谱收录情况，受维基条目详略影响，不等于书法史上的实际地位。</p>
    <div class="card"><h2>最长师承链</h2><p>沿“师从或取法”向上追溯得到的最长路径。</p>
      <div class="chain">${a.longestChain.map((x) => entityLink(x.name, x.id)).join("<span>→</span>")}</div></div>
    <div class="card"><h2>师承影响力前 15 位</h2><p>在“学生指向老师”的网络上计算 PageRank。</p>
      <table><thead><tr><th>排名</th><th>人物</th><th>朝代</th><th class="num">直接学生或取法者</th><th class="num">PageRank</th></tr></thead><tbody>
      ${a.influence.map((x, i) => `<tr><td>${i + 1}</td><td>${entityLink(x.name, x.id)}</td><td>${esc(x.dynasty.join("、"))}</td><td class="num">${x.students}</td><td class="num">${x.pagerank.toFixed(4)}</td></tr>`).join("")}
      </tbody></table></div>
    <div class="card"><h2>各时期收录的书法家人数</h2><p>一人可属于多个时期。人数集中在明清和近现代，也反映维基条目的分布。</p>
      ${a.dynastyCount.map((d) => `<div class="barrow" data-tip="${esc(d.name)}：${d.count} 位"><span>${esc(d.name)}</span><div class="track"><div class="fill" style="width:${(d.count / max) * 100}%"></div></div><span class="num">${d.count}</span></div>`).join("")}</div>
    <div class="card"><h2>各时期擅长书体的书法家人数</h2><p>只统计正文明确写出擅长书体的人物，颜色越深人数越多。古文的“隶书”常指今天的楷书，晋和南北朝的隶书人数因此可能偏高。</p>
      <table class="heat"><thead><tr><th></th>${a.scripts.map((s) => `<th>${esc(s)}</th>`).join("")}</tr></thead><tbody>
      ${a.dynastyCount.map((d) => `<tr><th>${esc(d.name)}</th>${a.scripts.map((s) => { const v = cross.get(d.name + "|" + s) || 0; return `<td class="h${level(v)}" data-tip="${esc(d.name)} · ${esc(s)}：${v} 位">${v}</td>`; }).join("")}</tr>`).join("")}
      </tbody></table></div>`;
  $("analysisBody").addEventListener("mousemove", (e) => { const c = e.target.closest("[data-tip]"); if (c) tip(e, c.dataset.tip); else hideTip(); });
  $("analysisBody").addEventListener("mouseleave", hideTip);
}

/* ---------- SPARQL ---------- */
$("sparqlInput").value = SAMPLE_SPARQL;
$("sparqlRun").addEventListener("click", async () => {
  $("sparqlInfo").textContent = "正在运行";
  const r = await api("sparql", { q: $("sparqlInput").value });
  if (r.error) { $("sparqlInfo").textContent = ""; $("sparqlResult").innerHTML = `<pre>${esc(r.error)}</pre>`; return; }
  $("sparqlInfo").textContent = `${r.rows.length} 行${r.rows.length === 500 ? "（最多显示 500 行）" : ""}`;
  const cols = r.rows.length ? Object.keys(r.rows[0]) : [];
  $("sparqlResult").innerHTML = cols.length ? `<table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${r.rows.map((row) => `<tr>${cols.map((c) => `<td>${esc(row[c])}</td>`).join("")}</tr>`).join("")}</tbody></table>` : "";
});

/* ---------- 启动 ---------- */
api("stats").then((s) => { $("scale").textContent = `${s["实体总数"]} 个实体 · ${s["关系总数"]} 条关系`; });
let startTab = "ask";
try { startTab = localStorage.getItem("tab") || "ask"; } catch (e) {}
showTab(startTab);
