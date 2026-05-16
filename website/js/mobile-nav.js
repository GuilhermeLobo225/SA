/* ============================================================
   mobile-nav.js — sidebar drawer em mobile.
   Liga o botão de hambúrguer e o overlay; transparente em desktop.
   ============================================================ */
(function () {
  function init() {
    const sidebar = document.querySelector(".sidebar");
    const btn     = document.querySelector(".mobile-menu-btn");
    const overlay = document.querySelector(".sidebar-overlay");
    if (!sidebar || !btn || !overlay) return;

    const open  = () => { sidebar.classList.add("open"); overlay.classList.add("open"); };
    const close = () => { sidebar.classList.remove("open"); overlay.classList.remove("open"); };

    btn.addEventListener("click", () =>
      sidebar.classList.contains("open") ? close() : open()
    );
    overlay.addEventListener("click", close);
    // Fechar ao navegar
    sidebar.querySelectorAll("a").forEach(a => a.addEventListener("click", close));
    // Fechar com ESC
    document.addEventListener("keydown", e => { if (e.key === "Escape") close(); });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
