/* ============================================================
   biblioteca-detalhe.js — lógica da página de detalhe
   ============================================================
   - Lê ?id=… da query string
   - Carrega metadados estáticos da biblioteca
   - Se a biblioteca tem sensorização: desenha a planta da sala
     e arranca polling à API a cada REFRESH_INTERVAL
   - Caso contrário, mostra apenas a ficha informativa
   ============================================================ */

let _meta       = null;
let _libObj     = null;
let _pollTimer  = null;
let _chart       = null;
let _chartTarget = "temperature";
let _chartUnit   = "";       // mantido sempre sincronizado com o último fetch
let _chartTimer  = null;
let _prev       = {};   // últimas leituras para calcular tendência

/* Limiares percentuais (do valor anterior) abaixo dos quais a tendência
   é considerada "estável" — evita setas a tremer com micro-flutuações. */
const TREND_THRESHOLDS = {
  temperature: 0.005,   // 0.5%
  humidity:    0.01,    // 1%
  air_quality: 0.03,    // 3%
  light:       0.05,    // 5%  (LM393 oscila mais)
  noise_db:    0.02,    // 2%
  people:      0,       // qualquer mudança em pessoas é significativa
};

/* Para sinais "inversos" (menor = melhor): se sobe, é PIOR.
   Usado só na cor da seta (semantic), não na direção da seta. */
const INVERSE_SIGNALS = new Set(["air_quality", "light", "noise_db"]);

/* Devolve {arrow, delta, cls} comparando valor atual com leitura anterior. */
function trendOf(key, current) {
  const prev = _prev[key];
  if (current == null || prev == null || isNaN(prev) || isNaN(current)) {
    return { arrow: "→", delta: null, cls: "trend-stable" };
  }
  const delta = current - prev;
  const thr   = (TREND_THRESHOLDS[key] ?? 0.02) * Math.max(Math.abs(prev), 1);
  if (Math.abs(delta) < thr) return { arrow: "→", delta, cls: "trend-stable" };
  const up = delta > 0;
  // Se sinal inverso, "subir" é mau → vermelho mesmo apontando para cima
  const isBad = INVERSE_SIGNALS.has(key) ? up : false;
  return {
    arrow: up ? "↗" : "↘",
    delta,
    cls: isBad ? "trend-bad" : "trend-good",
  };
}

function formatDelta(key, delta) {
  if (delta == null) return "";
  const sign = delta > 0 ? "+" : "";
  if (key === "temperature") return `${sign}${delta.toFixed(1)}°`;
  if (key === "humidity")    return `${sign}${Math.round(delta)}%`;
  if (key === "noise_db")    return `${sign}${delta.toFixed(1)} dB`;
  if (key === "people")      return `${sign}${Math.round(delta)}`;
  return `${sign}${Math.round(delta)}`;
}

document.addEventListener("DOMContentLoaded", async () => {
  const params = new URLSearchParams(window.location.search);
  const id = params.get("id") || "bg";

  try {
    _meta = await SDB.loadLibraries();
  } catch (e) {
    showError(`Erro a carregar metadados: ${e.message}`);
    return;
  }

  _libObj = _meta.bibliotecas.find(b => b.id === id);
  if (!_libObj) {
    showError(`Biblioteca '${id}' não encontrada.`);
    return;
  }

  document.getElementById("crumb-nome").textContent = _libObj.sigla;
  document.title = `${_libObj.nome} — Portal UMinho`;

  renderShell();

  if (_libObj.sensorizacao) {
    await refreshSensorData();
    _pollTimer = setInterval(refreshSensorData, SDB.REFRESH_INTERVAL);

    // Charts: render inicial + refresh ~1 min (mais lento que sensores)
    setupChartTabs();
    await refreshChart();
    _chartTimer = setInterval(refreshChart, 60000);

    // Stats: render inicial + refresh ~1 min
    await refreshStats();
    setInterval(refreshStats, 60000);
  }
});

