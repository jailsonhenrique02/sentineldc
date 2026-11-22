/* SentinelDC — painel NOC. Polling a cada 2 s em /api/racks/painel. */
const API = new URLSearchParams(location.search).get("api") || "";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { d: null, map: {}, sel: new Set(), preview: null, cache: {}, simSig: "", timer: null };

async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json" },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const txt = await r.text();
  let j = null;
  try { j = txt ? JSON.parse(txt) : null; } catch { /* resposta não-JSON */ }
  if (!r.ok) {
    const det = j && j.detail;
    const e = new Error(typeof det === "string" ? det : Array.isArray(det) ? det.map(x => x.msg).join("; ") : r.statusText);
    e.status = r.status;
    throw e;
  }
  return j;
}

/* só toca no DOM quando o HTML muda (evita perder foco e piscar) */
function pintar(chave, el, html) {
  if (S.cache[chave] !== html) { S.cache[chave] = html; el.innerHTML = html; }
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(S.timer); S.timer = setTimeout(() => (t.hidden = true), 3500);
}
function hora(ts) {
  if (!ts) return "";
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : ts + "Z");
  return d.toLocaleTimeString("pt-BR", { hour12: false });
}
const rackNome = id => (S.d.racks.find(r => r.id === id) || {}).nome || `rack ${id}`;

/* ---------- polling ---------- */
async function poll() {
  try {
    S.d = await api("/api/racks/painel");
    S.map = {};
    S.d.racks.forEach(r => r.ativos.forEach(a => (S.map[a.id] = { ...a, rack: r.nome })));
    for (const id of [...S.sel]) if (!S.map[id]) S.sel.delete(id);
    conexao(true);
    renderTudo();
  } catch { conexao(false); }
}
function conexao(on) {
  const c = $("#conn");
  c.textContent = on ? "ao vivo" : "sem conexão";
  c.className = "conn " + (on ? "on" : "off");
}
function renderTudo() {
  renderTopo(); renderBanner(); renderRacks(); renderOS(); renderLogs(); renderForm(); renderSim();
}

/* ---------- topo e banner ---------- */
function renderTopo() {
  const rs = S.d.racks, n = s => rs.filter(r => r.status_fisico === s).length;
  const off = Object.values(S.map).filter(a => a.status === "offline").length;
  const ativas = S.d.intervencoes.filter(o => o.status === "em_execucao").length;
  const c = (cls, v, t) => `<div class="cont ${cls}"><b>${v}</b><span>${t}</span></div>`;
  pintar("topo", $("#contadores"),
    c("ok", n("ok"), "racks ok") + c(n("alerta") ? "warn" : "", n("alerta"), "em alerta") +
    c(n("critico") ? "crit" : "", n("critico"), "críticos") + c(off ? "crit" : "", off, "ativos offline") +
    c("", ativas, "OS em execução"));
}
function renderBanner() {
  const d = S.d, L = d.limites, itens = [];
  d.violacoes.forEach(v => itens.push({ n: "crit", t: v.tipo === "fora_do_escopo"
    ? `Queda fora do escopo da ${v.os_codigo}: ${v.nome} (${rackNome(v.rack_id)}). Interrompa a intervenção.`
    : `Queda sem OS ativa: ${v.nome} (${rackNome(v.rack_id)}).` }));
  Object.values(S.map).filter(a => a.tipo === "ups" && a.em_bateria).forEach(u =>
    itens.push({ n: u.bateria_pct <= L.corte2 ? "crit" : "warn", t: `${u.nome} em bateria: ${Math.round(u.bateria_pct)}%` }));
  d.racks.filter(r => r.temperatura >= L.temp_alerta).forEach(r =>
    itens.push({ n: r.temperatura >= L.temp_critica ? "crit" : "warn", t: `${r.nome} a ${r.temperatura.toFixed(1)} °C` }));
  const b = $("#banner");
  b.hidden = !itens.length;
  b.className = "banner" + (itens.some(i => i.n === "crit") ? " tem-crit" : itens.length ? " tem-warn" : "");
  pintar("banner", b, itens.map(i => `<div class="it ${i.n}">${esc(i.t)}</div>`).join(""));
}

