(() => {
  'use strict';

  const body = document.body;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  // Con JavaScript, las filas de empresas se abren completas (ver el clic delegado).
  body.dataset.rowLinks = 'true';

  const previewForm = document.querySelector('[data-campaign-preview]');
  if (previewForm) {
    const updatePreview = () => {
      ['countries', 'segments'].forEach(name => {
        const target = previewForm.querySelector(`[data-preview-${name}]`);
        const selected = Array.from(previewForm.querySelectorAll(`input[name="${name}"]:checked`));
        if (target) target.textContent = selected.map(input => input.closest('label').textContent.trim()).join(', ') || 'Sin seleccionar';
      });
      const maximum = previewForm.querySelector('[name="max_companies"]');
      const target = previewForm.querySelector('[data-preview-max]');
      if (target) target.textContent = maximum?.value || 'Sin definir';
    };
    previewForm.addEventListener('input', updatePreview);
    updatePreview();
  }

  document.addEventListener('click', event => {
    const disabled = event.target?.closest?.('a[aria-disabled="true"]');
    if (disabled) {
      event.preventDefault();
      return;
    }
    // Toda la fila abre la ficha; el enlace del nombre sigue siendo el único destino para teclado y lectores.
    const row = event.target?.closest?.('.result-row');
    if (row && !event.target.closest('a, button, input, label, summary')
        && !String(window.getSelection?.() || '')) {
      const link = row.querySelector('.company-link');
      if (link && (event.ctrlKey || event.metaKey)) window.open(link.href, '_blank', 'noopener');
      else link?.click();
      return;
    }
    const copyBtn = event.target?.closest?.('[data-copy-channel]');
    if (copyBtn && navigator?.clipboard?.writeText) {
      const value = copyBtn.dataset.copyChannel || '';
      const label = copyBtn.querySelector('[data-copy-label]') || copyBtn;
      navigator.clipboard.writeText(value).then(() => {
        window.clearTimeout(Number(copyBtn.dataset.copyTimer));
        copyBtn.dataset.copied = 'true';
        label.textContent = 'Copiado';
        announce('Canal copiado.');
        copyBtn.dataset.copyTimer = String(window.setTimeout(() => {
          copyBtn.dataset.copied = 'false';
          label.textContent = 'Copiar';
        }, 1800));
      }).catch(() => {});
    }
  });

  // Un único anuncio cortés para confirmaciones que no cambian de página.
  let announcer;
  function announce(text) {
    if (!announcer) {
      announcer = document.createElement('p');
      announcer.className = 'sr-only';
      announcer.setAttribute('role', 'status');
      body.append(announcer);
    }
    announcer.textContent = '';
    window.setTimeout(() => { announcer.textContent = text; }, 60);
  }

  // La confirmación de guardado se muestra una vez; recargar la página no la repite.
  if (/[?&]saved=/.test(window.location?.search || '') && window.history?.replaceState) {
    const search = window.location.search.replace(/([?&])saved=[^&#]*&?/, '$1').replace(/[?&]$/, '');
    window.history.replaceState(null, '', `${window.location.pathname}${search}${window.location.hash}`);
  }

  // Filtros delegados: también funcionan con opciones que el sondeo agrega después de cargar.
  function syncChoice(choice) {
    const summaryText = choice.querySelector('[data-filter-summary]');
    const selected = Array.from(choice.querySelectorAll('input[type="checkbox"]:checked'));
    choice.dataset.active = String(selected.length > 0);
    if (!summaryText) return;
    if (selected.length === 0) summaryText.textContent = 'Todos';
    else if (selected.length === 1) {
      const label = selected[0].closest('label');
      summaryText.textContent = label ? label.textContent.trim() : '1 seleccionado';
    } else {
      summaryText.textContent = `${selected.length} seleccionados`;
    }
  }
  const openFilters = () => Array.from(document.querySelectorAll('.filter-choice details[open]'));
  document.addEventListener('change', event => {
    const choice = event.target?.closest?.('.filter-choice');
    if (choice) syncChoice(choice);
  });
  // `toggle` no burbujea: se escucha en captura para cerrar los demás desplegables.
  document.addEventListener('toggle', event => {
    const filter = event.target;
    if (filter?.open && filter.closest?.('.filter-choice')) {
      openFilters().forEach(other => { if (other !== filter) other.open = false; });
    }
  }, true);
  document.addEventListener('click', event => openFilters().forEach(filter => {
    if (!filter.contains(event.target)) filter.open = false;
  }));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const open = openFilters();
    open.forEach(filter => { filter.open = false; });
    if (open.some(filter => filter.contains(document.activeElement))) open[0].querySelector('summary')?.focus();
  });

  function setupOperationRows() {
    const rows = Array.from(document.querySelectorAll('[data-operation-row]'));
    if (!rows.length) return;

    function fillSuggested(row) {
      const costInput = row.querySelector('input[name^="cost_"]');
      const creditsInput = row.querySelector('input[name^="credits_"]');
      const suggestedCost = row.dataset.suggestedCost;
      const suggestedCredits = row.dataset.suggestedCredits;
      const costZero = !costInput || !costInput.value || Number(costInput.value) === 0;
      const creditsZero = !creditsInput || !creditsInput.value || Number(creditsInput.value) === 0;
      if (costZero && creditsZero) {
        if (costInput && suggestedCost !== undefined) costInput.value = suggestedCost;
        if (creditsInput && suggestedCredits !== undefined) creditsInput.value = suggestedCredits;
      }
    }

    rows.forEach(row => {
      const checkbox = row.querySelector('input[type="checkbox"][name^="allow_"]');
      if (!checkbox) return;
      row.dataset.selected = String(checkbox.checked);
      checkbox.addEventListener('change', () => {
        row.dataset.selected = String(checkbox.checked);
        if (checkbox.checked) fillSuggested(row);
      });
    });

    const applyButton = document.querySelector('[data-apply-suggested]');
    if (applyButton) {
      applyButton.addEventListener('click', () => {
        const anyChecked = rows.some(row => row.querySelector('input[type="checkbox"][name^="allow_"]')?.checked);
        rows.forEach(row => {
          const checkbox = row.querySelector('input[type="checkbox"][name^="allow_"]');
          if (!checkbox || checkbox.disabled) return;
          if (!anyChecked) {
            checkbox.checked = true;
            row.dataset.selected = 'true';
          }
          if (checkbox.checked) {
            const costInput = row.querySelector('input[name^="cost_"]');
            const creditsInput = row.querySelector('input[name^="credits_"]');
            if (costInput && row.dataset.suggestedCost !== undefined) costInput.value = row.dataset.suggestedCost;
            if (creditsInput && row.dataset.suggestedCredits !== undefined) creditsInput.value = row.dataset.suggestedCredits;
          }
        });
      });
    }
  }
  setupOperationRows();

  const tabsRoot = document.querySelector('[data-tabs]');
  if (tabsRoot) {
    const tablist = tabsRoot.querySelector('.tabs');
    const tabs = Array.from(tablist.querySelectorAll('.tab-link'));
    const panels = tabs.map(tab => document.querySelector(tab.getAttribute('href')));
    // Dos indicadores medidos desde cada etiqueta: la pastilla acompaña al puntero y la línea, a la pestaña activa.
    const hover = document.createElement('span');
    const line = document.createElement('span');
    hover.className = 'tabs-hover';
    line.className = 'tabs-indicator';
    [hover, line].forEach(node => node.setAttribute('aria-hidden', 'true'));
    tablist.append(hover, line);
    tablist.dataset.enhanced = 'true';
    let current = -1;
    tablist.setAttribute('role', 'tablist');
    tabs.forEach((tab, index) => {
      tab.setAttribute('role', 'tab');
      tab.id = `tab-${panels[index].id}`;
      tab.setAttribute('aria-controls', panels[index].id);
      panels[index].setAttribute('role', 'tabpanel');
      panels[index].setAttribute('aria-labelledby', tab.id);
      panels[index].tabIndex = 0;
    });
    function place(indicator, tab, instant = false) {
      if (!tab) {
        indicator.dataset.visible = 'false';
        return;
      }
      // La pastilla aparece en su sitio la primera vez y después se desliza entre pestañas.
      if (instant || indicator.dataset.visible !== 'true') indicator.style.transition = 'none';
      if (indicator === hover) {
        const right = tablist.clientWidth - tab.offsetLeft - tab.offsetWidth;
        indicator.style.clipPath = `inset(0 ${right}px 0 ${tab.offsetLeft}px round 9px)`;
      } else {
        indicator.style.transform = `translateX(${tab.offsetLeft}px) scaleX(${tab.offsetWidth / 100})`;
      }
      if (indicator.style.transition === 'none') {
        indicator.getBoundingClientRect();
        indicator.style.removeProperty('transition');
      }
      indicator.dataset.visible = 'true';
    }
    function selectTab(index, focus = false, animate = false) {
      const direction = Math.sign(index - current);
      // Elegir una pestaña termina la entrada: el panel nuevo no repite la cascada inicial.
      if (animate) tabsRoot.closest('[data-entering]')?.removeAttribute('data-entering');
      tabs.forEach((tab, position) => {
        const selected = position === index;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        panels[position].hidden = !selected;
      });
      place(line, tabs[index], !animate);
      // El panel entra desde el lado hacia el que se movió la selección.
      if (animate && index !== current) panels[index].animate?.(reducedMotion.matches
        ? [{ opacity: 0 }, { opacity: 1 }]
        : [{ opacity: 0, transform: `translateX(${direction * 18}px)` }, { opacity: 1, transform: 'none' }],
      { duration: reducedMotion.matches ? 160 : 340, easing: 'cubic-bezier(.16, 1, .3, 1)' });
      current = index;
      if (focus) tabs[index].focus();
    }
    tablist.addEventListener('pointerover', event => {
      const tab = event.target.closest?.('.tab-link');
      if (tab) place(hover, tab);
    });
    tablist.addEventListener('pointerleave', () => { hover.dataset.visible = 'false'; });
    window.addEventListener('resize', () => place(line, tabs[current], true));
    document.fonts?.ready?.then(() => place(line, tabs[current], true));
    function highlight(source) {
      source.scrollIntoView({ block: 'center' });
      // La fuente señalada por una píldora se ilumina un instante para unir referencia y origen.
      source.animate?.([
        { backgroundColor: 'rgb(128 223 243 / 10%)', boxShadow: '0 0 0 1px rgb(128 223 243 / 55%)' },
        { backgroundColor: 'rgb(128 223 243 / 0%)', boxShadow: '0 0 0 1px rgb(128 223 243 / 0%)' },
      ], { duration: 1800, delay: reducedMotion.matches ? 0 : 280, easing: 'ease-out', fill: 'backwards' });
    }
    function revealHash(animate = true) {
      const hash = window.location.hash;
      const matching = panels.findIndex(panel => `#${panel.id}` === hash);
      if (matching >= 0) selectTab(matching, false, animate);
      else if (hash.startsWith('#source-')) {
        selectTab(panels.findIndex(panel => panel.id === 'evidence'));
        const source = document.getElementById(hash.slice(1));
        if (source) requestAnimationFrame(() => highlight(source));
      }
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', event => {
        event.preventDefault();
        selectTab(index, false, true);
        window.history.replaceState(null, '', tab.getAttribute('href'));
      });
      tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = tabs.length - 1;
        if (next !== undefined) {
          event.preventDefault();
          selectTab(next, true, true);
          window.history.replaceState(null, '', tabs[next].getAttribute('href'));
        }
      });
    });
    selectTab(0);
    revealHash(false);
    const invalidPanel = panels.findIndex(panel => panel.querySelector('.field-errors, .errorlist'));
    if (invalidPanel >= 0) selectTab(invalidPanel);
    window.addEventListener('hashchange', () => revealHash());
    tabsRoot.querySelectorAll('[data-evidence-link]').forEach(link => link.addEventListener('click', () => {
      selectTab(panels.findIndex(panel => panel.id === 'evidence'));
    }));
  }

  const campaignPage = document.getElementById('campaign-page');
  if (!campaignPage) {
    // El resumen se actualiza en su sitio desde dashboard.js; recargarlo reiniciaría su entrada.
    if (document.querySelector('[data-live-dashboard]')) return;
    if (body.dataset.running === 'true' && body.dataset.statusUrl) {
      const check = async () => {
        try {
          const separator = body.dataset.statusUrl.includes('?') ? '&' : '?';
          const response = await fetch(`${body.dataset.statusUrl}${separator}compact=1`, {
            headers: { 'Accept': 'application/json' },
            cache: 'no-store',
            credentials: 'same-origin',
          });
          if (response.ok && !(await response.json()).is_executing) { window.location.reload(); return; }
        } catch (_error) { /* La consulta no altera resultados; un fallo se vuelve a comprobar. */ }
        window.setTimeout(check, 2000);
      };
      window.setTimeout(check, 2000);
    }
    return;
  }
  const live = document.getElementById('campaign-live');
  const form = document.getElementById('execution-form');
  const feedback = document.getElementById('execution-feedback');
  let pollTimer;
  let polling = false;
  let busy = campaignPage.dataset.running === 'true';
  const inactiveControls = new Map();

  function setBusy(value) {
    busy = value;
    body.dataset.running = String(value);
    campaignPage.dataset.running = String(value);
    document.querySelectorAll('[data-idle-only]').forEach(control => {
      if (!inactiveControls.has(control)) inactiveControls.set(control, {
        disabled: control.disabled,
        ariaDisabled: control.getAttribute('aria-disabled'),
        tabIndex: control.getAttribute('tabindex'),
      });
      const original = inactiveControls.get(control);
      if (control.tagName === 'A') {
        if (value) {
          control.setAttribute('aria-disabled', 'true');
          control.setAttribute('tabindex', '-1');
        } else {
          if (original.ariaDisabled === null) control.removeAttribute('aria-disabled');
          else control.setAttribute('aria-disabled', original.ariaDisabled);
          if (original.tabIndex === null) control.removeAttribute('tabindex');
          else control.setAttribute('tabindex', original.tabIndex);
        }
      } else control.disabled = value || original.disabled;
    });
    document.querySelectorAll('[data-idle-form] fieldset').forEach(fieldset => {
      if (!inactiveControls.has(fieldset)) inactiveControls.set(fieldset, { disabled: fieldset.disabled });
      fieldset.disabled = value || inactiveControls.get(fieldset).disabled;
    });
  }

  function showFeedback(message, kind = 'info') {
    feedback.replaceChildren();
    if (!message) return;
    const notice = document.createElement('div');
    notice.className = `notice notice-${kind}`;
    notice.textContent = message;
    feedback.append(notice);
  }

  function applyLiveSnapshot(html) {
    if (typeof DOMParser !== 'undefined' && live.querySelector) {
      const parsed = new DOMParser().parseFromString(html, 'text/html');
      const morphing = window.ProspectingLive;
      const currentScroll = live.querySelector('.results-section .table-scroll');
      const scrollLeft = currentScroll ? currentScroll.scrollLeft : 0;
      const budgetDetailsOpen = Boolean(live.querySelector('.budget-details')?.open);

      // Cada sección se compara en su sitio: filas, foco, desplegables y animaciones en curso se conservan.
      live.querySelectorAll('[data-live-section]').forEach(currentSection => {
        const nextSection = parsed.querySelector(`[data-live-section="${currentSection.dataset.liveSection}"]`);
        if (!nextSection) return;
        if (morphing) morphing.update(currentSection, nextSection);
        else currentSection.replaceWith(nextSection);
      });

      const currentFilters = live.querySelector('[data-live-filters]');
      const nextFilters = parsed.querySelector('[data-live-filters]');
      if (currentFilters && nextFilters) {
        currentFilters.hidden = nextFilters.hidden;
      }

      if (morphing) return;
      const nextBudgetDetails = live.querySelector('.budget-details');
      if (nextBudgetDetails) nextBudgetDetails.open = budgetDetailsOpen;
      const nextScroll = live.querySelector('.results-section .table-scroll');
      if (nextScroll && scrollLeft) nextScroll.scrollLeft = scrollLeft;
      return;
    }

    const openDetails = Array.from(live.querySelectorAll('details')).map(detail => detail.open);
    live.innerHTML = html;
    live.querySelectorAll('details').forEach((detail, index) => { detail.open = openDetails[index] || false; });
  }

  // Al terminar, la página se lee de nuevo y se actualiza en su sitio para no repetir la entrada;
  // sin comparación disponible o ante un fallo, se recarga.
  async function finish() {
    const morphing = window.ProspectingLive;
    if (!morphing || typeof DOMParser === 'undefined') {
      window.location.reload();
      return;
    }
    try {
      const response = await fetch(window.location.href, {
        headers: { 'Accept': 'text/html' }, cache: 'no-store', credentials: 'same-origin',
      });
      if (!response.ok) throw new Error(`Estado ${response.status}`);
      const next = new DOMParser().parseFromString(await response.text(), 'text/html');
      const main = document.getElementById('main');
      const nextMain = next.getElementById('main');
      if (!main || !nextMain?.querySelector('#campaign-page')) throw new Error('Campaña ausente');
      inactiveControls.clear();
      busy = false;
      morphing.update(main, nextMain);
      const nav = document.querySelector('[data-live-region="navigation"]');
      const nextNav = next.querySelector('[data-live-region="navigation"]');
      if (nav && nextNav) morphing.morph(nav, nextNav, []);
      body.dataset.running = next.body?.dataset.running === 'true' ? 'true' : 'false';
    } catch (_error) {
      window.location.reload();
    }
  }

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(campaignPage.dataset.statusUrl + window.location.search, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('No se pudo consultar el avance.');
      const snapshot = await response.json();
      if (snapshot.html) {
        applyLiveSnapshot(snapshot.html);
      }
      if (snapshot.is_executing) {
        setBusy(true);
        pollTimer = window.setTimeout(poll, 2000);
      } else if (busy) {
        await finish();
      }
    } catch (error) {
      showFeedback(error.message, 'warning');
      pollTimer = window.setTimeout(poll, 5000);
    } finally {
      polling = false;
    }
  }

  if (form) {
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy) return;
      const data = new FormData(form);
      const errors = form.querySelector('.execution-errors');
      if (errors) { errors.hidden = true; errors.replaceChildren(); }
      form.querySelectorAll?.('[aria-invalid="true"]').forEach(field => field.removeAttribute('aria-invalid'));
      setBusy(true);
      showFeedback('Iniciando investigación…');
      try {
        const response = await fetch(form.action, {
          method: 'POST', body: data, credentials: 'same-origin',
          headers: { 'Accept': 'application/json', 'X-CSRFToken': data.get('csrfmiddlewaretoken') },
        });
        const result = await response.json();
        if (!response.ok) {
          setBusy(result.is_executing === true);
          showFeedback(result.error_message || 'No se pudo iniciar la investigación.', 'error');
          if (errors && result.errors) {
            Object.entries(result.errors).forEach(([name, messages]) => {
              const field = form.elements?.namedItem?.(name);
              if (field && field.setAttribute) field.setAttribute('aria-invalid', 'true');
              messages.forEach(message => {
                const paragraph = document.createElement('p');
                paragraph.textContent = message;
                errors.append(paragraph);
              });
            });
            errors.hidden = false;
            errors.tabIndex = -1;
            errors.focus?.();
          }
          if (busy) poll();
          return;
        }
        const authDetails = document.querySelector('#authorization details');
        if (authDetails) authDetails.open = false;
        showFeedback('Investigación en curso.');
        window.clearTimeout(pollTimer);
        poll();
      } catch (_error) {
        showFeedback('No se pudo confirmar la respuesta del servidor.', 'warning');
        poll();
      }
    });
  }
  if (busy) {
    setBusy(true);
    pollTimer = window.setTimeout(poll, 2000);
  }
})();
