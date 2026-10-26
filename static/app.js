/* Oliver · front-end
 * Conversa com o backend em POST /api/oliver enviando { message, history, domain }.
 * O backend devolve { reply, overall_risk, findings, actions, domain, complete, location }.
 */
(() => {
  "use strict";

  const API_URL = window.OLIVER_API || "/api/oliver";
  const LOGIN_PAGE = window.OLIVER_LOGIN_PAGE || "/";

  const EXAMPLES = {
    fire: "Localização: Chapada dos Veadeiros; fogo ativo: sim; vento: 30 km/h; direção do vento: norte; umidade: 35%; secura da vegetação: 70%; declividade: 20%.",
    flood: "Localização: Centro de São Luís; chuva acumulada: 60 mm; chuva prevista: 40 mm; distância do rio: 500 m; drenagem: ruim; piso vulnerável: térreo.",
  };
  const DOMAIN_LABEL = { fire: "propagação de fogo", flood: "alagamento predial" };
  const RISK_ORDER = ["Baixo", "Moderado", "Alto"];

  const state = { domain: "", history: [], busy: false, reports: {} };

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
      el("span", { className: "visually-hidden", textContent: "Oliver está analisando" }),
    ]);
    messages.append(li);
    messages.scrollTop = messages.scrollHeight;
    return li;
  }

  function quickButtons(items) {
    const box = el("div", { className: "quick" });
    for (const { label, onClick } of items) {
      box.append(el("button", { type: "button", textContent: label, onclick: onClick }));
    }
    return box;
  }

  // ---------- Comunicação com o backend ----------
  async function callOliver(message) {
    const payload = { message, history: state.history, domain: state.domain || "auto" };
    let res;
    try {
      res = await fetch(API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch {
      const err = new Error("offline");
      err.offline = true;
      throw err;
    }
    if (res.status === 401) { location.href = LOGIN_PAGE; throw new Error("Sua sessão expirou. Entre novamente."); }
    if (res.status === 404 || res.status === 405) { const e = new Error("offline"); e.offline = true; throw e; }
    let data = null;
    try { data = await res.json(); } catch { /* resposta sem JSON */ }
    if (!res.ok || !data || data.error) {
      throw new Error((data && data.error) || `O servidor respondeu com erro ${res.status}.`);
    }
    return data;
  }

  async function send(message, { showInChat = true, resetHistory = false } = {}) {
    message = message.trim();
    if (!message || state.busy) return;
    if (resetHistory) state.history = [];
    setBusy(true);
    if (showInChat) addMessage("user", message);
    const typing = showTyping();
    try {
      const data = await callOliver(message);
      typing.remove();
      state.history.push({ role: "user", text: message }, { role: "assistant", text: data.reply });
      if (data.domain && data.domain !== state.domain) setDomain(data.domain, { announce: false });
      if (data.complete) state.reports[data.domain] = { data, at: new Date() };
      addMessage("bot", data.reply, data.complete ? reportQuickButtons() : null);
      renderResult(data);
      updateReport();
      // Depois de uma análise completa, a próxima mensagem começa do zero.
      if (data.complete) {
        state.history = [];
        // No celular o resultado fica abaixo do chat: rola até ele.
        if (window.matchMedia("(max-width: 900px)").matches) {
          $(".result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
        }
      }
    } catch (err) {
      typing.remove();
      if (!err.offline) console.error(err);
      addError(err.offline
        ? "O servidor do Oliver não está rodando. Abra o terminal na pasta do projeto, rode python app.py e acesse http://127.0.0.1:5000 no navegador."
        : err.message);
    } finally {
      setBusy(false);
    }
  }

  function setBusy(busy) {
    state.busy = busy;
    sendBtn.disabled = busy;
    $$(".primary-btn").forEach((b) => (b.disabled = busy));
  }

  // ---------- Cenário ----------
  function setDomain(domain, { announce = true } = {}) {
    state.domain = domain;
    document.body.dataset.domain = domain;
    $$(".scenario-btn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.domain === domain)));
    $$(".data-form").forEach((f) => (f.hidden = f.dataset.domain !== domain));
    $("#form-empty").hidden = Boolean(domain);
    if (announce) {
      state.history = [];
      clearResult();
      send(`Quero analisar ${DOMAIN_LABEL[domain]}.`, { showInChat: true }).then(() => {
        const last = messages.lastElementChild;
        if (last && last.classList.contains("bot")) {
          last.append(quickButtons([
            { label: "Preencher com dados de exemplo", onClick: () => send(EXAMPLES[domain]) },
            { label: "Usar o formulário", onClick: () => selectTab("form") },
          ]));
        }
      });
    }
  }

  $$(".scenario-btn").forEach((btn) =>
    btn.addEventListener("click", () => { if (!state.busy) setDomain(btn.dataset.domain); })
  );

  // ---------- Abas ----------
  function selectTab(which) {
    const isChat = which === "chat";
    $("#tab-chat").setAttribute("aria-selected", String(isChat));
    $("#tab-form").setAttribute("aria-selected", String(!isChat));
    $("#pane-chat").hidden = !isChat;
    $("#pane-form").hidden = isChat;
    (isChat ? chatInput : $("#pane-form input, #pane-form select"))?.focus();
  }
  $("#tab-chat").addEventListener("click", () => selectTab("chat"));
  $("#tab-form").addEventListener("click", () => selectTab("form"));
  $(".mode-switch").addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      selectTab($("#tab-chat").getAttribute("aria-selected") === "true" ? "form" : "chat");
      $(`#tab-${$("#tab-chat").getAttribute("aria-selected") === "true" ? "chat" : "form"}`).focus();
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

  // ---------- Formulários estruturados ----------
  // Por enquanto o formulário monta uma mensagem no formato que o parser do backend
  // já entende. Quando existir um endpoint com campos estruturados, troque aqui.
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
      values.loc = values.loc.replace(/[;.!?\n]/g, " ").trim(); // evita cortar o nome do local
      send(BUILDERS[form.dataset.domain](values), { resetHistory: true });
    });
    form.addEventListener("input", (e) => e.target.removeAttribute("aria-invalid"));
  });

  // ---------- Resultado ----------
  function clearResult() {
    $("#result-title").textContent = "Nenhuma análise ainda";
    setBadge("", "Aguardando cenário");
    setGauge(null);
    $("#probs").hidden = true;
    $("#findings-block").hidden = true;
    $("#actions-block").hidden = true;
    $("#reset-btn").hidden = true;
  }

  function setBadge(risk, text) {
    const badge = $("#risk-badge");
    badge.dataset.risk = RISK_ORDER.includes(risk) ? risk : "";
    badge.textContent = RISK_ORDER.includes(risk) ? `Risco ${risk.toLowerCase()}` : text;
  }

  function setGauge(score, level) {
    const gauge = $("#gauge");
    const needle = $("#gauge-needle");
    $$(".zone", gauge).forEach((z) => z.classList.toggle("on", z.dataset.zone === level));
    if (score == null) {
      gauge.classList.remove("has-value");
      needle.style.left = "0%";
      $("#gauge-value").textContent = "–";
      $("#gauge-caption").textContent = "O índice de 0 a 100 aparece aqui quando todos os dados forem reunidos.";
      return;
    }
    gauge.classList.add("has-value");
    needle.style.left = `${Math.max(0, Math.min(100, score))}%`;
    $("#gauge-value").textContent = score;
    $("#gauge-caption").textContent = "Índice demonstrativo calculado pela rede neural a partir dos dados informados.";
  }

  function renderResult(data) {
    const findings = Array.isArray(data.findings) ? data.findings : [];
    const label = DOMAIN_LABEL[data.domain] || "análise";

    $("#result-title").textContent = data.complete
      ? `Risco de ${label}${data.location ? " · " + data.location : ""}`
      : data.domain ? `Coletando dados · ${label}` : "Nenhuma análise ainda";
    setBadge(data.overall_risk, data.overall_risk || "Aguardando");

    const scoreRow = findings.find((f) => /^Risco estimado/.test(f.metric));
    const score = scoreRow ? parseInt(String(scoreRow.value), 10) : null;
    setGauge(Number.isFinite(score) ? score : null, data.overall_risk);

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
    const tbody = $("#findings");
    tbody.replaceChildren();
    for (const row of tableRows) {
      const missing = row.value === "Não informado";
      const status = missing ? "Falta informar"
        : RISK_ORDER.includes(row.risk) ? row.risk
        : "Recebido";
      tbody.append(el("tr", {}, [
        el("td", {}, [document.createTextNode(row.metric), el("small", { textContent: row.explanation || "" })]),
        el("td", { className: missing ? "missing" : "", textContent: prettyValue(row) }),
        el("td", {}, el("span", { className: "dot", dataset: { risk: row.risk }, textContent: status })),
      ]));
    }
    $("#findings-block").hidden = tableRows.length === 0;

    // Ações
    const actions = Array.isArray(data.actions) ? data.actions : [];
    $("#actions").replaceChildren(...actions.map((a) => el("li", { textContent: a })));
    $("#actions-block").hidden = actions.length === 0;

    $("#reset-btn").hidden = !data.domain;
  }

  // Valores que o backend devolve como número, mas que têm nome para o usuário.
  function prettyValue(row) {
    if (row.metric === "Condição da drenagem") {
      return { "0": "Boa", "0.5": "Regular", "1": "Ruim" }[String(row.value).trim()] || row.value;
    }
    return row.value;
  }

  // ---------- Relatório em PDF ----------
  const OTHER = { fire: "flood", flood: "fire" };

  function missingDomain() {
    return ["fire", "flood"].find((d) => !state.reports[d]);
  }

  function reportQuickButtons() {
    const items = [{ label: "Gerar relatório em PDF", onClick: () => generatePdf() }];
    const miss = missingDomain();
    if (miss) items.push({ label: `Analisar também ${DOMAIN_LABEL[miss]}`, onClick: () => setDomain(miss) });
    return quickButtons(items);
  }

  function updateReport() {
    const done = ["fire", "flood"].filter((d) => state.reports[d]);
    $("#report-block").hidden = done.length === 0;
    if (!done.length) return;
    const list = $("#report-list");
    list.replaceChildren();
    for (const d of ["fire", "flood"]) {
      const r = state.reports[d];
      list.append(el("li", { className: r ? "ok" : "todo" }, [
        el("strong", { textContent: DOMAIN_LABEL[d].replace(/^./, (c) => c.toUpperCase()) }),
        document.createTextNode(r ? ` · ${r.data.location} · risco ${r.data.overall_risk.toLowerCase()}` : " · ainda não analisado"),
      ]));
    }
    const miss = missingDomain();
    const other = $("#other-btn");
    other.hidden = !miss;
    if (miss) other.textContent = `Analisar também ${DOMAIN_LABEL[miss]}`;
    $("#report-note").textContent = miss
      ? "Você já pode gerar o PDF. Para um relatório completo, faça também a outra análise."
      : "As duas análises estão prontas para o relatório.";
  }

  $("#pdf-btn").addEventListener("click", () => generatePdf());
  $("#other-btn").addEventListener("click", () => { const m = missingDomain(); if (m && !state.busy) setDomain(m); });

  // O relatório é uma página A4 montada em HTML e impressa pelo próprio navegador
  // ("Salvar como PDF"). Funciona offline e não depende de bibliotecas externas.
  function generatePdf() {
    if (!Object.keys(state.reports).length) return;
    const old = document.getElementById("report-frame");
    if (old) old.remove();
    const frame = el("iframe", { id: "report-frame", title: "Relatório para impressão" });
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;visibility:hidden";
    if (window.OLIVER_PREVIEW) return showReportPreview();
    document.body.append(frame);
    const doc = frame.contentDocument;
    doc.open(); doc.write(buildReportHtml(state.reports)); doc.close();
    const print = () => { frame.contentWindow.focus(); frame.contentWindow.print(); };
    if (doc.readyState === "complete") setTimeout(print, 250);
    else frame.addEventListener("load", () => setTimeout(print, 250), { once: true });
  }

  // Na pré-visualização a janela de impressão não abre: mostra o relatório na tela.
  function showReportPreview() {
    let modal = document.getElementById("report-modal");
    if (!modal) {
      modal = el("div", { id: "report-modal", className: "report-modal" }, [
        el("div", { className: "report-modal-bar" }, [
          el("p", { textContent: "Prévia do relatório. Rodando o projeto (python app.py), este botão abre a janela para salvar em PDF." }),
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
    const order = ["fire", "flood"].filter((d) => reports[d]);
    const now = new Date();
    const fmt = (d) => d.toLocaleString("pt-BR", { dateStyle: "long", timeStyle: "short" });
    const fileName = `oliver-relatorio-${now.toISOString().slice(0, 10)}`;

    const summaryRows = order.map((d) => {
      const r = reports[d].data, p = probs(r);
      return `<tr><td>${esc(cap(DOMAIN_LABEL[d]))}</td><td>${esc(r.location || "-")}</td>
        <td><b class="lvl ${esc(r.overall_risk)}">Risco ${esc(r.overall_risk.toLowerCase())}</b></td>
        <td class="num">${score(r)}/100</td><td class="num">${Math.max(...Object.values(p)).toFixed(1)}%</td></tr>`;
    }).join("");

    const sections = order.map((d) => {
      const { data, at } = reports[d];
      const sc = score(data), p = probs(data), lvl = data.overall_risk;
      const rows = (data.findings || []).filter((f) => !/^Probabilidade|^Risco estimado/.test(f.metric));
      return `
      <section class="analysis ${d}">
        <h2>Análise de ${esc(DOMAIN_LABEL[d])}</h2>
        <p class="meta">${esc(data.location || "Local não informado")} · ${esc(fmt(at))}</p>
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
        <h3>Dados informados</h3>
        <table class="data"><thead><tr><th>Item</th><th>Valor</th><th>Observação</th></tr></thead><tbody>
          ${rows.map((r) => `<tr><td><b>${esc(r.metric)}</b></td><td>${esc(prettyValue(r))}</td><td class="obs">${esc(r.explanation)}</td></tr>`).join("")}
        </tbody></table>
        <h3>Conclusão do Oliver</h3>
        <p>${esc(data.reply)}</p>
        ${(data.actions || []).length ? `<h3>Recomendações</h3><ul>${data.actions.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}
      </section>`;
    }).join("");

    const missingNote = order.length < 2
      ? `<p class="note">Este relatório inclui apenas a análise de ${esc(DOMAIN_LABEL[order[0]])}. A análise de ${esc(DOMAIN_LABEL[OTHER[order[0]]])} não foi realizada.</p>`
      : "";

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
  .analysis { margin-top: 8mm; page-break-before: always; break-before: page; }
  .analysis:first-of-type { page-break-before: auto; break-before: auto; }
  .analysis h2 { font-size: 16pt; padding-left: 4mm; border-left: 2mm solid; }
  .analysis.fire h2 { color: #b23a1a; border-color: #b23a1a; }
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
  .data td:first-child { width: 48mm; } .data td:nth-child(2) { width: 38mm; }
  .obs { color: #56655f; font-size: 8.5pt; }
  ul { margin: 1mm 0; padding-left: 5mm; }
  tr, .verdict { page-break-inside: avoid; break-inside: avoid; }
  .method { page-break-before: always; break-before: page; }
  .warn { border: 1.5px solid #b23a1a; border-radius: 3mm; padding: 3mm 4mm; margin-top: 4mm; }
  .warn h2 { color: #b23a1a; font-size: 12pt; margin-bottom: 1mm; }
  footer { margin-top: 8mm; color: #56655f; font-size: 8pt; border-top: 1px solid #c9d1ca; padding-top: 2mm; }
</style></head><body>
  <div class="cover">
    <div class="f"><h1>Oliver</h1><p>Relatório de triagem de risco<br>fogo e alagamento</p></div>
    <div class="w"><small>Gerado em</small><b>${esc(fmt(now))}</b><small>${order.length} ${order.length > 1 ? "análises" : "análise"}</small></div>
  </div>

  <h2 class="sec">Resumo</h2>
  <table><thead><tr><th>Cenário</th><th>Local</th><th>Classificação</th><th>Índice</th><th>Confiança</th></tr></thead>
  <tbody>${summaryRows}</tbody></table>
  ${missingNote}

  ${sections}

  <section class="method">
    <h2 class="sec">Como o Oliver calcula</h2>
    <p>O Oliver usa duas redes neurais do tipo perceptron multicamadas (MLP), uma para cada cenário. Cada rede tem uma camada oculta com 10 neurônios (ativação tanh) e uma saída softmax com três classes: baixo, moderado e alto.</p>
    <p><b>Módulo de fogo:</b> velocidade do vento, umidade relativa, secura da vegetação e declividade, normalizadas entre 0 e 1.<br>
    <b>Módulo de alagamento:</b> chuva acumulada e prevista em 24 h (até 200 mm), proximidade de rio ou córrego (até 5 km), condição da drenagem e vulnerabilidade do piso.</p>
    <p>O índice de 0 a 100 combina as probabilidades: 100 × (0,5 × P(moderado) + P(alto)). A classificação é a classe com maior probabilidade, e a confiança é o valor dessa probabilidade.</p>
    <div class="warn">
      <h2>Aviso importante</h2>
      <p>Protótipo acadêmico (TCC). As redes foram treinadas com 1.400 exemplos sintéticos por cenário, e o resultado depende apenas dos dados informados: não há consulta a satélites, estações meteorológicas, rios ou mapas em tempo real. Este relatório não substitui alertas da Defesa Civil, do INPE, do INMET ou do Cemaden. Em emergência, ligue 193 (Bombeiros) ou 199 (Defesa Civil).</p>
    </div>
    <footer>Oliver · Relatório de triagem de risco · protótipo acadêmico</footer>
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
    state.history = [];
    clearResult();
    $$(".data-form").forEach((f) => f.reset());
    addMessage("bot", `Pronto, comecei uma nova análise de ${DOMAIN_LABEL[state.domain] || "risco"}. Envie os dados quando quiser.`);
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
  addMessage(
    "bot",
    "Oi, eu sou o Oliver. Posso estimar o risco de propagação de um foco de fogo ou o risco de alagamento de um prédio. Qual cenário você quer avaliar?",
    quickButtons([
      { label: "Propagação de fogo", onClick: () => setDomain("fire") },
      { label: "Alagamento predial", onClick: () => setDomain("flood") },
    ])
  );
})();