/* ---------- mapa dos racks ---------- */
function destaque() {
  const escopo = new Set(), impacto = new Set();
  S.d.intervencoes.filter(o => o.status === "em_execucao").forEach(o => {
    (o.ativos_escopo || []).forEach(i => escopo.add(i));
    (o.raio_impacto || []).forEach(i => impacto.add(i));
  });
  S.sel.forEach(i => escopo.add(i));
  if (S.preview) S.preview.raio_impacto.forEach(i => impacto.add(i));
  return { escopo, impacto };
}
function renderRacks() {
  const { escopo, impacto } = destaque(), L = S.d.limites;
  const html = S.d.racks.map(r => {
    const tcls = r.temperatura >= L.temp_critica ? "crit" : r.temperatura >= L.temp_alerta ? "warn" : "";
    const slots = r.ativos.map(a => {
      const st = a.status === "online" ? "ok" : a.status === "offline" ? "crit" : "shed";
      const linha = r.capacidade_u - (a.posicao_u + a.altura_u - 1) + 1;
      const extra = a.tipo === "ups" ? ` ${Math.round(a.bateria_pct ?? 0)}%${a.em_bateria ? " bat." : ""}` : "";
      const cl = ["slot", st, a.tipo, escopo.has(a.id) ? "esc" : impacto.has(a.id) ? "imp" : ""].join(" ");
      return `<button type="button" class="${cl}" data-id="${a.id}" style="grid-row:${linha} / span ${a.altura_u}"
        title="${esc(a.nome)} · ${a.tipo} · C${a.criticidade} · ${a.status.replace("_", " ")}">
        <span class="n">${esc(a.nome)}${extra}</span><span class="c">C${a.criticidade}</span></button>`;
    }).join("");
    return `<article class="rack ${r.status_fisico}${r.violacao ? " viol" : ""}">
      <header><h3>${esc(r.nome)}</h3><span class="temp ${tcls}">${r.temperatura.toFixed(1)} °C</span></header>
      <div class="elev" style="grid-template-rows:repeat(${r.capacidade_u},var(--u))">${slots}</div></article>`;
  }).join("");
  pintar("racks", $("#racks"), html);
}
$("#racks").addEventListener("click", e => {
  const b = e.target.closest(".slot");
  if (!b) return;
  const id = +b.dataset.id;
  if (!S.sel.size) $("#f-rack").value = S.map[id].rack_id;
  S.sel.has(id) ? S.sel.delete(id) : S.sel.add(id);
  mudouSelecao();
});

