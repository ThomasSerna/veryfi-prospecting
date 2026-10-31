(() => {
  'use strict';

  const body = document.body;
  const menu = document.querySelector('.menu-toggle');
  const sidebar = document.getElementById('navigation');
  const workspace = document.getElementById('workspace-main');
  const mobile = window.matchMedia('(max-width: 760px)');

  function closeNavigation() {
    body.dataset.navOpen = 'false';
    if (menu) {
      menu.setAttribute('aria-expanded', 'false');
      menu.setAttribute('aria-label', 'Abrir navegación');
    }
    if (sidebar) sidebar.inert = mobile.matches;
    if (workspace) workspace.inert = false;
  }

  if (menu && sidebar) {
    closeNavigation();
    menu.addEventListener('click', () => {
      const open = body.dataset.navOpen !== 'true';
      body.dataset.navOpen = String(open);
      menu.setAttribute('aria-expanded', String(open));
      menu.setAttribute('aria-label', open ? 'Cerrar navegación' : 'Abrir navegación');
      sidebar.inert = mobile.matches && !open;
      if (workspace) workspace.inert = mobile.matches && open;
      if (open) sidebar.querySelector('a')?.focus();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && body.dataset.navOpen === 'true') {
        closeNavigation();
        menu.focus();
      }
    });
    document.addEventListener('click', event => {
      if (body.dataset.navOpen === 'true' && !sidebar.contains(event.target) && !menu.contains(event.target)) closeNavigation();
    });
    mobile.addEventListener('change', closeNavigation);
  }

  document.addEventListener('click', event => {
    const disabled = event.target?.closest?.('a[aria-disabled="true"]');
    if (disabled) {
      event.preventDefault();
      return;
    }
    const copyBtn = event.target?.closest?.('[data-copy-channel]');
    if (copyBtn && navigator?.clipboard?.writeText) {
      const value = copyBtn.dataset.copyChannel || '';
      const original = copyBtn.dataset.originalLabel || copyBtn.textContent;
      copyBtn.dataset.originalLabel = original;
      navigator.clipboard.writeText(value).then(() => {
        copyBtn.dataset.copied = 'true';
        copyBtn.textContent = '¡Copiado!';
        window.setTimeout(() => {
          copyBtn.dataset.copied = 'false';
          copyBtn.textContent = original;
        }, 1800);
      }).catch(() => {});
    }
  });

  function setupFilterChoices(root = document) {
    if (!root.querySelectorAll) return;
    const choices = Array.from(root.querySelectorAll('.filter-choice'));
    const detailsList = choices.map(choice => choice.querySelector('details')).filter(Boolean);

    choices.forEach(choice => {
      const summaryText = choice.querySelector('[data-filter-summary]');
      const checkboxes = Array.from(choice.querySelectorAll('input[type="checkbox"]'));
      function syncChoice() {
        const selected = checkboxes.filter(input => input.checked);
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
      checkboxes.forEach(input => input.addEventListener('change', syncChoice));
    });

    detailsList.forEach(filter => filter.addEventListener('toggle', () => {
      if (filter.open) detailsList.forEach(other => { if (other !== filter) other.open = false; });
    }));
    document.addEventListener('click', event => detailsList.forEach(filter => {
      if (filter.open && !filter.contains(event.target)) filter.open = false;
    }));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') detailsList.forEach(filter => { filter.open = false; });
    });
  }
  setupFilterChoices();

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
    tablist.setAttribute('role', 'tablist');
    tabs.forEach((tab, index) => {
      tab.setAttribute('role', 'tab');
      tab.id = `tab-${panels[index].id}`;
      tab.setAttribute('aria-controls', panels[index].id);
      panels[index].setAttribute('role', 'tabpanel');
      panels[index].setAttribute('aria-labelledby', tab.id);
    });
    function selectTab(index, focus = false) {
      tabs.forEach((tab, current) => {
        const selected = current === index;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        panels[current].hidden = !selected;
      });
      if (focus) tabs[index].focus();
    }
    function revealHash() {
      const hash = window.location.hash;
      const matching = panels.findIndex(panel => `#${panel.id}` === hash);
      if (matching >= 0) selectTab(matching);
      else if (hash.startsWith('#source-')) {
        selectTab(panels.findIndex(panel => panel.id === 'evidence'));
        const source = document.getElementById(hash.slice(1));
        if (source) requestAnimationFrame(() => source.scrollIntoView({ block: 'start' }));
      }
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', event => {
        event.preventDefault();
        selectTab(index);
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
          selectTab(next, true);
          window.history.replaceState(null, '', tabs[next].getAttribute('href'));
        }
      });
    });
    selectTab(0);
    revealHash();
    const invalidPanel = panels.findIndex(panel => panel.querySelector('.field-errors, .errorlist'));
    if (invalidPanel >= 0) selectTab(invalidPanel);
    window.addEventListener('hashchange', revealHash);
    tabsRoot.querySelectorAll('[data-evidence-link]').forEach(link => link.addEventListener('click', () => {
      selectTab(panels.findIndex(panel => panel.id === 'evidence'));
    }));
  }

  const campaignPage = document.getElementById('campaign-page');
  if (!campaignPage) {
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
      const currentScroll = live.querySelector('.results-section .table-scroll');
      const scrollLeft = currentScroll ? currentScroll.scrollLeft : 0;
      const budgetDetailsOpen = Boolean(live.querySelector('.budget-details')?.open);

      ['overview', 'results', 'budget'].forEach(sectionName => {
        const currentSection = live.querySelector(`[data-live-section="${sectionName}"]`);
        const nextSection = parsed.querySelector(`[data-live-section="${sectionName}"]`);
        if (currentSection && nextSection) currentSection.replaceWith(nextSection);
      });

      const currentFilters = live.querySelector('[data-live-filters]');
      const nextFilters = parsed.querySelector('[data-live-filters]');
      if (currentFilters && nextFilters) {
        currentFilters.hidden = nextFilters.hidden;
      }

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

  async function poll() {
    if (polling) return;
    polling = true;
    try {
      const response = await fetch(campaignPage.dataset.statusUrl + window.location.search, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
      });
      if (!response.ok) throw new Error('No se pudo consultar el avance. Los datos guardados se conservan.');
      const snapshot = await response.json();
      if (snapshot.html) {
        applyLiveSnapshot(snapshot.html);
      }
      if (snapshot.is_executing) {
        setBusy(true);
        pollTimer = window.setTimeout(poll, 2000);
      } else if (busy) {
        window.location.reload();
      }
    } catch (error) {
      showFeedback(error.message + ' Puedes volver a cargar la página para consultar el estado.', 'warning');
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
      showFeedback('Iniciando investigación. Los resultados aparecerán cuando se guarden.');
      try {
        const response = await fetch(form.action, {
          method: 'POST', body: data, credentials: 'same-origin',
          headers: { 'Accept': 'application/json', 'X-CSRFToken': data.get('csrfmiddlewaretoken') },
        });
        const result = await response.json();
        if (!response.ok) {
          setBusy(result.is_executing === true);
          showFeedback(result.error_message || 'No se pudo iniciar la investigación. Revisa la autorización y los topes.', 'error');
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
        showFeedback('Investigación en curso. Puedes consultar el avance y las empresas que se van guardando.');
        window.clearTimeout(pollTimer);
        poll();
      } catch (_error) {
        showFeedback('No pudimos confirmar la respuesta del servidor. Consulta el avance antes de volver a ejecutar; los datos guardados se conservan.', 'warning');
        poll();
      }
    });
  }
  if (busy) {
    setBusy(true);
    pollTimer = window.setTimeout(poll, 2000);
  }
})();