window.addEventListener("beforeunload", () => {
  if (_pollTimer)  clearInterval(_pollTimer);
  if (_chartTimer) clearInterval(_chartTimer);
});

/* ============================================================
   Charts (histórico + previsão)
   ============================================================ */
function setupChartTabs() {
  const tabs = document.getElementById("chart-target-tabs");
  if (!tabs) return;
  tabs.addEventListener("click", e => {
    const btn = e.target.closest(".chart-tab");
    if (!btn) return;
    tabs.querySelectorAll(".chart-tab").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    _chartTarget = btn.dataset.target;
    refreshChart();
  });
}

async function refreshChart() {
  const roomId = _libObj.api_room_id || _libObj.id;
  const data   = await SDB.fetchHistory(roomId, _chartTarget, 4, 60);

  // Atualiza meta
  const labels = {
    "holt-winters": "Holt-Winters (sazonal)",
    "exponential": "Suavização exponencial",
    "naive":       "Naive (último valor)",
    "n/a":         "Previsão — trabalho futuro",
    "mock-sinusoidal": "Demo (mock)",
  };
  document.getElementById("chart-model").textContent  = labels[data.model] || data.model;
  document.getElementById("chart-source").textContent =
    data._source === "api" ? "Dados ao vivo" : "Modo demo";

  // Mantém a unidade atual no escopo do módulo para os callbacks do tooltip
  // (que se mantêm vivos depois de switchar de tab sem recriar o chart).
  _chartUnit = data.unit || "";

  // Constrói datasets — uma linha sólida (histórico) e uma tracejada (forecast)
  const histPts = data.history.map(p  => ({ x: new Date(p.t), y: p.v }));
  const fcPts   = data.forecast.map(p => ({ x: new Date(p.t), y: p.v }));

  // Conecta visualmente as duas linhas no ponto "agora"
  if (histPts.length && fcPts.length) {
    fcPts.unshift({ x: histPts[histPts.length - 1].x, y: histPts[histPts.length - 1].y });
  }

  const datasets = [
    {
      label: "Histórico",
      data: histPts,
      borderColor: "#A8001F",
      backgroundColor: "rgba(168, 0, 31, .08)",
      borderWidth: 2,
      tension: 0.25,
      pointRadius: 0,
      fill: true,
    },
  ];
  if (fcPts.length > 0) {
    datasets.push({
      label: "Previsão (próxima hora)",
      data: fcPts,
      borderColor: "#005A9C",
      backgroundColor: "rgba(0, 90, 156, .05)",
      borderWidth: 2,
      borderDash: [6, 4],
      tension: 0.25,
      pointRadius: 0,
      fill: false,
    });
  }

  if (_chart) {
    _chart.data.datasets = datasets;
    _chart.options.scales.y.title.text = `${prettyTarget(_chartTarget)} (${_chartUnit})`;
    _chart.update("none");
    return;
  }

  const ctx = document.getElementById("history-chart").getContext("2d");
  _chart = new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12, padding: 12 } },
        tooltip: {
          callbacks: {
            title: items => new Date(items[0].parsed.x).toLocaleTimeString("pt-PT"),
            // Usa a unidade ATUAL (módulo) — atualiza ao trocar de tab.
            label: it => `${it.dataset.label}: ${it.parsed.y.toFixed(1)} ${_chartUnit}`,
          },
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "minute", tooltipFormat: "HH:mm", displayFormats: { minute: "HH:mm" } },
          ticks: { maxRotation: 0, autoSkipPadding: 16 },
          grid: { color: "rgba(0,0,0,.06)" },
        },
        y: {
          title: { display: true, text: `${prettyTarget(_chartTarget)} (${_chartUnit})` },
          grid: { color: "rgba(0,0,0,.06)" },
        },
      },
    },
  });
}

function prettyTarget(t) {
  return ({
    temperature: "Temperatura",
    humidity:    "Humidade",
    air_quality: "Qualidade do ar",
    light:       "Iluminância",
    noise_db:    "Ruído",
    people:      "Pessoas",
  })[t] || t;
}

