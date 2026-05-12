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
  
  if (loading) loading.style.display = "none";

  if (!rooms || rooms.length === 0) {
    container.innerHTML = '<p class="col-span-full text-center text-gray-500 py-10">Nenhuma sala configurada no momento.</p>';
    return;
  }

  container.innerHTML = rooms.map(room => {
    // Lógica original de cálculo
    const pct = room.capacity > 0 ? Math.round((room.count / room.capacity) * 100) : 0;
    
    // Determinar cores dinâmicas baseadas na ocupação
    let themeColor = "green"; // Default baixo
    if (pct >= 50 && pct < 85) themeColor = "yellow";
    if (pct >= 85) themeColor = "red";

    const status = room.status || "desconhecido";
    const comfort = room.comfort || "desconhecido";
    const temp = room.temperature != null ? `${room.temperature.toFixed(1)} °C` : "—";
    const noise = room.noise || "—";
    
    // Configurar as cores do conforto
    let comfortBg = "bg-gray-100 text-gray-800";
    if (comfort === "bom") comfortBg = "bg-green-100 text-green-800";
    if (comfort === "moderado") comfortBg = "bg-orange-100 text-orange-800";
    if (comfort === "mau") comfortBg = "bg-red-100 text-red-800";

    // Retorna o HTML estruturado com Tailwind
    return `
      <div class="bg-white rounded shadow p-6 border-t-4 border-${themeColor}-500 transition hover:-translate-y-1">
        
        <div class="flex justify-between items-start mb-4">
          <div>
            <h2 class="text-xl font-bold text-gray-800">📍 ${formatRoomName(room.room_id)}</h2>
          </div>
          <div class="bg-${themeColor}-100 text-${themeColor}-800 px-3 py-1 rounded-full text-sm font-semibold flex items-center shadow-sm">
             ${formatStatus(status)}
          </div>
        </div>

        <div class="w-full bg-gray-200 rounded-full h-3 mb-2 overflow-hidden">
          <div class="bg-${themeColor}-500 h-3 rounded-full transition-all duration-500 ease-out" style="width: ${pct}%"></div>
        </div>
        <div class="text-center text-sm text-gray-500 mb-6 font-medium">
          ${room.count} / ${room.capacity} lugares ocupados (${pct}%)
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
          <div class="bg-gray-50 rounded-lg p-3 text-center border border-gray-100">
            <i class="fa-solid fa-temperature-half text-gray-400 text-xl mb-1"></i>
            <p class="text-[10px] uppercase tracking-wide text-gray-500 font-bold">Temperatura</p>
            <p class="font-bold text-gray-800 mt-1">${temp}</p>
          </div>
          <div class="bg-gray-50 rounded-lg p-3 text-center border border-gray-100">
            <i class="fa-solid fa-volume-low text-yellow-500 text-xl mb-1"></i>
            <p class="text-[10px] uppercase tracking-wide text-gray-500 font-bold">Ruído</p>
            <p class="font-bold text-gray-800 mt-1 text-sm">${formatNoise(noise)}</p>
          </div>
          <div class="bg-gray-50 rounded-lg p-3 text-center border border-gray-100">
            <i class="fa-solid fa-wind text-green-500 text-xl mb-1"></i>
            <p class="text-[10px] uppercase tracking-wide text-gray-500 font-bold">Qualidade Ar</p>
            <p class="font-bold text-gray-800 mt-1 text-sm">—</p>
          </div>
          <div class="bg-gray-50 rounded-lg p-3 text-center border border-gray-100">
            <i class="fa-solid fa-lightbulb text-orange-400 text-xl mb-1"></i>
            <p class="text-[10px] uppercase tracking-wide text-gray-500 font-bold">Iluminação</p>
            <p class="font-bold text-gray-800 mt-1 text-sm">—</p>
          </div>
        </div>

        <div class="mt-5 text-center p-2 rounded-lg font-bold text-sm ${comfortBg}">
          Índice de Conforto: ${comfort.charAt(0).toUpperCase() + comfort.slice(1)}
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
  const map = { baixo: "🟢 Baixo", moderado: "🟡 Mod.", elevado: "🔴 Elev." };
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