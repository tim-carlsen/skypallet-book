document.addEventListener("DOMContentLoaded", () => {
  // Select external links in the sidebar (bd-sidenav)
  document.querySelectorAll(".bd-sidenav a.reference.external").forEach((link) => {
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener");
  });
});