/* ============================================================
   Estatísticas do dia — 4 métricas por sensor (média, mediana, máx, mín)
   ============================================================ */
async function refreshStats() {
  const roomId = _libObj.api_room_id || _libObj.id;
  const s      = await SDB.fetchStats(roomId, 24);
  const grid   = document.getElementById("stats-grid");
  if (!grid) return;

  // Para cada categoria, define unidade e métricas (média/mediana/máx/mín).
  // Ocupação tem "Pico" em vez de "Máx." para combinar melhor com a UX.
  const cards = [
    {
      icon: "fa-users",
      label: "Ocupação",
      // Para a ocupação faz mais sentido mostrar a fracção do dia em cada
      // estado (categorias livre/parcial/cheio) — média/mediana de "número de
      // pessoas" não captura bem a experiência da sala.
      rows: [
        { k: "🟢 Livre",   v: s.occupancy?.pct_livre,   unit: "%"      },
        { k: "🟡 Parcial", v: s.occupancy?.pct_parcial, unit: "%"      },
        { k: "🔴 Cheio",   v: s.occupancy?.pct_cheio,   unit: "%"      },
        { k: "Pico",       v: s.occupancy?.peak,        unit: "pessoas"},
      ],
    },
    {
      icon: "fa-temperature-half",
      label: "Temperatura",
      unit:  "°C",
      rows: [
        { k: "Média",   v: s.temperature?.avg    },
        { k: "Mediana", v: s.temperature?.median },
        { k: "Máximo",  v: s.temperature?.max    },
        { k: "Mínimo",  v: s.temperature?.min    },
      ],
    },
    {
      icon: "fa-droplet",
      label: "Humidade",
      unit:  "%",
      rows: [
        { k: "Média",   v: s.humidity?.avg    },
        { k: "Mediana", v: s.humidity?.median },
        { k: "Máximo",  v: s.humidity?.max    },
        { k: "Mínimo",  v: s.humidity?.min    },
      ],
    },
    {
      icon: "fa-wind",
      label: "Qualidade do ar",
      unit:  "ADC",
      rows: [
        { k: "Média",   v: s.air_quality?.avg    },
        { k: "Mediana", v: s.air_quality?.median },
        { k: "Máximo",  v: s.air_quality?.max    },
        { k: "Mínimo",  v: s.air_quality?.min    },
      ],
    },
    {
      icon: "fa-volume-low",
      label: "Ruído",
      unit:  "dB",
      rows: [
        { k: "Média",   v: s.noise_db?.avg    },
        { k: "Mediana", v: s.noise_db?.median },
        { k: "Máximo",  v: s.noise_db?.max    },
        { k: "Mínimo",  v: s.noise_db?.min    },
      ],
    },
  ];

  grid.innerHTML = cards.map(c => `
    <div class="stat-card">
      <div class="stat-card-head">
        <i class="fa-solid ${c.icon}"></i>
        <div class="stat-card-title">${c.label}</div>
      </div>
      <div class="stat-rows">
        ${c.rows.map(r => {
          // Cada linha pode ter sua própria unidade (ex.: ocupação mistura % e
          // "pessoas"); cai para a unidade do card se não vier definida.
          const unit = (r.unit !== undefined) ? r.unit : c.unit;
          return `
            <div class="stat-row">
              <span class="stat-row-key">${r.k}</span>
              <span class="stat-row-value">
                ${r.v != null ? r.v : "—"}<span class="stat-row-unit">${r.v != null && unit ? " " + unit : ""}</span>
              </span>
            </div>
          `;
        }).join("")}
      </div>
    </div>
  `).join("");
}

/* ============================================================
   Render shell — estrutura HTML estática da página
   ============================================================ */
