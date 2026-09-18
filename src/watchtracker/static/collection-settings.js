/* One system settings surface, with independent collection-specific preferences. */
(() => {
  const domains = ["music", "books"];
  const options = [
    ["artwork_tint", "Artwork tint"],
    ["artwork_full_color", "Full-colour blend"],
    ["artwork_reveal", "Artwork reveal"],
    ["show_counts", "Show completion counts"]
  ];
  let installed = false;
  let preferences = {};
  let accountRevision = 0;
  const pending = new Set();
  const text = value => translatedText(value);
  const controlId = key => key.replaceAll("_", "-");

  function refreshControls() {
    for (const domain of domains) {
      const reveal = Boolean(preferences[`${domain}_artwork_reveal`]);
      for (const [option] of options) {
        const key = `${domain}_${option}`;
        const input = document.getElementById(controlId(key));
        if (!input) continue;
        input.checked = Boolean(preferences[key]);
        input.disabled = pending.has(key) || (reveal && ["artwork_tint", "artwork_full_color"].includes(option));
        if (reveal && ["artwork_tint", "artwork_full_color"].includes(option)) input.setAttribute("aria-describedby", `${domain}-appearance-hint`);
        else input.removeAttribute("aria-describedby");
      }
      const hint = document.getElementById(`${domain}-appearance-hint`);
      if (hint) hint.textContent = text(reveal
        ? "Turn off Artwork reveal to use artwork tint or full-colour blend. Your choices are kept."
        : "Only this collection changes. Rankings always keep their information visible.");
    }
    window.PMTMusic?.applyPreferences(preferences);
  }

  function applyPreferences(data) {
    for (const domain of domains) for (const [option] of options) {
      const key = `${domain}_${option}`;
      if (!pending.has(key)) preferences[key] = Boolean(data[key]);
    }
    refreshControls();
  }

  function savePreference(key, value, domain) {
    const revision = accountRevision;
    const previous = Boolean(preferences[key]);
    preferences[key] = value;
    pending.add(key);
    refreshControls();
    const status = document.getElementById(`${domain}-appearance-state`);
    showMessage(status, text("Saving appearance…"));
    state.appearanceSave = state.appearanceSave.catch(() => {}).then(async () => {
      if (revision !== accountRevision) return;
      try {
        await api("/api/settings/general", {method: "PUT", body: JSON.stringify({[key]: value})});
        if (revision !== accountRevision) return;
        showMessage(status, text("Appearance changes save automatically."));
      } catch (error) {
        if (revision !== accountRevision) return;
        preferences[key] = previous;
        showMessage(status, error.message, true);
      } finally {
        if (revision === accountRevision) { pending.delete(key); refreshControls(); }
      }
    });
  }

  function selectScreenSection(name) {
    if (!["appearance", "metadata", "integrations"].includes(name)) name = "appearance";
    document.querySelectorAll("[data-screen-settings-tab]").forEach(button => {
      button.setAttribute("aria-pressed", String(button.dataset.screenSettingsTab === name));
    });
    document.querySelectorAll("[data-screen-settings-panel]").forEach(panel => {
      panel.hidden = panel.dataset.screenSettingsPanel !== name;
    });
    if (name === "integrations") loadIntegrations();
  }

  function resolveTab(name) {
    if (name === "metadata" || name === "integrations") {
      selectScreenSection(name);
      return "screen";
    }
    return name;
  }

  function install() {
    if (installed) return;
    installed = true;
    const dialog = document.getElementById("settings-dialog");
    const screen = document.createElement("section");
    screen.className = "settings-panel collection-settings-panel";
    screen.dataset.settingsPanel = "screen";
    screen.setAttribute("role", "tabpanel");
    screen.hidden = true;
    screen.innerHTML = '<h3>Screen</h3><div class="segmented text-segmented screen-settings-nav" role="group" aria-label="Screen settings"><button type="button" data-screen-settings-tab="appearance" aria-pressed="true">Appearance</button><button type="button" data-screen-settings-tab="metadata" aria-pressed="false">Metadata</button><button type="button" data-screen-settings-tab="integrations" aria-pressed="false">Integrations</button></div><section data-screen-settings-panel="appearance"><h4>Media tiles</h4><div id="screen-tile-settings"></div><div id="screen-rating-settings"></div></section>';
    const general = dialog.querySelector('[data-settings-panel="general"]');
    general.after(screen);
    const tileHost = screen.querySelector("#screen-tile-settings");
    general.querySelectorAll(".media-artwork-pair").forEach(node => tileHost.append(node));
    // media-tiles.js normally wraps this in its display-option group first.
    const episode = general.querySelector(".episode-display-setting");
    if (episode) tileHost.append(episode);
    const advanced = general.querySelector(".general-advanced-ratings");
    if (advanced) screen.querySelector("#screen-rating-settings").append(advanced);
    const screenSave = document.createElement("p");
    screenSave.className = "save-state";
    screenSave.setAttribute("aria-live", "polite");
    tileHost.after(screenSave);
    const globalSave = document.getElementById("appearance-state");
    new MutationObserver(() => { screenSave.textContent = globalSave.textContent; }).observe(globalSave, {childList: true, subtree: true, characterData: true});
    screenSave.textContent = globalSave.textContent;
    for (const name of ["metadata", "integrations"]) {
      const panel = dialog.querySelector(`[data-settings-panel="${name}"]`);
      panel.removeAttribute("data-settings-panel");
      panel.dataset.screenSettingsPanel = name;
      panel.classList.remove("settings-panel");
      panel.id = `settings-panel-${name}`;
      panel.setAttribute("role", "region");
      panel.setAttribute("aria-label", name === "metadata" ? "Metadata" : "Integrations");
      screen.append(panel);
    }
    const region = document.getElementById("general-region");
    const regionLabel = region.closest("label");
    region.setAttribute("form", "general-settings-form");
    const regionArea = document.createElement("div");
    regionArea.className = "screen-region-setting";
    regionArea.append(regionLabel);
    const regionStatus = document.createElement("p");
    regionStatus.className = "message";
    regionStatus.setAttribute("role", "status");
    regionArea.append(regionStatus);
    screen.querySelector('[data-screen-settings-panel="metadata"]').prepend(regionArea);
    region.addEventListener("change", async () => {
      const value = region.value;
      region.disabled = true;
      showMessage(regionStatus, text("Saving…"));
      try {
        await api("/api/settings/general", {method: "PUT", body: JSON.stringify({region: value})});
        if (state.generalSettingsSnapshot) state.generalSettingsSnapshot.region = value;
        showMessage(regionStatus, text("Saved"));
      } catch (error) {
        region.value = state.generalSettingsSnapshot?.region || "US";
        showMessage(regionStatus, error.message, true);
      } finally { region.disabled = false; updateGeneralSettingsState(); }
    });
    for (const domain of domains) {
      const panel = document.createElement("section");
      panel.className = "settings-panel collection-settings-panel";
      panel.dataset.settingsPanel = domain;
      panel.setAttribute("role", "tabpanel");
      panel.hidden = true;
      const title = domain === "music" ? "Music" : "Books";
      panel.innerHTML = `<h3>${title}</h3><div class="segmented text-segmented screen-settings-nav" role="group" aria-label="${title} settings">${["Appearance", "Metadata", "Integrations"].map(label => `<button type="button" data-collection-settings-tab="${label.toLowerCase()}" aria-pressed="${label === "Appearance"}">${label}</button>`).join("")}</div><section data-collection-settings-panel="appearance"><h4>Media tiles</h4><div class="collection-appearance-options">${options.map(([option, label]) => `<label class="media-artwork-setting"><input id="${controlId(`${domain}_${option}`)}" type="checkbox"><span><strong>${label}</strong></span></label>`).join("")}</div><p id="${domain}-appearance-hint" class="hint"></p><p id="${domain}-appearance-state" class="message" role="status"></p></section><section data-collection-settings-panel="metadata" hidden><h4>Metadata</h4><div class="collection-provider-copy"></div></section><section data-collection-settings-panel="integrations" hidden><h4>Integrations</h4><p>Manual tracking only. Playback, listening history and account synchronization are not enabled.</p></section>`;
      panel.querySelectorAll("[data-collection-settings-tab]").forEach(button => button.addEventListener("click", () => {
        panel.querySelectorAll("[data-collection-settings-tab]").forEach(tab => tab.setAttribute("aria-pressed", String(tab === button)));
        panel.querySelectorAll("[data-collection-settings-panel]").forEach(section => { section.hidden = section.dataset.collectionSettingsPanel !== button.dataset.collectionSettingsTab; });
      }));
      const copy = panel.querySelector(".collection-provider-copy");
      copy.innerHTML = domain === "music"
        ? '<p>MusicBrainz supplies album editions, artists, genres and tracklists. Cover Art Archive supplies available covers.</p><p><a href="https://musicbrainz.org" target="_blank" rel="noopener noreferrer" data-external>MusicBrainz</a> · <a href="https://coverartarchive.org" target="_blank" rel="noopener noreferrer" data-external>Cover Art Archive</a></p>'
        : '<p>Open Library supplies book editions, authors, subjects, ISBNs and available covers. Subjects are not automatically classified as subgenres.</p><p><a href="https://openlibrary.org" target="_blank" rel="noopener noreferrer" data-external>Open Library</a></p>';
      const hint = document.createElement("p");
      hint.className = "hint";
      hint.textContent = "No API key is needed. Search sends only the title or creator you enter. Review the edition before saving; missing information can be entered manually.";
      copy.append(hint);
      screen.after(panel);
      panel.querySelectorAll("input").forEach(input => input.addEventListener("change", () => {
        savePreference(input.id.replaceAll("-", "_"), input.checked, domain);
      }));
    }
    screen.querySelectorAll("[data-screen-settings-tab]").forEach(button => button.addEventListener("click", () => selectScreenSection(button.dataset.screenSettingsTab)));
    selectScreenSection("appearance");
    refreshControls();
  }

  function reset() {
    accountRevision++;
    pending.clear();
    preferences = {};
    refreshControls();
  }
  window.PMTCollectionSettings = {install, applyPreferences, resolveTab, reset, refreshLabels: refreshControls};
})();
