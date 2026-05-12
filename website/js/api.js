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

/* Estrutura esperada do endpoint /api/rooms/<id>:
   {
     room_id: "bg",
     count: 7,            // pessoas detetadas pelo YOLOv8 na zona monitorizada
     capacity: 12,        // lugares na zona monitorizada (zona A)
     status: "parcialmente_ocupado",
     comfort: "bom",
     temperature: 22.4,
     humidity: 54,
     air_quality: 320,    // valor analógico bruto do MQ-135
     light: 612,          // lux equivalente
     noise: "baixo",      // ou valor numérico
     timestamp: "2026-05-12T14:32:11Z"
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
  /* Variação pseudo-aleatória mas suave em função do minuto, para a
     demo dar a sensação de tempo real sem saltos bruscos. */
  const minute = new Date().getMinutes();
  const phase  = (minute % 30) / 30;                 // 0 → 1 em meia hora
  const count  = Math.round(3 + 8 * Math.sin(phase * Math.PI));   // varia entre 3 e 11
  const capacity = 12;
  const pct = count / capacity;

  let status = "vazio";
  if (pct >= 0.95) status = "cheio";
  else if (pct >= 0.75) status = "quase_cheio";
  else if (pct >= 0.4) status = "parcialmente_ocupado";
  else if (pct > 0) status = "disponivel";

  return {
    room_id: roomId,
    count,
    capacity,
    status,
    comfort: pct > 0.85 ? "moderado" : "bom",
    temperature: 21.5 + Math.sin(phase * Math.PI * 2) * 1.2,
    humidity:    52 + Math.cos(phase * Math.PI) * 6,
    air_quality: 290 + Math.round(phase * 80),
    light:       540 + Math.round(Math.sin(phase * Math.PI) * 90),
    noise:       pct > 0.7 ? "moderado" : "baixo",
    timestamp:   new Date().toISOString(),
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

/* Expor no escopo global para os scripts de página */
window.SDB = {
  loadLibraries,
  loadBooks,
  fetchRoom,
  statusLabel,
  occupancyTier,
  formatTimestamp,
  REFRESH_INTERVAL,
};