/* ---------- formulário de OS (gatekeeper ao vivo) ---------- */
let tPrev;
function mudouSelecao() {
  clearTimeout(tPrev);
  renderRacks(); renderForm();
  if (!S.sel.size) { S.preview = null; renderRacks(); renderForm(); return; }
  tPrev = setTimeout(async () => {
    try {
      S.preview = await api("/api/intervencoes/validar", { method: "POST",
        body: { rack_id: +$("#f-rack").value, ativos_ids: [...S.sel] } });
    } catch (e) {
      S.preview = { aprovada: false, erros: [e.message], avisos: [], raio_impacto: [], impacto_detalhe: [] };
    }
    renderRacks(); renderForm();
  }, 250);
}
function renderForm() {
  const sel = $("#f-rack"), ids = S.d.racks.map(r => r.id).join();
  if (S.cache.rackIds !== ids) {
    const atual = sel.value;
    sel.innerHTML = S.d.racks.map(r => `<option value="${r.id}">${esc(r.nome)}</option>`).join("");
    if (atual) sel.value = atual;
    S.cache.rackIds = ids;
  }
  pintar("chips", $("#chips"), S.sel.size
    ? [...S.sel].map(id => `<span class="chip">${esc(S.map[id].nome)} <small>${esc(S.map[id].rack)}</small>
        <button type="button" data-rm="${id}" aria-label="Remover ${esc(S.map[id].nome)}">×</button></span>`).join("")
    : `<p class="vazio">Nenhum ativo selecionado. Clique nos ativos do mapa.</p>`);

  const p = S.preview, box = $("#resultado");
  box.hidden = !p;
  if (p) {
    box.className = "resultado " + (p.aprovada ? "bom" : "ruim");
    const lista = (cls, xs) => xs.length ? `<ul class="${cls}">${xs.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    const fora = p.impacto_detalhe.filter(i => !S.sel.has(i.id));
    pintar("resultado", box, `<strong>${p.aprovada ? "Gatekeeper: aprovada" : "Gatekeeper: bloqueada"}</strong>` +
      lista("er", p.erros) + lista("av", p.avisos) +
      `<small>Raio de impacto: ${p.raio_impacto.length} ativo(s)` +
      (fora.length ? `, além do escopo: ${esc(fora.map(i => i.nome).join(", "))}` : ", sem efeito colateral") + `.</small>`);
  }
  $("#btn-abrir").disabled = !S.sel.size || !$("#f-desc").value.trim();
}
$("#chips").addEventListener("click", e => {
  const b = e.target.closest("[data-rm]");
  if (b) { S.sel.delete(+b.dataset.rm); mudouSelecao(); }
});
$("#f-rack").addEventListener("change", mudouSelecao);
$("#f-desc").addEventListener("input", renderForm);
$("#btn-abrir").addEventListener("click", async () => {
  try {
    const os = await api("/api/intervencoes", { method: "POST", body: {
      descricao: $("#f-desc").value.trim(), rack_id: +$("#f-rack").value,
      ativos_ids: [...S.sel], responsavel: $("#f-resp").value.trim() || "noc" } });
    toast(os.status === "validada" ? `${os.codigo} validada. Inicie quando o técnico estiver no rack.` : `${os.codigo} rejeitada pelo gatekeeper.`);
    if (os.status === "validada") { S.sel.clear(); $("#f-desc").value = ""; S.preview = null; }
    poll();
  } catch (e) { toast(e.message); }
});

/* ---------- lista de OS ---------- */
const ROTULO = { validada: "validada", em_execucao: "em execução", encerrada: "encerrada", rejeitada: "rejeitada" };
function renderOS() {
  const html = S.d.intervencoes.map(o => {
    const nomes = (o.ativos_escopo || []).map(i => (S.map[i] || {}).nome || `#${i}`).join(", ");
    const impacto = (o.raio_impacto || []).length - (o.ativos_escopo || []).length;
    const erros = o.status === "rejeitada" && o.validacao ? `<p class="meta">${esc((o.validacao.erros || []).join(" "))}</p>` : "";
    const acoes = o.status === "validada"
      ? `<button class="sec" data-act="iniciar" data-id="${o.id}">Iniciar</button><button class="sec" data-act="encerrar" data-id="${o.id}">Cancelar</button>`
      : o.status === "em_execucao" ? `<button class="sec" data-act="encerrar" data-id="${o.id}">Encerrar</button>` : "";
    return `<article class="os"><header><span class="cod">${esc(o.codigo)} <small class="meta">${esc(rackNome(o.rack_id))}</small></span>
      <span class="st ${o.status}">${ROTULO[o.status]}</span></header>
      <p>${esc(o.descricao)}</p><p class="meta">Escopo: ${esc(nomes)}${impacto > 0 ? ` · +${impacto} no raio de impacto` : ""}
      ${o.violacoes ? ` · <span class="viol-n">${o.violacoes} violação(ões)</span>` : ""}</p>${erros}
      ${acoes ? `<div class="acoes">${acoes}</div>` : ""}</article>`;
  }).join("") || `<p class="vazio">Nenhuma OS ainda.</p>`;
  pintar("os", $("#lista-os"), html);
}
$("#lista-os").addEventListener("click", async e => {
  const b = e.target.closest("[data-act]");
  if (!b) return;
  const id = b.dataset.id;
  try {
    if (b.dataset.act === "iniciar") {
      await api(`/api/intervencoes/${id}/iniciar`, { method: "POST" });
      toast("OS iniciada. Watchdog armado.");
    } else {
      try { await api(`/api/intervencoes/${id}/encerrar`, { method: "POST", body: {} }); }
      catch (err) {
        if (err.status !== 409 || !confirm(`${err.message}\n\nForçar o encerramento?`)) throw err;
        await api(`/api/intervencoes/${id}/encerrar`, { method: "POST", body: { forcar: true } });
      }
      toast("OS encerrada.");
    }
    poll();
  } catch (err) { toast(err.message); poll(); }
});

/* ---------- eventos ---------- */
function renderLogs() {
  pintar("logs", $("#logs"), S.d.logs.map(l =>
    `<li class="${l.nivel}"><time>${hora(l.ts)}</time><span><span class="o">${esc(l.origem)}</span> ${esc(l.mensagem)}</span></li>`).join(""));
}