function renderShell() {
  const b = _libObj;
  const content = document.getElementById("detail-content");

  const sensorBlock = b.sensorizacao
    ? renderSensorBlock()
    : `
      <div class="no-sensor-banner">
        <i class="fa-solid fa-circle-info"></i>
        <strong>Sem sensorização disponível.</strong>
        A versão atual do sistema-piloto está instalada apenas na Biblioteca Geral.
        Esta biblioteca está prevista para uma fase futura de implantação.
      </div>
    `;

  content.innerHTML = `
    <div class="page-header">
      <div>
        <div class="page-eyebrow">${b.sigla} · Campus ${b.campus}</div>
        <h1 class="page-title">${b.nome}</h1>
        <p class="page-subtitle">${b.descricao}</p>
      </div>
    </div>

    <div class="detail-grid">

      <!-- Coluna esquerda: planta + sensores OU placeholder -->
      <div>
        ${sensorBlock}
      </div>

      <!-- Coluna direita: ficha da biblioteca -->
      <aside>
        <div class="panel">
          <h2><i class="fa-solid fa-circle-info"></i>Informações</h2>
          <dl class="info-grid">
            <dt>Sigla</dt>             <dd>${b.sigla}</dd>
            <dt>Campus</dt>            <dd>${b.campus} — ${b.cidade}</dd>
            <dt>Morada</dt>            <dd>${b.endereco}</dd>
            <dt>Telefone</dt>          <dd>${b.telefone}</dd>
            <dt>E-mail</dt>            <dd><a href="mailto:${b.email}">${b.email}</a></dd>
            <dt>Lugares totais</dt>    <dd>${b.lugares}</dd>
            <dt>Horário letivo</dt>    <dd>${b.horario.letivo}</dd>
            <dt>Horário de férias</dt> <dd>${b.horario.ferias}</dd>
          </dl>
        </div>

        <div class="panel" style="margin-top: 20px;">
          <h2><i class="fa-solid fa-arrow-left"></i>Voltar</h2>
          <p style="font-size: 13.5px; margin: 0;">
            <a href="index.html">← Lista de bibliotecas</a><br>
            <a href="index.html#catalogo">→ Pesquisar no catálogo</a>
          </p>
        </div>
      </aside>
    </div>
  `;
}

/* ============================================================
   Bloco completo de sensorização (ocupação + planta + sensores)
   ============================================================ */
