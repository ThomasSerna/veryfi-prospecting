(() => {
  'use strict';

  const menu = document.getElementById('navigation-menu');
  if (!menu) return;
  const toggle = menu.querySelector('summary');

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) {
      event.preventDefault();
      menu.open = false;
      toggle.focus();
    }
  });
  document.addEventListener('click', event => {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  window.matchMedia('(max-width: 760px)').addEventListener('change', () => { menu.open = false; });
})();
