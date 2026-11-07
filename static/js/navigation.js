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

  // Una sola pastilla se desliza al enlace señalado o enfocado y vuelve a la sección actual.
  const nav = sidebar.querySelector?.('.main-nav');
  const indicator = nav ? document.createElement('span') : null;
  if (indicator) {
    indicator.className = 'navigation-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    indicator.setAttribute('data-morph-skip', '');
    nav.append(indicator);
    nav.dataset.indicator = 'true';
  }
  const currentLink = () => nav?.querySelector('a[aria-current="page"]') || null;

  function placeIndicator(link, instant = false) {
    if (!indicator) return;
    if (!link?.offsetHeight) {
      nav.dataset.indicatorVisible = 'false';
      return;
    }
    if (instant) indicator.style.transition = 'none';
    indicator.style.transform = `translateY(${link.offsetTop}px)`;
    indicator.style.height = `${link.offsetHeight}px`;
    nav.dataset.indicatorVisible = 'true';
    if (instant) {
      indicator.getBoundingClientRect();
      indicator.style.removeProperty('transition');
    }
  }

  nav?.addEventListener('pointerover', event => {
    const link = event.target.closest?.('a[href]');
    placeIndicator(link && link.getAttribute('aria-disabled') !== 'true' ? link : currentLink());
  });
  nav?.addEventListener('pointerleave', () => placeIndicator(currentLink()));
  nav?.addEventListener('focusin', event => placeIndicator(event.target.closest?.('a[href]') || currentLink()));
  nav?.addEventListener('focusout', event => {
    if (!nav.contains(event.relatedTarget)) placeIndicator(currentLink());
  });

  function setNavigation(open, focus = true) {
    window.clearTimeout(closingTimer);
    if (open) {
      drawer.open = true;
      // Materializa el estado de partida antes de deslizar el panel.
      sidebar.getBoundingClientRect();
      placeIndicator(currentLink(), true);
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
