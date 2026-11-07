(() => {
  'use strict';

  const drawer = document.getElementById('navigation-drawer');
  const sidebar = document.getElementById('navigation');
  const workspace = document.getElementById('workspace-main');
  const menu = document.querySelector('.menu-toggle');
  const close = document.querySelector('.sidebar-close');
  const backdrop = document.querySelector('.navigation-backdrop');
  if (!drawer || !sidebar || !workspace || !menu) return;

  const body = document.body;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  let closingTimer;

  function setNavigation(open, focus = true) {
    window.clearTimeout(closingTimer);
    if (open) {
      drawer.open = true;
      // Materializa el estado de partida antes de deslizar el panel.
      sidebar.getBoundingClientRect();
      sidebar.setAttribute('role', 'dialog');
      sidebar.setAttribute('aria-modal', 'true');
      sidebar.setAttribute('aria-label', 'Navegación principal');
    } else {
      sidebar.removeAttribute('role');
      sidebar.removeAttribute('aria-modal');
      sidebar.removeAttribute('aria-label');
    }
    body.dataset.navOpen = String(open);
    menu.setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-label', open ? 'Cerrar navegación' : 'Abrir navegación');
    sidebar.inert = !open;
    workspace.inert = open;
    if (!open) {
      if (!focus || reducedMotion.matches) drawer.open = false;
      else closingTimer = window.setTimeout(() => { drawer.open = false; }, 200);
    }
    if (focus) (open ? close : menu)?.focus();
  }

  setNavigation(false, false);
  window.addEventListener('pageshow', event => {
    if (event.persisted) setNavigation(false, false);
  });
  menu.addEventListener('click', event => {
    event.preventDefault();
    setNavigation(body.dataset.navOpen !== 'true');
  });
  close?.addEventListener('click', () => setNavigation(false));
  backdrop?.addEventListener('click', () => setNavigation(false));
  sidebar.addEventListener('click', event => {
    if (event.target.closest?.('a[href]:not([aria-disabled="true"])')) setNavigation(false);
  });
  document.addEventListener('keydown', event => {
    if (body.dataset.navOpen !== 'true') return;
    if (event.key === 'Escape') {
      event.preventDefault();
      setNavigation(false);
    }
    if (event.key !== 'Tab') return;
    const items = Array.from(sidebar.querySelectorAll('a[href]:not([aria-disabled="true"]), button:not([disabled]):not([tabindex="-1"])'));
    const first = items[0];
    const last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });
})();