function renderSensorBlock() {
  return `
    <!-- Cartão "hero" de ocupação -->
    <div class="panel">
      <h2><i class="fa-solid fa-users"></i>Ocupação em tempo real</h2>

      <div class="occupancy-hero">
        <div class="occupancy-ring">
          <svg viewBox="0 0 100 100">
            <circle class="track" cx="50" cy="50" r="42"></circle>
            <circle class="fill"  cx="50" cy="50" r="42"
                    stroke-dasharray="263.89" stroke-dashoffset="263.89" id="ring-fill"></circle>
          </svg>
          <div class="pct" id="ring-pct">—</div>
        </div>
        <div class="occupancy-info">
          <div class="status-line">
            <span class="live-dot" id="live-dot"></span>
            <span id="data-source">a ligar…</span>
          </div>
          <div class="status-name" id="status-name">—</div>
          <div class="seats" id="seats-text">—</div>
          <div class="led-chip" id="led-chip" title="Estado simplificado consumido pelo LED RGB do nó ambiental">
            <span class="led-dot" id="led-dot"></span>
            <span>LED: <strong id="led-state">—</strong></span>
          </div>
        </div>
      </div>

      <div class="last-update">
        Última leitura: <span id="last-update">—</span>
      </div>
    </div>

    <!-- Planta da sala -->
    <div class="panel" style="margin-top: 20px;">
      <h2><i class="fa-solid fa-chair"></i>Disposição da sala — Piso 1</h2>
      <p style="font-size: 13px; color: var(--text-muted); margin: -6px 0 8px;">
        ${_meta.bg_layout.descricao}
      </p>

      <div class="layout-wrap" id="layout-wrap">
        ${_meta.bg_layout.zonas.map(z => zoneHtml(z)).join("")}
      </div>

      <div class="layout-legend">
        <span><span class="legend-swatch" style="background: rgba(168,163,154,.15)"></span>Sem sensor</span>
        <span><span class="legend-swatch" style="background: rgba(47,138,62,.15); border-color: var(--uminho-red);"></span>Monitorizada</span>
        <span><span class="legend-swatch" style="background: rgba(214,162,22,.25); border-color: var(--uminho-red);"></span>Ocupação média</span>
        <span><span class="legend-swatch" style="background: rgba(154,24,24,.32); border-color: var(--uminho-red);"></span>Ocupação alta</span>
      </div>
    </div>

    <!-- Sensores ambientais -->
    <div class="panel" style="margin-top: 20px;">
      <h2><i class="fa-solid fa-temperature-half"></i>Conforto ambiental</h2>
      <p style="font-size: 13px; color: var(--text-muted); margin: -6px 0 12px;">
        Nó ambiental ESP32-S3 com sensores DHT11 (temp./hum.), MQ-135 (qualidade do ar), fotodíodo LM393 (iluminância) e microfone MEMS I2S MSM261S4030H0 (ruído), a transmitir para Firebase a cada 30 s.
      </p>

      <div class="sensor-grid" id="sensor-grid">
        <!-- preenchido por JS -->
      </div>
    </div>

    <!-- Estatísticas do dia -->
    <div class="panel" style="margin-top: 20px;">
      <h2><i class="fa-solid fa-chart-pie"></i>Estatísticas das últimas 24h</h2>
      <p style="font-size: 13px; color: var(--text-muted); margin: -6px 0 12px;">
        Métricas agregadas a partir do histórico do Firebase. Atualiza a cada
        minuto.
      </p>
      <div class="stats-grid" id="stats-grid">
        <div class="loading">A calcular estatísticas…</div>
      </div>
    </div>

    <!-- Histórico + previsão -->
    <div class="panel" style="margin-top: 20px;">
      <h2><i class="fa-solid fa-chart-line"></i>Evolução temporal & previsão</h2>
      <p style="font-size: 13px; color: var(--text-muted); margin: -6px 0 12px;">
        Linha sólida: histórico real recolhido pelos nós. Linha tracejada:
        previsão para a próxima hora, calculada na API a partir do histórico
        (Holt-Winters quando há ≥ 2 dias de dados; suavização exponencial caso
        contrário).
      </p>

      <div class="chart-controls">
        <div class="chart-target-tabs" id="chart-target-tabs">
          <button class="chart-tab active" data-target="temperature">Temperatura</button>
          <button class="chart-tab"        data-target="humidity">Humidade</button>
          <button class="chart-tab"        data-target="air_quality">Qualidade do ar</button>
          <button class="chart-tab"        data-target="noise_db">Ruído</button>
          <button class="chart-tab"        data-target="people">Ocupação</button>
        </div>
        <div class="chart-meta">
          <span id="chart-model">—</span>
          <span class="sep">·</span>
          <span id="chart-source">—</span>
        </div>
      </div>

      <div class="chart-wrap">
        <canvas id="history-chart"></canvas>
      </div>
    </div>
  `;
}

/* HTML de uma zona da planta */
function zoneHtml(z) {
  const cls = z.monitorizada ? "zone monitored" : "zone unmonitored";
  return `
    <div class="${cls}" id="zone-${z.id}" data-lugares="${z.lugares}"
         style="left:${z.x}%; top:${z.y}%; width:${z.w}%; height:${z.h}%;">
      <div>
        <div class="zone-id">${z.id}</div>
        <div class="zone-name">${z.lugares} lug.</div>
      </div>
      ${z.monitorizada ? `<div class="zone-count" id="zone-${z.id}-count">—/${z.lugares}</div>` : ``}
    </div>
  `;
}

/* ============================================================
   Atualização dos dados ao vivo
   ============================================================ */
async function refreshSensorData() {
  const roomId = _libObj.api_room_id || _libObj.id;
  const data   = await SDB.fetchRoom(roomId);
  paintOccupancy(data);
  paintZone(data);
  paintSensors(data);
  paintMeta(data);
}

