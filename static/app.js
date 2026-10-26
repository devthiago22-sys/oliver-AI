/* Oliver · front-end
 *
 * Conversa (aba "Conversa"): a pessoa diz a cidade do Maranhão; o servidor busca os
 * dados oficiais coletados (INPE, INMET, com Open-Meteo como fonte complementar),
 * passa pela rede neural e devolve { reply, options, state, reports[] }.
 * Simulação (aba "Simulação"): valores técnicos digitados à mão (modo "manual").
 */
(() => {
  "use strict";

  const API_URL = window.OLIVER_API || "/api/oliver";
  const LOGIN_PAGE = window.OLIVER_LOGIN_PAGE || "/";
  const LEAFLET = {
    css: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css",
    js: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js",
  };
  const MA_BOUNDS = [[-10.3, -48.8], [-1.0, -41.7]];
  const PDF_OPTION = "Gerar relatório em PDF";

  const TITLES = { fire: "Risco de queimadas", flood: "Risco de alagamento", panorama: "Panorama do Maranhão" };
  const DOMAIN_LABEL = { fire: "queimadas", flood: "alagamento", panorama: "panorama do Maranhão" };
  const RISK_ORDER = ["Baixo", "Moderado", "Alto"];

  const state = {
    busy: false,
    chat: {},          // estado da conversa regional (cidade, perguntas respondidas)
    history: [],       // histórico só para a simulação manual
    reports: {},       // fire / flood / panorama → { data, at }
    shown: [],         // relatórios mostrados no painel agora
    sim: "fire",
  };

  // ---------- Atalhos de DOM ----------
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
  const el = (tag, props = {}, children = []) => {
    const { dataset, ...rest } = props;
    const node = Object.assign(document.createElement(tag), rest);
    if (dataset) Object.assign(node.dataset, dataset);
    for (const c of [].concat(children)) node.append(c);
    return node;
  };

  const messages = $("#messages");
  const chatForm = $("#chat-form");
  const chatInput = $("#chat-input");
  const sendBtn = $(".send-btn");

  // ---------- Mensagens ----------
  function addMessage(role, text, extra) {
    const li = el("li", { className: `msg ${role}` }, [
      el("span", { className: "who", textContent: role === "user" ? "Você" : "Oliver" }),
      document.createTextNode(text),
    ]);
    if (extra) li.append(extra);
    messages.append(li);
    messages.scrollTop = messages.scrollHeight;
    return li;
  }

  function addError(text) {
    const li = el("li", { className: "msg error", textContent: text });
    messages.append(li);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const li = el("li", { className: "msg bot typing" }, [
      el("span", { className: "who", textContent: "Oliver" }),
      el("span", { className: "typing-dots", innerHTML: "<span></span><span></span><span></span>" }),
      el("span", { className: "visually-hidden", textContent: "Oliver está buscando os dados" }),
    ]);
    messages.append(li);
    messages.scrollTop = messages.scrollHeight;
    return li;
  }

  function quickButtons(labels) {
    const box = el("div", { className: "quick" });
    for (const label of labels) {
      box.append(el("button", {
        type: "button", textContent: label,
        onclick: () => (label === PDF_OPTION ? generatePdf() : send(label)),
      }));
    }
    return box;
  }

  // ---------- Comunicação com o servidor ----------
  async function callOliver(payload) {
    let res;
    try {
      res = await fetch(API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    } catch {
      const err = new Error("offline"); err.offline = true; throw err;
    }
    if (res.status === 401) { location.href = LOGIN_PAGE; throw new Error("Sua sessão expirou. Entre novamente."); }
    if (res.status === 404 || res.status === 405) { const e = new Error("offline"); e.offline = true; throw e; }
    let data = null;
    try { data = await res.json(); } catch { /* resposta sem JSON */ }
    if (!res.ok || !data || data.error) throw new Error((data && data.error) || `O servidor respondeu com erro ${res.status}.`);
    return data;
  }

  async function send(message, { mode = "regional", domain = "auto", showInChat = true, resetHistory = false } = {}) {
    message = message.trim();
    if (!message || state.busy) return;
    if (resetHistory) state.history = [];
    setBusy(true);
    if (showInChat) addMessage("user", message);
    const typing = showTyping();
    try {
      const payload = mode === "manual"
        ? { message, mode, domain, history: state.history }
        : { message, mode, state: state.chat };
      const data = await callOliver(payload);
      typing.remove();
      handleResponse(data, mode, message);
    } catch (err) {
      typing.remove();
      if (!err.offline) console.error(err);
      addError(err.offline
        ? "O servidor do Oliver não está respondendo. Se estiver rodando no seu computador, abra o terminal na pasta do projeto, rode python app.py e acesse http://127.0.0.1:5000."
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  function handleResponse(data, mode, message) {
    if (mode === "manual") {
      state.history.push({ role: "user", text: message }, { role: "assistant", text: data.reply });
      if (data.complete) state.history = [];
    } else if (data.state) {
      state.chat = data.state;
    }

    const reports = Array.isArray(data.reports) ? data.reports
      : data.complete && ["fire", "flood", "panorama"].includes(data.domain) ? [data] : [];
    const at = new Date();
    for (const r of reports) state.reports[r.domain] = { data: r, at };

    let options = Array.isArray(data.options) ? [...data.options] : [];
    if (reports.length && !options.includes(PDF_OPTION)) options.unshift(PDF_OPTION);
    addMessage("bot", data.reply, options.length ? quickButtons(options) : null);

    if (reports.length) {
      showReports(reports);
      updateReport();
      if (window.matchMedia("(max-width: 900px)").matches) {
        $(".result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } else if (mode === "manual" && data.findings && data.findings.length) {
      showReports([data]);
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    sendBtn.disabled = busy;
    $$(".primary-btn").forEach((b) => (b.disabled = busy));
  }

  // ---------- Abas ----------
  function selectTab(which) {
    const isChat = which === "chat";
    $("#tab-chat").setAttribute("aria-selected", String(isChat));
    $("#tab-form").setAttribute("aria-selected", String(!isChat));
    $("#pane-chat").hidden = !isChat;
    $("#pane-form").hidden = isChat;
    (isChat ? chatInput : $("#pane-form .data-form:not([hidden]) input"))?.focus();
  }
  $("#tab-chat").addEventListener("click", () => selectTab("chat"));
  $("#tab-form").addEventListener("click", () => selectTab("form"));
  $(".mode-switch").addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      const toForm = $("#tab-chat").getAttribute("aria-selected") === "true";
      selectTab(toForm ? "form" : "chat");
      $(toForm ? "#tab-form" : "#tab-chat").focus();
    }
  });

  // ---------- Conversa ----------
  chatForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = chatInput.value;
    chatInput.value = "";
    autoGrow();
    send(text);
  });
  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); chatForm.requestSubmit(); }
  });
  function autoGrow() {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 160) + "px";
  }
  chatInput.addEventListener("input", autoGrow);

  // ---------- Simulação (valores técnicos) ----------
  function setSim(domain) {
    state.sim = domain;
    $$(".sim-switch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.sim === domain)));
    $$(".data-form").forEach((f) => (f.hidden = f.dataset.domain !== domain));
  }
  $$(".sim-switch button").forEach((b) => b.addEventListener("click", () => setSim(b.dataset.sim)));

  const BUILDERS = {
    fire: (v) =>
      `Localização: ${v.loc}; fogo ativo: ${v.active}; vento: ${v.wind} km/h; direção do vento: ${v.dir}; ` +
      `umidade: ${v.hum}%; secura da vegetação: ${v.dry}%; declividade: ${v.slope}%.`,
    flood: (v) =>
      `Localização: ${v.loc}; chuva acumulada: ${v.rain} mm; chuva prevista: ${v.forecast} mm; ` +
      `distância do rio: ${v.dist} m; drenagem: ${v.drain}; piso vulnerável: ${v.floor}.`,
  };

  $$(".data-form").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const errorBox = $(".form-error", form);
      let firstInvalid = null;
      for (const field of form.elements) {
        if (!field.name || field.type === "radio") continue;
        const ok = field.checkValidity();
        field.setAttribute("aria-invalid", String(!ok));
        if (!ok && !firstInvalid) firstInvalid = field;
      }
      const radios = $$('input[type="radio"]', form);
      const radioOk = !radios.length || radios.some((r) => r.checked);
      if (firstInvalid || !radioOk) {
        errorBox.textContent = radioOk
          ? "Preencha os campos destacados. Vento, umidade, secura e declividade vão de 0 a 100."
          : "Informe se há fogo ativo agora.";
        errorBox.hidden = false;
        (firstInvalid || radios[0]).focus();
        return;
      }
      errorBox.hidden = true;
      const values = Object.fromEntries(new FormData(form));
      values.loc = values.loc.replace(/[;.!?\n]/g, " ").trim();
      send(BUILDERS[form.dataset.domain](values), { mode: "manual", domain: form.dataset.domain, resetHistory: true });
    });
    form.addEventListener("input", (e) => e.target.removeAttribute("aria-invalid"));
  });

  // ---------- Painel de resultado ----------
  function clearResult() {
    state.shown = [];
    $("#result-switch").hidden = true;
    $("#result-title").textContent = "Nenhuma análise ainda";
    setBadge("", "Aguardando cidade");
    setGauge(null);
    $("#gauge").hidden = false;
    for (const id of ["#probs", "#findings-block", "#actions-block", "#map-block", "#sources-block"]) $(id).hidden = true;
    $("#reset-btn").hidden = true;
  }

  function setBadge(risk, text) {
    const badge = $("#risk-badge");
    badge.dataset.risk = RISK_ORDER.includes(risk) ? risk : "";
    badge.textContent = RISK_ORDER.includes(risk) ? `Risco ${risk.toLowerCase()}` : text;
  }

  function setGauge(score, level, caption) {
    const gauge = $("#gauge");
    const needle = $("#gauge-needle");
    $$(".zone", gauge).forEach((z) => z.classList.toggle("on", z.dataset.zone === level));
    if (score == null) {
      gauge.classList.remove("has-value");
      needle.style.left = "0%";
      $("#gauge-value").textContent = "–";
      $("#gauge-caption").textContent = caption || "Diga a sua cidade no chat. O índice de 0 a 100 aparece aqui.";
      return;
    }
    gauge.classList.add("has-value");
    needle.style.left = `${Math.max(0, Math.min(100, score))}%`;
    $("#gauge-value").textContent = score;
    $("#gauge-caption").textContent = caption || "Índice calculado pela rede neural do Oliver.";
  }

  function showReports(list) {
    state.shown = list;
    const sw = $("#result-switch");
    sw.replaceChildren();
    sw.hidden = list.length < 2;
    list.forEach((r, i) => {
      sw.append(el("button", {
        type: "button", role: "tab", className: "chip",
        textContent: `${cap(DOMAIN_LABEL[r.domain] || "análise")} · ${r.overall_risk}`,
        dataset: { risk: r.overall_risk },
        onclick: () => selectReport(i),
      }));
    });
    selectReport(0);
  }

  function selectReport(i) {
    const r = state.shown[i];
    $$("#result-switch .chip").forEach((c, j) => c.setAttribute("aria-selected", String(i === j)));
    if (r) renderResult(r);
  }

  function renderResult(data) {
    const findings = Array.isArray(data.findings) ? data.findings : [];
    const isPanorama = data.domain === "panorama";
    document.body.dataset.domain = data.domain === "flood" ? "flood" : "fire";

    $("#result-title").textContent = data.complete
      ? `${TITLES[data.domain] || "Análise"}${data.location && !isPanorama ? " · " + data.location : ""}`
      : "Coletando dados";
    setBadge(data.overall_risk, data.overall_risk || "Aguardando");

    if (isPanorama) {
      const c = data.regional.contagem || {};
      $("#gauge").hidden = true;
      setGauge(null, null, `${c.Alto || 0} municípios com risco alto, ${c.Moderado || 0} com risco moderado e ${c.Baixo || 0} com risco baixo de propagação de fogo. ${data.regional.focos_24h} focos de calor nas últimas 24 h.`);
    } else {
      $("#gauge").hidden = false;
      const scoreRow = findings.find((f) => /^Risco estimado/.test(f.metric));
      const sc = scoreRow ? parseInt(String(scoreRow.value), 10) : null;
      setGauge(Number.isFinite(sc) ? sc : null, data.overall_risk);
    }

    // Probabilidades
    const probRows = findings.filter((f) => /^Probabilidade/.test(f.metric));
    const probList = $("#prob-list");
    probList.replaceChildren();
    for (const row of probRows) {
      const pct = parseFloat(String(row.value).replace(",", ".")) || 0;
      const bar = el("i");
      bar.style.background = `var(--risk-${row.risk.toLowerCase()})`;
      probList.append(el("li", { className: "prob" }, [
        el("span", { textContent: row.risk }),
        el("span", { className: "prob-bar" }, bar),
        el("span", { className: "prob-val", textContent: `${pct.toFixed(1)}%` }),
      ]));
      requestAnimationFrame(() => requestAnimationFrame(() => (bar.style.width = `${pct}%`)));
    }
    $("#probs").hidden = probRows.length === 0;

    // Tabela de dados
    const tableRows = findings.filter((f) => !/^Probabilidade|^Risco estimado/.test(f.metric));
    $("#findings-block h3").textContent = isPanorama ? "Municípios com maior risco de fogo agora" : "Dados usados na análise";
    const tbody = $("#findings");
    tbody.replaceChildren();
    for (const row of tableRows) {
      const missing = row.value === "Não informado";
      tbody.append(el("tr", {}, [
        el("td", {}, [document.createTextNode(row.metric), el("small", { textContent: row.explanation || "" })]),
        el("td", { className: missing ? "missing" : "", textContent: prettyValue(row) }),
        el("td", {}, el("span", { className: "dot", dataset: { risk: row.risk }, textContent: missing ? "Falta informar" : statusOf(row) })),
      ]));
    }
    $("#findings-block").hidden = tableRows.length === 0;

    // Ações
    const actions = Array.isArray(data.actions) ? data.actions : [];
    $("#actions").replaceChildren(...actions.map((a) => el("li", { textContent: a })));
    $("#actions-block").hidden = actions.length === 0;

    // Fontes e mapa (só na análise com dados oficiais)
    const reg = data.regional;
    $("#sources-block").hidden = !reg;
    $("#map-block").hidden = !reg;
    if (reg) {
      $("#sources-time").textContent = `Dados coletados em ${reg.dados_de}.`;
      $("#sources").replaceChildren(...reg.fontes.map((f) => el("li", {}, el("a", { href: f.url, target: "_blank", rel: "noopener", textContent: f.nome }))));
      showMap(reg, isPanorama);
    }
    $("#reset-btn").hidden = !data.complete;
  }

  function statusOf(row) {
    if (RISK_ORDER.includes(row.risk)) return row.risk;
    const e = row.explanation || "";
    if (/Informado por você/.test(e)) return "Você";
    if (/INPE|INMET|IBGE/.test(e)) return "Oficial";
    if (/Open-Meteo/.test(e)) return "Complementar";
    return "Recebido";
  }

  function prettyValue(row) {
    if (row.metric === "Condição da drenagem") {
      return { "0": "Boa", "0.5": "Regular", "1": "Ruim" }[String(row.value).trim()] || row.value;
    }
    return row.value;
  }

  // ---------- Mapa (Leaflet + OpenStreetMap) ----------
  let leafletPromise = null, map = null, layer = null;
  function loadLeaflet() {
    if (window.L) return Promise.resolve();
    if (!leafletPromise) {
      leafletPromise = new Promise((ok, fail) => {
        document.head.append(el("link", { rel: "stylesheet", href: LEAFLET.css }));
        const s = el("script", { src: LEAFLET.js });
        s.onload = ok;
        s.onerror = () => { leafletPromise = null; fail(new Error("leaflet")); };
        document.head.append(s);
      });
    }
    return leafletPromise;
  }

  function utcToBr(s) {
    if (!s) return "";
    const d = new Date(s.replace(" ", "T") + "Z");
    return isNaN(d) ? s : d.toLocaleString("pt-BR", { timeZone: "America/Fortaleza", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  async function showMap(reg, isPanorama) {
    const n = reg.focos_proximos.length;
    $("#map-caption").textContent = isPanorama
      ? `${reg.focos_48h} focos de calor no Maranhão nas últimas 48 h (INPE). Mapa © colaboradores do OpenStreetMap.`
      : `${n} foco(s) de calor nas últimas 48 h a até 60 km de ${reg.municipio.nome} (INPE). Mapa © colaboradores do OpenStreetMap.`;
    try { await loadLeaflet(); } catch { $("#map").textContent = "Não foi possível carregar o mapa agora."; return; }
    const L = window.L;
    if (!map) {
      map = L.map("map", { scrollWheelZoom: false, attributionControl: true });
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 16, attribution: "© OpenStreetMap",
      }).addTo(map);
    }
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);
    for (const f of reg.focos_proximos) {
      L.circleMarker([f.lat, f.lon], { radius: 6, color: "#7a2410", weight: 1, fillColor: "#ef6a2b", fillOpacity: 0.85 })
        .bindPopup(`<b>Foco de calor</b><br>${f.municipio}<br>${utcToBr(f.data)} · ${f.satelite || ""}`)
        .addTo(layer);
    }
    if (isPanorama) {
      map.fitBounds(MA_BOUNDS);
    } else {
      const c = [reg.municipio.lat, reg.municipio.lon];
      L.circle(c, { radius: 60000, color: "#1e5c86", weight: 1, fill: false, dashArray: "4 6" }).addTo(layer);
      L.marker(c).bindPopup(`<b>${reg.municipio.nome}</b>`).addTo(layer);
      map.setView(c, 8);
    }
    setTimeout(() => map.invalidateSize(), 50);
  }

  // ---------- Relatório em PDF ----------
  const ORDER = ["fire", "flood", "panorama"];

  function updateReport() {
    const done = ORDER.filter((d) => state.reports[d]);
    $("#report-block").hidden = done.length === 0;
    if (!done.length) return;
    $("#report-list").replaceChildren(...done.map((d) => {
      const r = state.reports[d].data;
      return el("li", { className: "ok" }, [
        el("strong", { textContent: cap(DOMAIN_LABEL[d]) }),
        document.createTextNode(` · ${r.location} · risco ${r.overall_risk.toLowerCase()}`),
      ]);
    }));
    const miss = state.chat.cidade ? ["fire", "flood"].find((d) => !state.reports[d]) : null;
    const other = $("#other-btn");
    other.hidden = !miss;
    if (miss) other.textContent = `Analisar também ${DOMAIN_LABEL[miss]}`;
    $("#report-note").textContent = "O relatório traz as análises acima, os dados oficiais usados e as fontes.";
  }

  $("#pdf-btn").addEventListener("click", () => generatePdf());
  $("#other-btn").addEventListener("click", () => {
    const miss = ["fire", "flood"].find((d) => !state.reports[d]);
    if (miss && !state.busy) send(miss === "flood" ? "Ver também o risco de alagamento" : "Ver também o risco de queimadas");
  });

  // O relatório é uma página A4 montada em HTML e impressa pelo próprio navegador
  // ("Salvar como PDF"). Funciona sem bibliotecas externas.
  function generatePdf() {
    if (!Object.keys(state.reports).length) {
      addMessage("bot", "Ainda não tenho uma análise para colocar no relatório. Me diga a sua cidade primeiro.");
      return;
    }
    if (window.OLIVER_PREVIEW) return showReportPreview();
    const old = document.getElementById("report-frame");
    if (old) old.remove();
    const frame = el("iframe", { id: "report-frame", title: "Relatório para impressão" });
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
    document.body.append(frame);
    const doc = frame.contentDocument;
    doc.open(); doc.write(buildReportHtml(state.reports)); doc.close();
    const print = () => { frame.contentWindow.focus(); frame.contentWindow.print(); };
    if (doc.readyState === "complete") setTimeout(print, 250);
    else frame.addEventListener("load", () => setTimeout(print, 250), { once: true });
  }

  function showReportPreview() {
    let modal = document.getElementById("report-modal");
    if (!modal) {
      modal = el("div", { id: "report-modal", className: "report-modal" }, [
        el("div", { className: "report-modal-bar" }, [
          el("p", { textContent: "Prévia do relatório. No site publicado, este botão abre a janela para salvar em PDF." }),
          el("button", { type: "button", className: "ghost-btn", textContent: "Fechar", onclick: () => (modal.hidden = true) }),
        ]),
        el("iframe", { title: "Prévia do relatório" }),
      ]);
      document.body.append(modal);
      modal.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.hidden = true; });
    }
    $("iframe", modal).srcdoc = buildReportHtml(state.reports).replace("</style>", "body{padding:24px;background:#fff;max-width:820px;margin:0 auto}</style>");
    modal.hidden = false;
    $("button", modal).focus();
  }

  function esc(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function buildReportHtml(reports) {
    const order = ORDER.filter((d) => reports[d]);
    const now = new Date();
    const fmt = (d) => d.toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "short" });
    const fileName = `oliver-relatorio-${now.toISOString().slice(0, 10)}`;
    const allSources = new Map();

    const summaryRows = order.map((d) => {
      const r = reports[d].data, p = probs(r);
      const conf = Object.values(p).length ? `${Math.max(...Object.values(p)).toFixed(1)}%` : "–";
      const idx = d === "panorama" ? "–" : `${score(r)}/100`;
      return `<tr><td>${esc(cap(DOMAIN_LABEL[d]))}</td><td>${esc(r.location || "-")}</td>
        <td><b class="lvl ${esc(r.overall_risk)}">Risco ${esc(r.overall_risk.toLowerCase())}</b></td>
        <td class="num">${idx}</td><td class="num">${conf}</td></tr>`;
    }).join("");

    const sections = order.map((d) => {
      const { data, at } = reports[d];
      const reg = data.regional;
      if (reg) for (const f of reg.fontes) allSources.set(f.url, f.nome);
      const lvl = data.overall_risk;
      const rows = (data.findings || []).filter((f) => !/^Probabilidade|^Risco estimado/.test(f.metric));
      const p = probs(data), sc = score(data);
      const focos = reg ? reg.focos_proximos.slice(0, 15) : [];
      const avisos = reg && reg.avisos ? reg.avisos : [];
      return `
      <section class="analysis ${d}">
        <h2>${esc(TITLES[d])}</h2>
        <p class="meta">${esc(data.location || "Local não informado")} · análise feita em ${esc(fmt(at))}${reg ? ` · dados coletados em ${esc(reg.dados_de)}` : ""}</p>
        ${d === "panorama" ? `
          <p class="lead">${esc(data.reply)}</p>
          <h3>Municípios com maior risco de propagação de fogo</h3>
          <table class="data"><thead><tr><th>Posição e município</th><th>Índice</th><th>Focos em 24 h (INPE)</th></tr></thead><tbody>
          ${reg.ranking.map((r, i) => `<tr><td><b>${i + 1}º · ${esc(r.nome)}</b></td><td><b class="lvl ${esc(r.nivel)}">${r.score}/100 · ${esc(r.nivel.toLowerCase())}</b></td><td>${r.focos_24h}</td></tr>`).join("")}
          </tbody></table>` : `
        <div class="verdict">
          <div><span class="label">Classificação</span><b class="big lvl ${esc(lvl)}">Risco ${esc(lvl.toLowerCase())}</b></div>
          <div class="gauge-wrap"><span class="label">Índice de risco (0 a 100)</span>
            <div class="gauge">
              ${RISK_ORDER.map((z) => `<i class="${z === lvl ? "on " + z : ""}"></i>`).join("")}
              <span class="needle" style="left:${Math.min(100, Math.max(0, sc))}%"><b>${sc}</b></span>
            </div>
            <div class="scale"><span>0</span><span>50</span><span>100</span></div>
          </div>
        </div>
        <h3>Probabilidade por classe</h3>
        <table class="probs">${RISK_ORDER.map((k) => `
          <tr><td>${k}</td><td class="num">${(p[k] || 0).toFixed(1)}%</td>
          <td class="barcell"><div class="bar"><i class="${k}" style="width:${p[k] || 0}%"></i></div></td></tr>`).join("")}
        </table>
        <h3>${reg ? "Dados usados e suas fontes" : "Dados informados"}</h3>
        <table class="data"><thead><tr><th>Item</th><th>Valor</th><th>Fonte / observação</th></tr></thead><tbody>
          ${rows.map((r) => `<tr><td><b>${esc(r.metric)}</b></td><td>${esc(prettyValue(r))}</td><td class="obs">${esc(r.explanation)}</td></tr>`).join("")}
        </tbody></table>
        <h3>Conclusão do Oliver</h3>
        <p>${esc(data.reply)}</p>`}
        ${focos.length && d !== "panorama" ? `
          <h3>Focos de calor próximos (até 60 km, últimas 48 h · INPE)</h3>
          <table class="data"><thead><tr><th>Município</th><th>Data e hora</th><th>Satélite</th><th>Coordenadas</th></tr></thead><tbody>
          ${focos.map((f) => `<tr><td>${esc(f.municipio)}</td><td>${esc(utcToBr(f.data))}</td><td>${esc(f.satelite || "-")}</td><td>${f.lat.toFixed(3)}, ${f.lon.toFixed(3)}</td></tr>`).join("")}
          </tbody></table>${reg.focos_proximos.length > 15 ? `<p class="note">Mostrando 15 de ${reg.focos_proximos.length} focos.</p>` : ""}` : ""}
        ${avisos.length ? `<h3>Avisos meteorológicos ativos (INMET)</h3><ul>${avisos.map((a) => `<li><b>${esc(a.evento)}</b>${a.severidade ? ` · ${esc(a.severidade)}` : ""}${a.inicio ? ` · de ${esc(a.inicio)}` : ""}${a.fim ? ` até ${esc(a.fim)}` : ""}</li>`).join("")}</ul>` : ""}
        ${(data.actions || []).length ? `<h3>Recomendações</h3><ul>${data.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      </section>`;
    }).join("");

    const sourcesHtml = allSources.size ? `
      <h2 class="sec">Fontes dos dados</h2>
      <ul>${[...allSources].map(([url, nome]) => `<li>${esc(nome)} · ${esc(url)}</li>`).join("")}</ul>
      <p class="note">Vento e umidade vêm da estação automática do INMET mais próxima (até 80 km) quando ela responde; caso contrário, do Open-Meteo. Chuva das últimas e das próximas 24 horas: Open-Meteo. Dias sem chuva e chuva dos últimos 30 dias: Open-Meteo. Focos de calor e risco de fogo: INPE. Os dados são coletados de hora em hora.</p>` : "";

    return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${fileName}</title>
<style>
  @page { size: A4; margin: 16mm 16mm 18mm; }
  * { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  body { margin: 0; font: 10pt/1.5 "Atkinson Hyperlegible", Arial, Helvetica, sans-serif; color: #1d2b2a; }
  h1, h2, h3 { font-family: "Bricolage Grotesque", Arial, Helvetica, sans-serif; margin: 0; line-height: 1.2; }
  .cover { display: flex; border-radius: 10px; overflow: hidden; color: #fff; margin-bottom: 8mm; }
  .cover > div { flex: 1; padding: 7mm 8mm; }
  .cover .f { background: linear-gradient(120deg, #7a2410, #b23a1a 60%, #ef6a2b); }
  .cover .w { background: linear-gradient(120deg, #3f8fc4, #1e5c86 40%, #0c2f48); text-align: right; display: flex; flex-direction: column; justify-content: flex-end; }
  .cover h1 { font-size: 26pt; font-weight: 800; }
  .cover p { margin: 2mm 0 0; font-size: 11pt; }
  .cover small { font-size: 9pt; opacity: .9; }
  h2.sec { font-size: 13pt; border-bottom: 1px solid #c9d1ca; padding-bottom: 2mm; margin: 6mm 0 3mm; }
  table { width: 100%; border-collapse: collapse; margin: 2mm 0 4mm; }
  th, td { text-align: left; padding: 2mm 2.5mm; border: 1px solid #c9d1ca; vertical-align: top; }
  th { background: #edf0ea; }
  td.num { text-align: right; white-space: nowrap; width: 22mm; }
  .lvl.Baixo { color: #3e7c4f; } .lvl.Moderado { color: #b8820f; } .lvl.Alto { color: #b23a1a; }
  .note { color: #56655f; font-size: 9pt; }
  .lead { font-size: 11pt; }
  .analysis { margin-top: 8mm; page-break-before: always; break-before: page; }
  .analysis:first-of-type { page-break-before: auto; break-before: auto; }
  .analysis h2 { font-size: 16pt; padding-left: 4mm; border-left: 2mm solid; }
  .analysis.fire h2, .analysis.panorama h2 { color: #b23a1a; border-color: #b23a1a; }
  .analysis.flood h2 { color: #1e5c86; border-color: #1e5c86; }
  .meta { color: #56655f; margin: 1.5mm 0 5mm; }
  .verdict { display: flex; gap: 10mm; align-items: flex-end; margin-bottom: 4mm; }
  .verdict > div:first-child { flex: none; }
  .label { display: block; font-size: 8.5pt; color: #56655f; margin-bottom: 1mm; }
  .big { font-size: 17pt; font-family: "Bricolage Grotesque", Arial, sans-serif; }
  .gauge-wrap { flex: 1; }
  .gauge { position: relative; display: flex; gap: 1mm; height: 5mm; margin-top: 8mm; }
  .gauge i { flex: 1; background: #edf0ea; border-radius: 1mm; }
  .gauge i.on.Baixo { background: #3e7c4f; } .gauge i.on.Moderado { background: #b8820f; } .gauge i.on.Alto { background: #b23a1a; }
  .needle { position: absolute; top: -2mm; bottom: -2mm; width: .8mm; background: #1d2b2a; transform: translateX(-50%); }
  .needle b { position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); font-size: 12pt; margin-bottom: .5mm; }
  .scale { display: flex; justify-content: space-between; font-size: 8pt; color: #56655f; margin-top: 1mm; }
  .analysis h3 { font-size: 11pt; margin: 4mm 0 1mm; }
  .probs td:first-child { width: 28mm; }
  .barcell { width: 60%; }
  .bar { height: 3mm; background: #edf0ea; border-radius: 2mm; overflow: hidden; margin-top: 1mm; }
  .bar i { display: block; height: 100%; }
  .bar i.Baixo { background: #3e7c4f; } .bar i.Moderado { background: #b8820f; } .bar i.Alto { background: #b23a1a; }
  .data td:first-child { width: 48mm; }
  .obs { color: #56655f; font-size: 8.5pt; }
  ul { margin: 1mm 0; padding-left: 5mm; }
  tr, .verdict { page-break-inside: avoid; break-inside: avoid; }
  .method { page-break-before: always; break-before: page; }
  .warn { border: 1.5px solid #b23a1a; border-radius: 3mm; padding: 3mm 4mm; margin-top: 4mm; }
  .warn h2 { color: #b23a1a; font-size: 12pt; margin-bottom: 1mm; }
  footer { margin-top: 8mm; color: #56655f; font-size: 8pt; border-top: 1px solid #c9d1ca; padding-top: 2mm; }
</style></head><body>
  <div class="cover">
    <div class="f"><h1>Oliver</h1><p>Relatório de risco de queimadas<br>e alagamento · Maranhão</p></div>
    <div class="w"><small>Gerado em</small><b>${esc(fmt(now))}</b><small>${order.length} ${order.length > 1 ? "análises" : "análise"}</small></div>
  </div>

  <h2 class="sec">Resumo</h2>
  <table><thead><tr><th>Análise</th><th>Local</th><th>Classificação</th><th>Índice</th><th>Confiança</th></tr></thead>
  <tbody>${summaryRows}</tbody></table>

  ${sections}

  <section class="method">
    ${sourcesHtml}
    <h2 class="sec">Como o Oliver calcula</h2>
    <p>O Oliver usa duas redes neurais do tipo perceptron multicamadas (MLP), uma para cada risco. Cada rede tem uma camada oculta com 10 neurônios (ativação tanh) e uma saída softmax com três classes: baixo, moderado e alto.</p>
    <p><b>Queimadas:</b> velocidade do vento, umidade relativa do ar, secura da vegetação e declividade do terreno. A secura é o maior valor entre duas estimativas: dias seguidos com menos de 5 mm de chuva (0 dia = 10 %, 45 dias ou mais = 100 %) e chuva dos últimos 30 dias (0 mm = 100 %, 150 mm ou mais = 0 %). A declividade é estimada pela elevação em torno da sede do município.<br>
    <b>Alagamento:</b> chuva das últimas 24 horas, chuva prevista para as próximas 24 horas, proximidade de rio ou córrego, se a rua costuma alagar (drenagem) e o tipo de imóvel. As três últimas vêm das respostas da pessoa.</p>
    <p>O índice de 0 a 100 combina as probabilidades: 100 × (0,5 × P(moderado) + P(alto)). A classificação é a classe com maior probabilidade, e a confiança é o valor dessa probabilidade.</p>
    <div class="warn">
      <h2>Aviso importante</h2>
      <p>Protótipo acadêmico (TCC). As redes neurais foram treinadas com exemplos sintéticos e usam dados públicos do momento da coleta. O resultado é uma triagem e não substitui os alertas da Defesa Civil, do INPE, do INMET ou do Cemaden. Em emergência, ligue 193 (Bombeiros) ou 199 (Defesa Civil).</p>
    </div>
    <footer>Oliver · Relatório de risco de queimadas e alagamento · protótipo acadêmico</footer>
  </section>
</body></html>`;
  }

  function probs(data) {
    const out = {};
    for (const f of data.findings || []) {
      const m = /^Probabilidade · (.+)$/.exec(f.metric);
      if (m) out[m[1]] = parseFloat(String(f.value).replace(",", ".")) || 0;
    }
    return out;
  }
  function score(data) {
    const r = (data.findings || []).find((f) => /^Risco estimado/.test(f.metric));
    return r ? parseInt(r.value, 10) : 0;
  }
  function cap(s) { return s.charAt(0).toUpperCase() + s.slice(1); }

  $("#reset-btn").addEventListener("click", () => {
    if (state.busy) return;
    state.chat = {};
    state.history = [];
    state.reports = {};
    clearResult();
    updateReport();
    $$(".data-form").forEach((f) => f.reset());
    addMessage("bot", "Pronto, comecei uma nova análise. Qual cidade do Maranhão você quer ver?", quickButtons(["Como está o Maranhão hoje?"]));
  });

  // ---------- Conta ----------
  fetch("/api/auth/me").then((r) => (r.ok ? r.json() : null)).then((d) => {
    if (!d || !d.user) return;
    $("#account-name").textContent = `Olá, ${d.user.name.split(" ")[0]}`;
    $("#account").hidden = false;
  }).catch(() => {});
  $("#logout-btn").addEventListener("click", async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
    location.href = LOGIN_PAGE;
  });

  // ---------- Início ----------
  setSim("fire");
  clearResult();
  addMessage(
    "bot",
    "Oi, eu sou o Oliver. Me diga a sua cidade no Maranhão e eu busco os dados do INPE e do INMET para calcular o risco de queimadas ou de alagamento. No fim, você pode baixar um relatório em PDF.",
    quickButtons(["Risco de queimadas na minha cidade", "Risco de alagamento no meu imóvel", "Como está o Maranhão hoje?"])
  );
})();