/* ---------- simulador ---------- */
const evento = async corpo => { try { await api("/api/telemetria/evento", { method: "POST", body: corpo }); } catch (e) { toast(e.message); } poll(); };
function renderSim() {
  const ativos = Object.values(S.map), ups = ativos.filter(a => a.tipo === "ups");
  const sig = JSON.stringify([S.d.racks.map(r => r.id), ativos.map(a => a.id)]);
  const box = $("#sim");
  if (S.simSig !== sig) {
    S.simSig = sig;
    box.innerHTML = `
      <div class="bloco"><h3>Derrubar ou restaurar um ativo</h3>
        <select id="s-ativo">${ativos.map(a => `<option value="${a.id}">${esc(a.nome)} (${esc(a.rack)})</option>`).join("")}</select>
        <div class="botoes"><button class="sec perigo" data-s="off">Derrubar</button><button class="sec" data-s="on">Restaurar</button></div></div>
      <div class="bloco"><h3>UPS</h3>${ups.map(u => `
        <div><div class="par"><strong>${esc(u.nome)}</strong>
          <label style="display:flex;gap:6px;align-items:center"><input type="checkbox" data-ups="${u.id}" style="width:auto"> em bateria</label></div>
        <div class="rng"><span>Bateria</span><input type="range" min="0" max="100" step="1" data-bat="${u.id}"><span class="val" id="v-bat-${u.id}"></span></div></div>`).join("")}</div>
      <div class="bloco"><h3>Temperatura dos racks</h3>${S.d.racks.map(r => `
        <div class="rng"><span>${esc(r.nome)}</span><input type="range" min="18" max="42" step="0.5" data-temp="${r.id}"><span class="val" id="v-temp-${r.id}"></span></div>`).join("")}</div>
      <div class="bloco"><button class="sec" data-s="reset">Recarregar ambiente de demonstração</button></div>`;
  }
  const livre = el => el && document.activeElement !== el;
  ups.forEach(u => {
    const c = box.querySelector(`[data-ups="${u.id}"]`), r = box.querySelector(`[data-bat="${u.id}"]`);
    if (livre(c)) c.checked = u.em_bateria;
    if (livre(r)) r.value = u.bateria_pct ?? 0;
    $(`#v-bat-${u.id}`).textContent = Math.round(r.value) + "%";
  });
  S.d.racks.forEach(rk => {
    const r = box.querySelector(`[data-temp="${rk.id}"]`);
    if (livre(r)) r.value = rk.temperatura;
    $(`#v-temp-${rk.id}`).textContent = (+r.value).toFixed(1) + " °C";
  });
}
const simEl = $("#sim");
simEl.addEventListener("input", e => {
  const t = e.target;
  if (t.dataset.bat) $(`#v-bat-${t.dataset.bat}`).textContent = t.value + "%";
  if (t.dataset.temp) $(`#v-temp-${t.dataset.temp}`).textContent = (+t.value).toFixed(1) + " °C";
});
simEl.addEventListener("change", e => {
  const t = e.target;
  if (t.dataset.ups || t.dataset.bat) {
    const id = +(t.dataset.ups || t.dataset.bat);
    // baixar a bateria só faz sentido com a UPS fora da rede: marca "em bateria" sozinho
    if (t.dataset.bat && +t.value < (S.map[id].bateria_pct ?? 100)) {
      simEl.querySelector(`[data-ups="${id}"]`).checked = true;
    }
    evento({ tipo: "ups", ativo_id: id,
      em_bateria: simEl.querySelector(`[data-ups="${id}"]`).checked,
      bateria_pct: +simEl.querySelector(`[data-bat="${id}"]`).value });
  } else if (t.dataset.temp) {
    evento({ tipo: "temperatura", rack_id: +t.dataset.temp, valor: +t.value });
  }
});
simEl.addEventListener("click", async e => {
  const b = e.target.closest("[data-s]");
  if (!b) return;
  if (b.dataset.s === "reset") {
    if (!confirm("Apagar tudo e recarregar o ambiente de demonstração?")) return;
    try { await api("/api/demo/reset", { method: "POST" }); S.sel.clear(); S.preview = null; S.cache = {}; S.simSig = ""; toast("Ambiente recarregado."); } catch (err) { toast(err.message); }
    return poll();
  }
  evento({ tipo: "ativo_status", ativo_id: +$("#s-ativo").value, status: b.dataset.s === "off" ? "offline" : "online" });
});

/* ---------- abas e relógio ---------- */
document.querySelectorAll(".abas button").forEach(b => b.addEventListener("click", () => {
  document.querySelectorAll(".abas button").forEach(x => x.setAttribute("aria-selected", x === b));
  ["os", "ev", "sim"].forEach(k => ($("#aba-" + k).hidden = k !== b.dataset.tab));
}));
setInterval(() => ($("#relogio").textContent = new Date().toLocaleTimeString("pt-BR", { hour12: false })), 1000);
poll();
setInterval(poll, 2000);