function paintOccupancy(d) {
  const cap = d.capacity || 1;
  const pct = Math.min(1, d.count / cap);
  const tier = SDB.occupancyTier(pct);

  /* Anel SVG: C = 2π·r = 2π·42 ≈ 263.89 */
  const C = 263.89;
  const ring = document.getElementById("ring-fill");
  ring.style.strokeDashoffset = C * (1 - pct);
  /* cor do anel acompanha o tier */
  const colors = {
    empty: "var(--status-free)",
    low:   "var(--status-low)",
    mid:   "var(--status-mid)",
    high:  "var(--status-high)",
    full:  "var(--status-full)"
  };
  ring.style.stroke = colors[tier];

  document.getElementById("ring-pct").textContent  = `${Math.round(pct * 100)}%`;
  document.getElementById("status-name").textContent = SDB.statusLabel(d.status);
  document.getElementById("seats-text").textContent  = `${d.count} de ${cap} lugares ocupados na zona monitorizada`;

  /* Chip do LED — mostra o estado simplificado (3 níveis) que o firmware lê. */
  const simple = d.status_simple || "—";
  const ledLabel = ({
    livre:   "Livre",
    parcial: "Parcial",
    cheio:   "Cheio",
  })[simple] || "—";
  const ledColors = {
    livre:   "var(--status-free)",
    parcial: "var(--status-mid)",
    cheio:   "var(--status-full)",
  };
  document.getElementById("led-state").textContent = ledLabel;
  document.getElementById("led-dot").style.background = ledColors[simple] || "var(--status-unknown)";
}

function paintZone(d) {
  /* Distribui as pessoas pelas mesas monitorizadas em ordem (preenchimento
     sequencial mesa-a-mesa) — bate certo com a heurística que o detector.py
     usa para classificar livre/parcial/cheio.

     Cor da MESA usa um esquema simples de 3 tiers (alinhado com a legenda
     "Sem sensor · Monitorizada · Ocupação média · Ocupação alta"):
        0 pessoas       → empty (verde)
        1..(cap-1)      → mid   (amarelo)   ← qualquer mesa parcial
        cap (cheia)     → full  (vermelho)
  */
  const cells = document.querySelectorAll(".zone.monitored");
  let remaining = d.count || 0;

  cells.forEach(cell => {
    const localCap   = parseInt(cell.dataset.lugares, 10) || 0;
    const localCount = Math.min(remaining, localCap);
    remaining -= localCount;

    let tier;
    if (localCount <= 0)            tier = "empty";
    else if (localCount >= localCap) tier = "full";
    else                             tier = "mid";

    ["empty","low","mid","high","full"].forEach(t => cell.classList.remove("occ-" + t));
    cell.classList.add("occ-" + tier);

    const countEl = cell.querySelector(".zone-count");
    if (countEl) countEl.textContent = `${localCount}/${localCap}`;
  });
}

