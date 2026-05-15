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
  }
});

window.addEventListener("beforeunload", () => {
  if (_pollTimer) clearInterval(_pollTimer);
});

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
  /* Limiares definidos no README do projeto (ASHRAE 55, OMS, EN 12464-1) */
  const tiles = [
    {
      icon: "fa-temperature-half",
      label: "Temperatura",
      value: d.temperature?.toFixed(1) ?? "—",
      unit:  "°C",
      alert: d.temperature != null && (d.temperature < 20 || d.temperature > 26)
    },
    {
      icon: "fa-droplet",
      label: "Humidade",
      value: d.humidity != null ? Math.round(d.humidity) : "—",
      unit:  "%",
      alert: d.humidity != null && (d.humidity < 30 || d.humidity > 70)
    },
    {
      icon: "fa-wind",
      label: "Qualidade do ar",
      value: d.air_quality ?? "—",
      unit:  "(MQ-135)",
      alert: d.air_quality != null && d.air_quality > 400
    },
    {
      icon: "fa-lightbulb",
      label: "Iluminância",
      value: d.light ?? "—",
      unit:  "lux",
      alert: d.light != null && d.light < 500
    },
    {
      icon: "fa-volume-low",
      label: "Ruído",
      value: typeof d.noise === "number" ? d.noise : formatNoise(d.noise),
      unit:  typeof d.noise === "number" ? "dB(A)" : "",
      alert: d.noise === "elevado" || (typeof d.noise === "number" && d.noise > 35)
    }
  ];

  document.getElementById("sensor-grid").innerHTML = tiles.map(t => `
    <div class="sensor-tile ${t.alert ? "alert" : ""}">
      <i class="fa-solid ${t.icon}"></i>
      <div class="label">${t.label}</div>
      <div class="value">${t.value}<span class="unit"> ${t.unit}</span></div>
    </div>
  `).join("");
}

function formatNoise(n) {
  return ({ baixo: "Baixo", moderado: "Moderado", elevado: "Elevado" })[n] || n || "—";
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
