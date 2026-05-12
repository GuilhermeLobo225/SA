/* ============================================================
   bibliotecas.js — lógica da página principal
   ============================================================
   - Renderiza a lista de bibliotecas a partir de libraries.json
   - Carrega o catálogo (books.csv) e implementa pesquisa + filtro
     por área. A pesquisa é client-side (catálogo pequeno).
   ============================================================ */

let _allBooks   = [];
let _filterArea = "";
let _query      = "";

document.addEventListener("DOMContentLoaded", async () => {
  await renderLibraries();
  await renderCatalog();
});

/* ---------- Bibliotecas ---------- */

async function renderLibraries() {
  const grid = document.getElementById("library-grid");
  try {
    const meta = await SDB.loadLibraries();
    grid.innerHTML = meta.bibliotecas.map(libCardHtml).join("");
    // delegação de clique → ir para detalhe
    grid.addEventListener("click", e => {
      const card = e.target.closest(".library-card");
      if (card) window.location.href = `biblioteca.html?id=${card.dataset.id}`;
    });
  } catch (e) {
    grid.innerHTML = `<div class="empty">Erro a carregar bibliotecas: ${e.message}</div>`;
  }
}

function libCardHtml(b) {
  const monitored = b.sensorizacao;
  const badge = monitored
    ? `<span class="badge monitored"><i class="fa-solid fa-circle"></i> Sensorização ativa</span>`
    : `<span class="badge unmonitored"><i class="fa-solid fa-circle"></i> Sem sensorização</span>`;
  return `
    <article class="library-card ${monitored ? 'monitored' : ''}" data-id="${b.id}">
      <div class="top-band"></div>
      <div class="body">
        <div class="sigla">${b.sigla} · CAMPUS ${b.campus.toUpperCase()}</div>
        <h3>${b.nome}</h3>
        <div class="campus"><i class="fa-solid fa-location-dot"></i>${b.cidade}</div>
        <div class="badge-row">${badge}</div>
        <p class="descricao">${b.descricao}</p>
        <div class="meta">
          <div class="item">
            <span class="label">Lugares</span>
            <span class="val">${b.lugares}</span>
          </div>
          <div class="item">
            <span class="label">Horário letivo</span>
            <span class="val" style="font-size: 11.5px; font-weight: 500;">${b.horario.letivo.split('|')[0].trim()}</span>
          </div>
        </div>
      </div>
    </article>
  `;
}

/* ---------- Catálogo ---------- */

async function renderCatalog() {
  try {
    _allBooks = await SDB.loadBooks();
  } catch (e) {
    document.getElementById("book-results").innerHTML =
      `<div class="empty">Erro a carregar catálogo: ${e.message}</div>`;
    return;
  }

  /* Chips de área dinâmicos */
  const areas = [...new Set(_allBooks.map(b => b.area))].sort();
  const chips = document.getElementById("area-filters");
  areas.forEach(a => {
    const c = document.createElement("button");
    c.className = "filter-chip";
    c.dataset.area = a;
    c.textContent = a;
    chips.appendChild(c);
  });
  chips.addEventListener("click", e => {
    const chip = e.target.closest(".filter-chip");
    if (!chip) return;
    chips.querySelectorAll(".filter-chip").forEach(x => x.classList.remove("active"));
    chip.classList.add("active");
    _filterArea = chip.dataset.area;
    applyFilter();
  });

  /* Input de pesquisa */
  document.getElementById("search-input").addEventListener("input", e => {
    _query = e.target.value.trim().toLowerCase();
    applyFilter();
  });

  applyFilter();
}

function applyFilter() {
  const filtered = _allBooks.filter(b => {
    if (_filterArea && b.area !== _filterArea) return false;
    if (!_query) return true;
    return (
      b.titulo.toLowerCase().includes(_query) ||
      b.autor.toLowerCase().includes(_query)  ||
      b.cota.toLowerCase().includes(_query)
    );
  });
  renderBookTable(filtered);
  document.getElementById("book-count").textContent =
    `${filtered.length} de ${_allBooks.length} registo(s)`;
}

function renderBookTable(books) {
  const target = document.getElementById("book-results");
  if (books.length === 0) {
    target.innerHTML = `<div class="empty">Sem resultados para os critérios indicados.</div>`;
    return;
  }
  /* Mapa rápido id → sigla para a coluna "Biblioteca" */
  const sigla = window.__libSigla ||= {};
  if (Object.keys(sigla).length === 0) {
    SDB.loadLibraries().then(m =>
      m.bibliotecas.forEach(b => sigla[b.id] = { sigla: b.sigla, nome: b.nome })
    );
  }

  target.innerHTML = `
    <table class="book-table">
      <thead>
        <tr>
          <th>Título</th>
          <th>Autor</th>
          <th class="col-area">Área</th>
          <th>Ano</th>
          <th>Cota</th>
          <th>Biblioteca</th>
          <th>Disponibilidade</th>
        </tr>
      </thead>
      <tbody>
        ${books.map(b => {
          const disp = b.exemplares_disponiveis;
          const tot  = b.exemplares_total;
          let pill = "ok", txt = `${disp} de ${tot}`;
          if (disp === 0) { pill = "out"; txt = `0 de ${tot}`; }
          else if (disp <= 1) { pill = "few"; txt = `${disp} de ${tot}`; }
          const lib = sigla[b.biblioteca_id];
          const libCell = lib
            ? `<a href="biblioteca.html?id=${b.biblioteca_id}" title="${lib.nome}">${lib.sigla}</a>`
            : b.biblioteca_id;
          return `
            <tr>
              <td class="col-titulo">${b.titulo}</td>
              <td class="col-autor">${b.autor}</td>
              <td class="col-area">${b.area}</td>
              <td>${b.ano}</td>
              <td class="col-cota">${b.cota}</td>
              <td class="col-bib">${libCell}</td>
              <td class="col-disp"><span class="pill ${pill}">${txt}</span></td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}