function paintSensors(d) {
  /* Privilegia a classe textual da API ("bom"/"moderado"/"mau"/...) para
     decidir alertas; cai para limiares numéricos só quando a classe não existe. */
  const isBadClass = c => ["mau", "elevado", "muito_elevado",
                            "necessita_ventilacao", "insuficiente", "escuro"].includes(c);

  const subFor = (cls, fallback = "") =>
    cls ? `<span class="sublabel">${formatClass(cls)}</span>` : fallback;

  const tiles = [
    {
      key: "temperature",
      icon: "fa-temperature-half",
      label: "Temperatura",
      value: d.temperature != null ? d.temperature.toFixed(1) : "—",
      raw:   d.temperature,
      unit:  "°C",
      sub:   "ASHRAE 55: 20–26",
      alert: d.temperature != null && (d.temperature < 20 || d.temperature > 26),
    },
    {
      key: "humidity",
      icon: "fa-droplet",
      label: "Humidade",
      value: d.humidity != null ? Math.round(d.humidity) : "—",
      raw:   d.humidity,
      unit:  "%",
      sub:   "Confort.: 30–70",
      alert: d.humidity != null && (d.humidity < 30 || d.humidity > 70),
    },
    {
      key: "air_quality",
      icon: "fa-wind",
      label: "Qualidade do ar",
      value: d.air_quality ?? "—",
      raw:   d.air_quality,
      unit:  "ADC (MQ-135)",
      sub:   subFor(d.air_quality_class, "Calibração empírica"),
      alert: isBadClass(d.air_quality_class)
              || (d.air_quality != null && d.air_quality > 2500),
    },
    {
      key: "light",
      icon: "fa-lightbulb",
      label: "Iluminância",
      value: d.light ?? "—",
      raw:   d.light,
      unit:  "ADC (LM393)",
      sub:   subFor(d.light_class, "Menor = mais luz"),
      alert: isBadClass(d.light_class)
              || (d.light != null && d.light > 3500),
    },
    {
      key: "noise_db",
      icon: "fa-volume-low",
      label: "Ruído",
      value: d.noise_db != null ? d.noise_db.toFixed(1)
                                  : (typeof d.noise === "number" ? d.noise : "—"),
      raw:   d.noise_db,
      unit:  "dB rel.",
      sub:   subFor(d.noise, "MSM261 (I2S)"),
      alert: isBadClass(d.noise)
              || (d.noise_db != null && d.noise_db > 55),
    },
    {
      key: "comfort",
      icon: "fa-heart-pulse",
      label: "Conforto global",
      value: d.comfort ? formatClass(d.comfort) : "—",
      unit:  "",
      sub:   "Score ASHRAE + OMS",
      alert: isBadClass(d.comfort),
      isText: true,
    },
  ];

  document.getElementById("sensor-grid").innerHTML = tiles.map(t => {
    const tr = !t.isText && t.raw != null ? trendOf(t.key, t.raw) : null;
    const trendHtml = tr
      ? `<span class="trend ${tr.cls}" title="Δ vs leitura anterior">
            ${tr.arrow}<span class="trend-delta">${formatDelta(t.key, tr.delta)}</span>
         </span>`
      : "";
    return `
      <div class="sensor-tile ${t.alert ? "alert" : ""}">
        <i class="fa-solid ${t.icon}"></i>
        <div class="label">${t.label}${trendHtml}</div>
        <div class="value ${t.isText ? "value-text" : ""}">
          ${t.value}${t.unit ? `<span class="unit"> ${t.unit}</span>` : ""}
        </div>
        ${t.sub ? `<div class="sublabel-row">${t.sub}</div>` : ""}
      </div>
    `;
  }).join("");

  // Memorizar leituras atuais para a próxima comparação
  tiles.forEach(t => { if (!t.isText && t.raw != null) _prev[t.key] = t.raw; });

  // Tendência também na contagem de pessoas (mostrada noutra zona)
  if (d.count != null) _prev.people = d.count;
}

/* "necessita_ventilacao" → "Necessita ventilacao" (cosmético). */
function formatClass(c) {
  if (!c) return "—";
  return c.replace(/_/g, " ")
          .replace(/^\w/, ch => ch.toUpperCase());
}

function paintMeta(d) {
  const dot = document.getElementById("live-dot");
  const src = document.getElementById("data-source");
  if (d._source === "api") {
    dot.classList.remove("stale");
    src.textContent = "Em direto · API local";
  } else {
    dot.classList.add("stale");
    src.textContent = "Modo demo · API offline";
  }
  document.getElementById("last-update").textContent = SDB.formatTimestamp(d.timestamp);
}

/* ============================================================
   Erros
   ============================================================ */
function showError(msg) {
  document.getElementById("detail-content").innerHTML = `
    <div class="page-header"><h1 class="page-title">Erro</h1></div>
    <div class="empty">${msg} · <a href="index.html">Voltar</a></div>
  `;
}
