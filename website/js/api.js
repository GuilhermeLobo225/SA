/* ============================================================
   API.js — camada partilhada de acesso a dados
   ============================================================
   Responsabilidades:
   1. Carregar metadados estáticos (libraries.json, books.csv)
   2. Obter dados ao vivo da API local (processing/api.py em :5000)
      que por sua vez lê do Firebase Realtime Database
   3. Quando a API não está acessível, devolver dados simulados
      para que a página funcione em modo demo
   ============================================================ */

const API_BASE = "http://localhost:5000/api";
const REFRESH_INTERVAL = 15000; // 15 s — alinhado com a frequência de envio dos nós ESP32

/* ---------- Metadados estáticos ---------- */

async function loadLibraries() {
  const res = await fetch("data/libraries.json");
  if (!res.ok) throw new Error("Falha a carregar libraries.json");
  return await res.json();
}

/* Parser CSV simples — suficiente para um catálogo sem aspas/vírgulas dentro de campos */
async function loadBooks() {
  const res = await fetch("data/books.csv");
  if (!res.ok) throw new Error("Falha a carregar books.csv");
  const text = await res.text();
  const lines = text.trim().split(/\r?\n/);
  const header = lines.shift().split(",");
  return lines.map(line => {
    const cells = line.split(",");
    const obj = {};
    header.forEach((h, i) => obj[h] = cells[i]);
    obj.ano = parseInt(obj.ano, 10);
    obj.exemplares_total = parseInt(obj.exemplares_total, 10);
    obj.exemplares_disponiveis = parseInt(obj.exemplares_disponiveis, 10);
    return obj;
  });
}

/* ---------- Dados ao vivo (sensorização) ---------- */

/* Contrato (ver processing/api.py / build_room_payload):
   {
     room_id:           "bg",
     timestamp:         "2026-05-15T14:32:11",

     // Ocupação
     count:             7,                          // alias people
     people:            7,
     capacity:          8,
     tables:            2,
     chairs_total:      8,
     chairs_free:       1,
     occupancy_pct:     87.5,
     status:            "quase_cheio",              // 5 níveis (UX)
     status_simple:     "parcial",                  // 3 níveis (LED)

     // Ambiente — numéricos
     temperature:       22.4,
     humidity:          54,
     air_quality:       720,                        // ADC do MQ-135 (12-bit)
     light:             1100,                       // ADC do LM393 (menor = mais luz)
     light_digital:     0,
     noise_db:          42.7,                       // dB relativo (MSM261)

     // Ambiente — classes textuais
     comfort:           "bom",
     air_quality_class: "bom",
     light_class:       "bom",
     noise:             "baixo"
   }
*/
async function fetchRoom(roomId) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 3000);
    const res = await fetch(`${API_BASE}/rooms/${roomId}`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    data._source = "api";
    return data;
  } catch (e) {
    console.warn(`[api] /rooms/${roomId} indisponível — a usar mock. (${e.message})`);
    return mockRoom(roomId);
  }
}

/* ---------- Mock — usado quando a api.py não está a correr ---------- */

function mockRoom(roomId) {
  /* Variação suave em função do minuto, para a demo parecer "em tempo real"
     sem saltos bruscos. Espelha o contrato real da api.py. */
  const minute = new Date().getMinutes();
  const phase  = (minute % 30) / 30;                          // 0 → 1 em meia hora
  const tables = 2, chairsPerTable = 4;                       // alinhado com config.py
  const capacity = tables * chairsPerTable;                   // 8
  const count    = Math.round(3 + 4 * Math.sin(phase * Math.PI));   // varia entre 3 e 7
  const pct      = count / capacity;

  /* 5 estados (UX) */
  let status = "vazio";
  if (pct >= 0.95) status = "cheio";
  else if (pct >= 0.75) status = "quase_cheio";
  else if (pct >= 0.40) status = "parcialmente_ocupado";
  else if (pct >  0)    status = "disponivel";

  /* 3 estados (LED) — coerente com detector.py: */
  let status_simple = "livre";
  const tablesUsed = Math.ceil(count / chairsPerTable);
  if (count >= capacity)             status_simple = "cheio";
  else if (tablesUsed >= tables)     status_simple = "parcial";

  /* Ambiente — valores realistas que cruzam thresholds para demonstrar alerts */
  const temperature = 21.5 + Math.sin(phase * Math.PI * 2) * 1.2;
  const humidity    = 52   + Math.cos(phase * Math.PI)     * 6;
  const air_quality = 600  + Math.round(phase * 400);              // 600..1000 (MQ-135 ADC)
  const light       = 800  + Math.round(Math.sin(phase * Math.PI) * 1500); // 800..2300 (LM393 ADC)
  const noise_db    = 32   + pct * 25;                              // 32..57 dB rel.

  /* Classificação textual coerente com firmware */
  const air_quality_class = air_quality < 800  ? "bom"
                           : air_quality < 1500 ? "aceitavel"
                           : air_quality < 2500 ? "necessita_ventilacao"
                           : "mau";
  const light_class = light < 2500 ? "adequado"
                     : light < 3500 ? "insuficiente"
                     : "escuro";
  const noise       = noise_db < 35 ? "baixo"
                     : noise_db < 55 ? "moderado"
                     : noise_db < 70 ? "elevado"
                     : "muito_elevado";
  /* Conforto: bom se nada gritar, moderado/mau caso contrário */
  const bads = [air_quality_class, light_class, noise]
                  .filter(c => ["mau","elevado","muito_elevado","necessita_ventilacao","insuficiente","escuro"].includes(c))
                  .length;
  const comfort = bads === 0 ? "bom" : bads === 1 ? "moderado" : "mau";

  return {
    room_id:        roomId,
    timestamp:      new Date().toISOString(),

    // Ocupação
    count, people: count, capacity, tables,
    chairs_total:  capacity,
    chairs_free:   Math.max(0, capacity - count),
    occupancy_pct: Math.round(pct * 1000) / 10,
    status,
    status_simple,

    // Ambiente — numéricos
    temperature,
    humidity,
    air_quality,
    light,
    light_digital: light < 1500 ? 0 : 1,
    noise_db,

    // Ambiente — classes
    comfort,
    air_quality_class,
    light_class,
    noise,

    _source: "mock"
  };
}

