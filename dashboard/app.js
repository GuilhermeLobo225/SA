// Configuração — ajustar URL da API
const API_BASE = "http://localhost:5000/api";
const REFRESH_INTERVAL = 15000; // 15 segundos

async function fetchRooms() {
  try {
    const res = await fetch(`${API_BASE}/rooms`);
    if (!res.ok) throw new Error("Erro na API");
    return await res.json();
  } catch (e) {
    console.error("Erro ao obter dados:", e);
    return null;
  }
}

function renderRooms(rooms) {
  const container = document.getElementById("rooms-container");
  const loading = document.getElementById("loading");
  loading.style.display = "none";

  if (!rooms || rooms.length === 0) {
    container.innerHTML = '<p style="text-align:center;color:#999;">Nenhuma sala configurada.</p>';
    return;
  }

  container.innerHTML = rooms.map(room => {
    const pct = room.capacity > 0 ? Math.round((room.count / room.capacity) * 100) : 0;
    const fillClass = pct < 50 ? "fill-low" : pct < 85 ? "fill-medium" : "fill-high";
    const status = room.status || "desconhecido";
    const comfort = room.comfort || "desconhecido";
    const temp = room.temperature != null ? `${room.temperature.toFixed(1)}°C` : "—";
    const noise = room.noise || "—";

    return `
      <div class="room-card">
        <div class="room-header">
          <span class="room-name">📍 ${formatRoomName(room.room_id)}</span>
          <span class="status-badge status-${status}">${formatStatus(status)}</span>
        </div>
        <div class="occupancy-bar">
          <div class="occupancy-fill ${fillClass}" style="width:${pct}%"></div>
        </div>
        <div class="occupancy-text">${room.count} / ${room.capacity} lugares ocupados (${pct}%)</div>
        <div class="env-grid">
          <div class="env-item">
            <div class="env-icon">🌡️</div>
            <div class="env-label">Temperatura</div>
            <div class="env-value">${temp}</div>
          </div>
          <div class="env-item">
            <div class="env-icon">🔊</div>
            <div class="env-label">Ruído</div>
            <div class="env-value">${formatNoise(noise)}</div>
          </div>
          <div class="env-item">
            <div class="env-icon">💨</div>
            <div class="env-label">Qualidade do Ar</div>
            <div class="env-value">—</div>
          </div>
          <div class="env-item">
            <div class="env-icon">💡</div>
            <div class="env-label">Iluminação</div>
            <div class="env-value">—</div>
          </div>
        </div>
        <div class="comfort-indicator comfort-${comfort}">
          Conforto: ${comfort.charAt(0).toUpperCase() + comfort.slice(1)}
        </div>
      </div>
    `;
  }).join("");
}

function formatRoomName(id) {
  return id.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function formatStatus(s) {
  const map = {
    vazio: "Vazio",
    disponivel: "Disponível",
    parcialmente_ocupado: "Parcial",
    quase_cheio: "Quase Cheio",
    cheio: "Cheio",
    desconhecido: "—",
  };
  return map[s] || s;
}

function formatNoise(n) {
  const map = { baixo: "🟢 Baixo", moderado: "🟡 Moderado", elevado: "🔴 Elevado" };
  return map[n] || n;
}

// Init
async function init() {
  const rooms = await fetchRooms();
  renderRooms(rooms);
  setInterval(async () => {
    const r = await fetchRooms();
    if (r) renderRooms(r);
  }, REFRESH_INTERVAL);
}

document.addEventListener("DOMContentLoaded", init);
