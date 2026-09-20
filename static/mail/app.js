"use strict";
document.addEventListener("DOMContentLoaded", function () {
  const toggle = document.querySelector("[data-menu-toggle]");
  const sidebar = document.getElementById("primary-navigation");
  if (toggle && sidebar) {
    const closeMenu = function () { sidebar.classList.remove("is-open"); toggle.setAttribute("aria-expanded", "false"); };
    toggle.addEventListener("click", function () {
      const open = sidebar.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", String(open));
      if (open) { const firstLink = sidebar.querySelector("a"); if (firstLink) firstLink.focus(); }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && sidebar.classList.contains("is-open")) { closeMenu(); toggle.focus(); }
    });
    document.addEventListener("click", function (event) {
      if (!sidebar.contains(event.target) && !toggle.contains(event.target)) closeMenu();
    });
  }
  document.querySelectorAll("[data-dismiss]").forEach(function (button) {
    button.addEventListener("click", function () { const note = button.closest(".notification"); if (note) note.remove(); });
  });
});