/* ---------- Utilitários partilhados ---------- */

function statusLabel(s) {
  return ({
    vazio: "Vazio",
    disponivel: "Disponível",
    parcialmente_ocupado: "Parcialmente ocupado",
    quase_cheio: "Quase cheio",
    cheio: "Cheio",
  })[s] || "—";
}

function occupancyTier(pct) {
  if (pct >= 0.95) return "full";
  if (pct >= 0.75) return "high";
  if (pct >= 0.40) return "mid";
  if (pct >  0)    return "low";
  return "empty";
}

function formatTimestamp(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/* ---------- Série histórica + previsão ---------- */

/* Devolve { target, unit, history: [{t,v}], forecast: [{t,v}], model } */
async function fetchHistory(roomId, target, hours = 4, forecastMinutes = 60) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 8000);
    const url = `${API_BASE}/rooms/${roomId}/history`
              + `?target=${encodeURIComponent(target)}`
              + `&hours=${hours}&forecast_minutes=${forecastMinutes}`;
    const res = await fetch(url, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    data._source = "api";
    return data;
  } catch (e) {
    console.warn(`[api] /rooms/${roomId}/history?target=${target} indisponível — mock. (${e.message})`);
    return mockHistory(target, hours, forecastMinutes);
  }
}

function mockHistory(target, hours, forecastMinutes) {
  const now = new Date();
  const step = 60 * 1000;  // 1 min
  const points = Math.round(hours * 60);
  const history = [];

  const unitMap   = { temperature: "°C", humidity: "%", air_quality: "ADC",
                      light: "ADC", noise_db: "dB rel.", people: "pessoas" };
  const baseMap   = { temperature: 22, humidity: 50, air_quality: 600,
                      light: 1200, noise_db: 35, people: 2 };
  const ampMap    = { temperature: 1.5, humidity: 6, air_quality: 250,
                      light: 600, noise_db: 8, people: 2 };

  const base = baseMap[target] ?? 0;
  const amp  = ampMap[target]  ?? 1;

  for (let i = points; i > 0; i--) {
    const ts = new Date(now.getTime() - i * step);
    const phase = (ts.getMinutes() % 30) / 30;
    const v = base + Math.sin(phase * Math.PI * 2) * amp + (Math.random() - 0.5) * (amp * 0.15);
    history.push({ t: ts.toISOString(), v: Math.max(0, v) });
  }

  const forecast = [];
  if (target !== "people") {
    for (let i = 1; i <= forecastMinutes; i++) {
      const ts = new Date(now.getTime() + i * step);
      const phase = (ts.getMinutes() % 30) / 30;
      const v = base + Math.sin(phase * Math.PI * 2) * amp;
      forecast.push({ t: ts.toISOString(), v });
    }
  }

  return {
    target, unit: unitMap[target] || "",
    hours, history, forecast,
    model: target === "people" ? "n/a" : "mock-sinusoidal",
    _source: "mock",
  };
}

/* ---------- Estatísticas do dia ---------- */
async function fetchStats(roomId, hours = 24) {
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const res = await fetch(`${API_BASE}/rooms/${roomId}/stats?hours=${hours}`, { signal: ctrl.signal });
    clearTimeout(t);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    data._source = "api";
    return data;
  } catch (e) {
    console.warn(`[api] /rooms/${roomId}/stats indisponível — mock. (${e.message})`);
    return mockStats();
  }
}

function mockStats() {
  return {
    hours_window: 24,
    occupancy:   { peak: 4,    min: 0,    avg: 1.6,  median: 1    , pct_livre: 60, pct_parcial: 30, pct_cheio: 10 },
    temperature: { min: 20.4, max: 24.1, avg: 22.3, median: 22.4, hottest_at: null, coldest_at: null },
    humidity:    { min: 38,   max: 56,   avg: 47,   median: 47   },
    air_quality: { min: 80,   max: 420,  avg: 220,  median: 195  },
    noise_db:    { min: 28.5, max: 52.3, avg: 36.1, median: 34.8 },
    samples:     { environment: 0, occupancy: 0 },
    _source: "mock",
  };
}

/* Expor no escopo global para os scripts de página */
window.SDB = {
  loadLibraries,
  loadBooks,
  fetchRoom,
  fetchHistory,
  fetchStats,
  statusLabel,
  occupancyTier,
  formatTimestamp,
  REFRESH_INTERVAL,
};
