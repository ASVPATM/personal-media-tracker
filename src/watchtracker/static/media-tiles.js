(() => {
  "use strict";
  document.addEventListener("DOMContentLoaded", () => {
    const library = document.querySelector("#library");
    if (typeof window.cardHtml !== "function" || !library) return;
    const hosts = [...document.querySelectorAll('.app-view:not(#rankings-view) .library, #recommendation-results')];
    const cardsIn = host => [...host.querySelectorAll('.entry-card:not(.skeleton-card), .recommendation-result')]
      .filter(card => !card.closest('#rankings-view, dialog'));
    const eligible = card => card && hosts.some(host => host.contains(card)) && !card.closest('#rankings-view, dialog');
    const originalChildren = new WeakMap();
    // The application's translation cache intentionally stores only identity
    // metadata. Keep a separate, bounded tile-render snapshot; never feed these
    // personal tracking fields into the metadata/translation request cache.
    const tileEntries = new Map();
    let tileOwner = state.currentUser?.id || 'local';
    function tileSnapshot(entry = null) {
      const owner = state.currentUser?.id || 'local';
      if (owner !== tileOwner) { tileEntries.clear(); tileOwner = owner; }
      if (entry?.catalog_item && typeof entry.status === 'string'
          && Number.isFinite(entry.view_count) && Array.isArray(entry.effective_genres)) {
        const fields = ['id', 'catalog_item', 'status', 'view_count', 'is_favorite',
          'effective_genres', 'effective_subgenres', 'episode_progress', 'deleted_at'];
        tileEntries.set(entry.id, Object.fromEntries(fields.map(key => [key, entry[key]])));
        if (tileEntries.size > 512) tileEntries.delete(tileEntries.keys().next().value);
      }
      return tileEntries;
    }
    const storageKey = "watchtracker-artwork-reveal";
    let enabled = false;
    try { enabled = localStorage.getItem(storageKey) === "true"; } catch (_) { /* Optional device preference. */ }
    const viewCountsKey = 'watchtracker-tile-view-counts';
    let showViewCounts = false;
    try { showViewCounts = localStorage.getItem(viewCountsKey) === 'true'; } catch (_) { /* Optional device preference. */ }
    let activeCard = null;
    let hoveredCard = null;
    let dismissTimer = null;
    let lastInput = "keyboard";
    let lastPointer = null;
    let hoverBlockedAt = null;
    let restoringFocus = false;
    let panelSequence = 0;
    const labels = {
      en: ["Artwork reveal", "Hover, focus, or tap for compact details on the poster. All media tiles except Rankings.", "Show details for", "Close details", "Read more", "Read less", "View counts on tiles", "Optional. Counts and viewing history are always available in title details.", "Turn off Artwork reveal to use artwork tint or full-colour blend. Your choices are kept."],
      fr: ["Volet sur l’affiche", "Survolez, utilisez le clavier ou touchez pour voir les détails sur l’affiche. Toutes les fiches, sauf le classement.", "Afficher les détails de", "Fermer les détails", "Lire la suite", "Réduire", "Compteurs de visionnages sur les fiches", "Facultatif. Les compteurs et l’historique restent disponibles dans les détails du titre.", "Désactivez le volet sur l’affiche pour utiliser la teinte ou le mélange des couleurs. Vos choix sont conservés."],
      "zh-CN": ["海报详情浮层", "悬停、键盘聚焦或轻点，在海报上查看紧凑详情。适用于除排名页之外的所有媒体卡片。", "显示详情：", "关闭详情", "展开全文", "收起", "在媒体卡片上显示观看次数", "可选。观看次数和观看历史始终可在媒体详情中查看。", "关闭海报详情浮层后，即可使用海报色调或全彩混合。您的选择会被保留。"]
    };
    const copy = () => labels[document.documentElement.lang] || labels.en;
    const renderLanguage = typeof window.applyInterfaceLanguage === "function" ? window.applyInterfaceLanguage : null;
    const renderCard = window.cardHtml;
    const replaceCard = window.replaceEntryCard;
    window.cardHtml = function(entry, ...args) {
      tileSnapshot(entry);
      return renderCard.call(this, entry, ...args);
    };
    // Preserve the open panel and focus when a live control replaces its card.
    if (typeof replaceCard === "function") window.replaceEntryCard = function(card, entry, focusSelector) {
      const wasOpen = activeCard === card;
      const wasHovered = hoveredCard === card;
      const counterWasOpen = Boolean(card.querySelector('[data-episode-toggle][aria-expanded="true"]'));
      const replacement = replaceCard.call(this, card, entry, focusSelector);
      if (counterWasOpen) setEpisodeMenu(replacement?.querySelector('[data-episode-progress]'), true);
      if (enabled && wasOpen && eligible(replacement)) {
        hoverBlockedAt = lastPointer;
        replacement.classList.add("pmt-reveal-restored");
        prepareCards();
        if (wasHovered) hoveredCard = replacement;
        openPanel(replacement);
        if (focusSelector) replacement.querySelector(focusSelector)?.focus({preventScroll: true});
      }
      return replacement;
    };

    function setEpisodeMenu(progress, open, returnFocus = false) {
      const toggle = progress?.querySelector('[data-episode-toggle]');
      const menu = progress?.querySelector('[data-episode-menu]');
      if (!toggle || !menu) return;
      if (!open && returnFocus && progress.isConnected) toggle.focus({preventScroll: true});
      toggle.setAttribute('aria-expanded', String(open));
      menu.hidden = !open;
    }

    function closeEpisodeMenus(except = null, returnFocus = false) {
      document.querySelectorAll('[data-episode-toggle][aria-expanded="true"]').forEach(toggle => {
        const progress = toggle.closest('[data-episode-progress]');
        if (progress !== except) setEpisodeMenu(progress, false, returnFocus);
      });
    }

    function closePanel(returnFocus = false) {
      clearTimeout(dismissTimer);
      if (!activeCard) return;
      const previous = activeCard;
      previous.querySelectorAll('[data-episode-progress]').forEach(progress => setEpisodeMenu(progress, false));
      activeCard = null;
      const trigger = previous.querySelector(".pmt-artwork-trigger");
      // Move focus before making the formerly focused controls inert.
      if (returnFocus && previous.isConnected) {
        hoverBlockedAt = lastPointer;
        restoringFocus = true;
        trigger?.focus({preventScroll: true});
        restoringFocus = false;
      }
      previous.classList.remove("pmt-reveal-open", "pmt-reveal-restored");
      const panel = previous.querySelector(".pmt-artwork-panel");
      if (panel) { panel.inert = true; panel.setAttribute("aria-hidden", "true"); }
      trigger?.setAttribute("aria-expanded", "false");
    }

    function openPanel(card) {
      if (!enabled || !card?.isConnected || !card.classList.contains("media-artwork-card")) return;
      clearTimeout(dismissTimer);
      if (activeCard !== card) closePanel();
      activeCard = card;
      const panel = card.querySelector(".pmt-artwork-panel");
      panel.inert = false;
      panel.setAttribute("aria-hidden", "false");
      card.querySelector(".pmt-artwork-trigger").setAttribute("aria-expanded", "true");
      card.classList.add("pmt-reveal-open");
    }

    function syncLabels(card) {
      const title = card.querySelector("h3, h4")?.textContent || "PMT";
      const trigger = card.querySelector(".pmt-artwork-trigger");
      trigger?.setAttribute("aria-label", `${copy()[2]} ${title}`);
      card.querySelector(".pmt-artwork-panel")?.setAttribute("aria-label", title);
      card.querySelector(".pmt-artwork-close")?.setAttribute("aria-label", copy()[3]);
    }

    function prepareCards() {
      for (const host of hosts) {
        host.classList.toggle('pmt-artwork-grid', enabled);
        for (const card of cardsIn(host)) {
        if (enabled && !card.classList.contains("media-artwork-card")) {
          const poster = card.querySelector(":scope > .poster, :scope > .recommendation-poster");
          const children = [...card.children];
          const content = children.filter(node => node !== poster);
          if (!poster || !content.length) continue;
          originalChildren.set(card, children);
          const trigger = document.createElement("button");
          trigger.type = "button";
          trigger.className = "pmt-artwork-trigger";
          trigger.setAttribute("aria-expanded", "false");
          const panel = document.createElement("div");
          panel.id = `pmt-artwork-panel-${++panelSequence}`;
          panel.className = "pmt-artwork-panel";
          panel.setAttribute("role", "region");
          panel.setAttribute("aria-hidden", "true");
          panel.inert = true;
          trigger.setAttribute("aria-controls", panel.id);
          poster.replaceWith(trigger);
          trigger.append(poster);
          const close = document.createElement("button");
          close.type = "button";
          close.className = "pmt-artwork-close";
          close.innerHTML = '<svg aria-hidden="true"><use href="#icon-close"></use></svg>';
          panel.append(...content, close);
          card.append(panel);
          card.classList.add("media-artwork-card");
        } else if (!enabled && card.classList.contains("media-artwork-card")) {
          const trigger = card.querySelector(".pmt-artwork-trigger");
          const panel = card.querySelector(".pmt-artwork-panel");
          // Preserve node identity, order, and existing action listeners.
          const poster = trigger.firstElementChild;
          const children = originalChildren.get(card) || [poster, ...panel.children].filter(node => !node.classList.contains('pmt-artwork-close'));
          for (const node of children) card.append(node.isConnected ? node : poster);
          trigger.remove();
          panel.remove();
          originalChildren.delete(card);
          card.classList.remove("media-artwork-card", "pmt-reveal-open", "pmt-reveal-restored");
        }
        if (enabled) syncLabels(card);
        }
      }
      if (activeCard && !activeCard.isConnected) closePanel();
    }

    // Never resubmit the editor or discard
    // unsaved fields when changing an episode counter.
    const detailDialog = document.querySelector('#entry-dialog');
    const detailArt = document.querySelector('#entry-dialog-art');
    const detailFacts = document.querySelector('#entry-overview-facts');
    const descriptions = new WeakMap();
    let descriptionSequence = 0;
    function refreshDescription() {
      const paragraph = detailFacts?.querySelector('.entry-description > p');
      if (!paragraph) return;
      let saved = descriptions.get(paragraph);
      const key = `${state.currentEntry?.id}:${paragraph.textContent}`;
      if (!saved || saved.key !== key) {
        saved = {key, expanded: false};
        descriptions.set(paragraph, saved);
      }
      paragraph.classList.toggle('pmt-description-collapsed', !saved.expanded);
      const lineHeight = parseFloat(getComputedStyle(paragraph).lineHeight) || 20;
      const long = paragraph.scrollHeight > lineHeight * 5 + 2;
      let button = paragraph.parentElement.querySelector('.pmt-description-toggle');
      if (!long) {
        paragraph.classList.remove('pmt-description-collapsed');
        button?.remove();
        return;
      }
      if (!button) {
        if (!paragraph.id) paragraph.id = `pmt-description-${++descriptionSequence}`;
        button = document.createElement('button');
        button.type = 'button';
        button.className = 'quiet pmt-description-toggle';
        button.setAttribute('translate', 'no');
        button.setAttribute('aria-controls', paragraph.id);
        button.addEventListener('click', () => {
          descriptions.get(paragraph).expanded = !descriptions.get(paragraph).expanded;
          refreshDescription();
        });
        paragraph.after(button);
      }
      button.setAttribute('aria-expanded', String(saved.expanded));
      const label = copy()[saved.expanded ? 5 : 4];
      if (button.textContent !== label) button.textContent = label;
    }
    function refreshDetails() {
      if (!detailDialog || !state.currentEntry) return;
      detailDialog.classList.add('media-details');
      detailArt.querySelector('.status-chip')?.remove();
      const entry = state.currentEntry;
      const html = episodeProgressHtml(entry);
      let host = detailArt.querySelector('.pmt-detail-progress');
      if (!html) { host?.remove(); refreshDescription(); return; }
      if (!host) {
        host = document.createElement('div');
        host.className = 'pmt-detail-progress';
        detailArt.querySelector(':scope > div')?.append(host);
      }
      const key = JSON.stringify([entry.id, entry.episode_progress, state.interfaceLanguage]);
      if (host.dataset.progressKey !== key) {
        host.dataset.progressKey = key;
        host.innerHTML = html;
      }
      refreshDescription();
    }
    detailArt?.addEventListener('click', async event => {
      const button = event.target.closest('.pmt-detail-progress [data-episode-step]');
      if (!button || button.disabled) return;
      const host = button.closest('.pmt-detail-progress');
      const progress = button.closest('[data-episode-progress]');
      const entryId = state.currentEntry.id;
      const step = Number(button.dataset.episodeStep);
      const next = Math.min(Math.max(Number(progress.dataset.watched) + step, 0), Number(progress.dataset.total));
      const statusControl = document.querySelector('#entry-status');
      const countControl = document.querySelector('#entry-count');
      const previous = state.currentEntry;
      host.querySelectorAll('button').forEach(control => { control.disabled = true; });
      host.setAttribute('aria-busy', 'true');
      try {
        const updated = await api(`/api/entries/${entryId}`, {method: 'PATCH', body: JSON.stringify({episode_progress_count: next})});
        rememberDisplayEntry(updated);
        for (const flag of ['currentlyWatchingLoaded', 'activeShowsLoaded', 'rankingsLoaded', 'listsLoaded']) state[flag] = false;
        document.querySelectorAll('.entry-card[data-entry]').forEach(card => {
          if (card.dataset.entry === entryId) window.replaceEntryCard(card, updated);
        });
        if (state.currentEntry?.id === entryId) {
          state.currentEntry = updated;
          if (statusControl.value === previous.status) statusControl.value = updated.status;
          if (countControl.value === String(previous.view_count)) countControl.value = updated.view_count;
          refreshDetails();
          const focusTarget = detailArt.querySelector(`[data-episode-step='${step}']:not(:disabled)`)
            || detailArt.querySelector('[data-episode-step]:not(:disabled)');
          if (detailDialog.open) focusTarget?.focus({preventScroll: true});
        }
      } catch (error) {
        toast(error.message);
        delete host.dataset.progressKey;
        if (state.currentEntry?.id === entryId) refreshDetails();
      } finally { host.removeAttribute('aria-busy'); }
    });
    const detailObserver = new MutationObserver(refreshDetails);
    if (detailArt) detailObserver.observe(detailArt, {childList: true, subtree: true});
    if (detailFacts) detailObserver.observe(detailFacts, {childList: true, subtree: true, characterData: true});
    if (detailDialog) detailObserver.observe(detailDialog, {attributes: true, attributeFilter: ['open']});
    if (detailFacts && typeof ResizeObserver === 'function') new ResizeObserver(refreshDescription).observe(detailFacts);
    const saveEpisodePreference = window.saveEpisodeProgressPreference;
    if (typeof saveEpisodePreference === 'function') window.saveEpisodeProgressPreference = async function(...args) {
      const owner = state.currentUser?.id || 'local';
      const result = await saveEpisodePreference.apply(this, args);
      if (owner !== (state.currentUser?.id || 'local')) return result;
      // The base preference refreshes Library/Watching only. Apply it to any
      // already-loaded list/active tiles too, without fetching more metadata.
      hosts.forEach(host => cardsIn(host).forEach(card => {
        const entry = card.dataset.entry && tileSnapshot().get(card.dataset.entry);
        if (entry) window.replaceEntryCard(card, entry);
      }));
      refreshDetails();
      return result;
    };

    const setting = document.createElement("label");
    setting.className = "media-artwork-setting pmt-artwork-reveal-setting";
    setting.innerHTML = '<input id="artwork-reveal" type="checkbox"><span translate="no"><strong></strong><i class="help-tip" tabindex="0">?</i></span>';
    const input = setting.querySelector("input");
    const viewSetting = document.createElement('label');
    viewSetting.className = 'media-artwork-setting pmt-tile-view-count-setting';
    viewSetting.innerHTML = '<input id="tile-view-counts" type="checkbox"><span translate="no"><strong></strong><i class="help-tip" tabindex="0">?</i></span>';
    const viewInput = viewSetting.querySelector('input');
    function setViewCounts(value) {
      showViewCounts = Boolean(value);
      viewInput.checked = showViewCounts;
      document.documentElement.dataset.pmtTileViewCounts = String(showViewCounts);
      try { localStorage.setItem(viewCountsKey, String(showViewCounts)); } catch (_) { /* Session-only fallback. */ }
    }
    viewInput.addEventListener('change', () => {
      setViewCounts(viewInput.checked);
      queueAppearanceSave({show_tile_view_counts: showViewCounts}, "Appearance changes save automatically.");
    });
    setViewCounts(showViewCounts);
    const anchor = document.querySelector("#show-episode-progress")?.closest("label");
    const displayOptions = document.createElement('div');
    displayOptions.className = 'media-artwork-pair tile-display-options';
    if (anchor) {
      anchor.replaceWith(displayOptions);
      displayOptions.append(anchor, viewSetting, setting);
    }
    bindHelpTips(displayOptions);
    function refreshCopy() {
      setting.querySelector("strong").textContent = copy()[0];
      viewSetting.querySelector('strong').textContent = copy()[6];
      for (const [option, text] of [[setting, copy()[1]], [viewSetting, copy()[7]]]) {
        option.querySelector('.help-tip').dataset.tip = text;
        option.querySelector('.help-tip').setAttribute('aria-label', text);
      }
      for (const [selector, original] of [
        ['#media-artwork-tint', 'Adds a subtle colour atmosphere to each media tile.'],
        ['#media-artwork-full-color', 'Carries the poster colours across the tile under a readability gradient.']
      ]) {
        const control = document.querySelector(selector);
        const tip = control?.closest('label').querySelector('.help-tip');
        const text = enabled ? copy()[8] : translatedText(original);
        if (tip) { tip.dataset.tip = text; tip.setAttribute('aria-label', text); }
        if (enabled) control?.setAttribute('aria-description', text);
        else control?.removeAttribute('aria-description');
      }
      hosts.forEach(host => host.querySelectorAll(".media-artwork-card").forEach(syncLabels));
      refreshDescription();
      refreshDetails();
    }
    function setMode(value) {
      closePanel();
      enabled = Boolean(value);
      input.checked = enabled;
      document.documentElement.dataset.pmtArtworkReveal = String(enabled);
      try { localStorage.setItem(storageKey, String(enabled)); } catch (_) { /* Session-only fallback. */ }
      syncMediaArtworkPreferences();
      refreshCopy();
      prepareCards();
    }
    input.addEventListener("change", () => {
      setMode(input.checked);
      queueAppearanceSave({artwork_reveal: enabled}, "Appearance changes save automatically.");
    });
    // The server/file preference is authoritative, including after account changes.
    window.PMTMediaTiles = {
      reset() {
        closeEpisodeMenus();
        tileEntries.clear();
        setMode(false);
        setViewCounts(false);
      },
      applyPreferences(data) {
        setViewCounts(Boolean(data.show_tile_view_counts));
        if (enabled !== Boolean(data.artwork_reveal)) setMode(Boolean(data.artwork_reveal));
      }
    };
    if (renderLanguage) window.applyInterfaceLanguage = function(...args) {
      const result = renderLanguage.apply(this, args);
      refreshCopy();
      return result;
    };
    refreshCopy();
    setMode(enabled);
    const tileObserver = new MutationObserver(prepareCards);
    hosts.forEach(host => tileObserver.observe(host, {childList: true, subtree: true}));

    const stationaryHover = event => hoverBlockedAt && event.clientX === hoverBlockedAt.x && event.clientY === hoverBlockedAt.y;
    document.addEventListener("pointermove", event => {
      if (!lastPointer || event.clientX !== lastPointer.x || event.clientY !== lastPointer.y) {
        lastInput = "pointer";
        hoverBlockedAt = null;
      }
      lastPointer = {x: event.clientX, y: event.clientY};
    }, true);
    document.addEventListener("pointerover", event => {
      if (event.pointerType === "touch" || !matchMedia("(hover: hover)").matches) return;
      if (stationaryHover(event)) return;
      const card = event.target.closest(".media-artwork-card");
      if (!card) return;
      // A replaced card may emit a synthetic boundary event while repainting.
      // Do not switch to the poster underneath the still-open details panel.
      if (activeCard && activeCard !== card) {
        const bounds = activeCard.querySelector(".pmt-artwork-panel").getBoundingClientRect();
        if (event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom) return;
      }
      lastInput = "pointer";
      hoveredCard = card;
      openPanel(card);
    });
    document.addEventListener("pointerout", event => {
      // Lifting a finger is not leaving a hover target: tap-open stays open.
      if (event.pointerType === "touch" || !matchMedia("(hover: hover)").matches) return;
      if (stationaryHover(event)) return;
      const card = event.target.closest(".media-artwork-card");
      if (!card || card.contains(event.relatedTarget)) return;
      hoveredCard = null;
      clearTimeout(dismissTimer);
      dismissTimer = setTimeout(() => {
        if (activeCard === card && !(lastInput === "keyboard" && card.querySelector(".pmt-artwork-panel")?.contains(document.activeElement))) closePanel();
      }, 100);
    });
    document.addEventListener("focusin", event => {
      const card = event.target.closest(".media-artwork-card");
      if (!restoringFocus && lastInput === "keyboard") {
        hoverBlockedAt = lastPointer;
        openPanel(card);
      }
    });
    document.addEventListener("focusout", event => {
      const progress = event.target.closest('[data-episode-progress]');
      if (progress && !progress.contains(event.relatedTarget) && !event.target.disabled) {
        requestAnimationFrame(() => {
          if (progress.isConnected && !progress.contains(document.activeElement)) setEpisodeMenu(progress, false);
        });
      }
      const card = event.target.closest(".media-artwork-card");
      if (!card || card.contains(event.relatedTarget)) return;
      // A pending save disables its button, which blurs it on touch devices.
      // That is not navigation out of the panel; replacement restores focus.
      if (!event.relatedTarget && event.target.disabled
          && event.target.matches('[data-favorite-toggle], [data-episode-step]')) return;
      // Let the browser finish moving focus before hiding its destination.
      requestAnimationFrame(() => {
        if (activeCard === card && hoveredCard !== card && !card.contains(document.activeElement)) closePanel();
      });
    });
    document.addEventListener("click", event => {
      const toggle = event.target.closest('[data-episode-toggle]');
      if (toggle) {
        const progress = toggle.closest('[data-episode-progress]');
        const open = toggle.getAttribute('aria-expanded') !== 'true';
        closeEpisodeMenus(progress);
        setEpisodeMenu(progress, open);
        return;
      }
      const card = event.target.closest(".media-artwork-card");
      if (!card) return;
      if (event.target.closest(".pmt-artwork-close")) closePanel(true);
      else if (event.target.closest(".pmt-artwork-trigger")) {
        if (activeCard === card) closePanel(); else openPanel(card);
      }
    });
    document.addEventListener("pointerdown", event => {
      lastInput = "pointer";
      lastPointer = {x: event.clientX, y: event.clientY};
      closeEpisodeMenus(event.target.closest('[data-episode-progress]'));
      if (activeCard && !activeCard.contains(event.target)) closePanel();
    }, true);
    document.addEventListener("keydown", event => {
      lastInput = "keyboard";
      if (event.key === "Escape" && document.querySelector('[data-episode-toggle][aria-expanded="true"]')) {
        closeEpisodeMenus(null, true);
        event.preventDefault();
        return;
      }
      if (event.key === "Escape" && activeCard && !document.querySelector("dialog[open]")) {
        closePanel(true);
        event.preventDefault();
      }
    });
    window.addEventListener("resize", () => { closeEpisodeMenus(); closePanel(); });
    document.addEventListener('wheel', event => {
      // Preserve pinch-to-zoom. Mouse/trackpad scrolling over a reveal belongs
      // to the page, not to the small details panel beneath the pointer.
      if (event.ctrlKey || event.defaultPrevented || !event.cancelable) return;
      const panel = event.target.closest?.('.pmt-artwork-panel');
      if (!panel || !panel.closest('.pmt-reveal-open')) return;
      let scrollTarget = panel.closest('.media-artwork-card')?.parentElement;
      while (scrollTarget && scrollTarget !== document.body) {
        const style = getComputedStyle(scrollTarget);
        if (/(auto|scroll)/.test(style.overflowY) && scrollTarget.scrollHeight > scrollTarget.clientHeight) break;
        scrollTarget = scrollTarget.parentElement;
      }
      if (!scrollTarget || scrollTarget === document.body) scrollTarget = document.scrollingElement;
      const scale = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? scrollTarget.clientHeight : 1;
      event.preventDefault();
      scrollTarget.scrollBy({left: event.deltaX * scale, top: event.deltaY * scale, behavior: 'instant'});
    }, {passive: false});
    window.addEventListener("scroll", event => {
      // Nested controls can scroll while browser focus is being restored.
      // The panel travels with its poster; dismiss only after it leaves the page viewport.
      if (activeCard && event.target === document) {
        const bounds = activeCard.getBoundingClientRect();
        if (bounds.bottom < 0 || bounds.top > innerHeight) closePanel();
      }
    }, true);
    document.addEventListener("visibilitychange", () => { if (document.hidden) closePanel(); });
  }, {once: true});
})();
