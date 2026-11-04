/* Collection-bound durable metadata maintenance; no matching heuristics. */
window.PMTCollectionMaintenance = {create({getMode, active, html, icon, cover, images, activate, openEditor, queueMetadataRefresh}) {
  let fillTimer = null, fillDomain = null, fillStatus = null, fillRevision = 0;
  let fillReviewOffset = 0;
  const review = window.PMTCollectionReview.create({html, icon, cover, images,
    changed: domain => { if (getMode() === domain) queueMetadataRefresh(); pollFill(domain); },
    edit: async (domain, id) => { if (getMode() !== domain) await activate(domain); openEditor(id); }
  });
  async function cacheInfo(host, domain) {
    try {
      const [data, coverage] = await Promise.all([window.api("/api/collections/cache"), window.api(`/api/collections/${domain}/metadata-coverage`)]);
      host.querySelector('[data-cache-clear]').hidden = !data.can_clear;
      host.querySelector('[data-cache-summary]').textContent = data.can_clear ? `${data.files} ${translatedText("cached covers")} · ${(data.bytes / 1048576).toFixed(1)} MiB` : translatedText("Downloaded covers are managed by the server account.");
      host.querySelector('[data-coverage-summary]').textContent = `${coverage.linked} / ${coverage.total} ${translatedText("catalog-linked entries")} · ${coverage.fields.genres} ${translatedText("with genres")} · ${coverage.local_images} ${translatedText("covers stored locally")}`;
    } catch (_) { /* Cache diagnostics do not block settings. */ }
  }
  function renderFill(data) {
    fillStatus = data;
    const summary = `${data.completed} / ${data.total} · ${data.updated} ${translatedText("Metadata filled")} · ${data.review_count} ${translatedText("Needs review")}`;
    $("#collection-fill-progress").max = Math.max(1, data.total);
    $("#collection-fill-progress").value = data.completed;
    $("#collection-fill-progress").hidden = !data.total;
    $("#collection-fill-summary").textContent = data.total ? summary : translatedText(data.run_id ? "No missing metadata to check." : "Start a check to find missing metadata.");
    $("#collection-fill-start").disabled = Boolean(data.pending);
    $("#collection-fill-wikidata").disabled = Boolean(data.pending);
    $("#collection-fill-retry").hidden = Boolean(data.pending) || !data.review_count;
    $("#collection-fill-retry").disabled = Boolean(data.pending);
    $("#collection-fill-more").hidden = !data.review_has_more;
    $("#collection-fill-previous").hidden = !fillReviewOffset;
    $("#collection-fill-cancel").hidden = !data.pending;
    const reasons = {review: "No confident match", duplicate: "Matching entry already exists", changed: "Entry changed during lookup", incomplete: "Catalog artwork is missing", unavailable: "Catalog unavailable; try again"};
    $("#collection-fill-review").innerHTML = (data.review || []).map(row => `<button type="button" class="quiet collection-fill-review-row" data-fill-review="${html(row.id)}"><span translate="no">${html(row.title)}</span><small>${html(translatedText(reasons[row.reason] || reasons.unavailable))}</small></button>`).join("");
    const banner = $(`[data-collection-fill-banner="${fillDomain}"]`);
    if (banner) banner.innerHTML = data.total ? `<button type="button" class="quiet" data-open-fill>${html(translatedText(data.pending ? "Finding metadata…" : data.cancelled ? "Metadata check stopped" : "Metadata check finished"))} · ${html(summary)}</button>` : "";
  }
  async function pollFill(domain) {
    clearTimeout(fillTimer);
    const revision = ++fillRevision;
    try {
      const data = await window.api(`/api/collections/${domain}/metadata-fill${fillReviewOffset ? `?review_offset=${fillReviewOffset}` : ""}`);
      if (revision !== fillRevision) return;
      const previous = fillDomain === domain ? fillStatus : null;
      fillDomain = domain; renderFill(data);
      if (previous && data.updated !== previous.updated && getMode() === domain) queueMetadataRefresh();
      if (data.pending) fillTimer = setTimeout(() => pollFill(domain), 1800);
    } catch (error) {
      if (revision !== fillRevision) return;
      showMessage($("#collection-fill-summary"), error.message, true);
      // Transient offline errors must not make background work appear lost.
      if (getMode() === domain || $("#collection-fill-dialog").open) fillTimer = setTimeout(() => pollFill(domain), 5000);
    }
  }
  function openFill(domain = getMode()) {
    if (!["music", "books"].includes(domain)) return;
    fillDomain = domain; fillStatus = null; fillReviewOffset = 0;
    $("#collection-fill-wikidata-option").hidden = domain !== "music";
    $("#collection-fill-heading").textContent = `${translatedText("Fill missing metadata")} · ${translatedText(domain === "books" ? "Books" : "Music")}`;
    $("#collection-fill-review").replaceChildren();
    $("#collection-fill-start").disabled = true;
    showMessage($("#collection-fill-summary"), translatedText("Loading…"));
    openDialog($("#collection-fill-dialog")); pollFill(domain);
  }
  function installMetadataFill() {
    window.PMTCollectionSettings?.install();
    for (const domain of ["music", "books"]) {
      const host = $(`[data-settings-panel="${domain}"] [data-collection-settings-panel="metadata"]`);
      const section = document.createElement("section"); section.className = "collection-metadata-maintenance";
      section.innerHTML = `<h4>${html(translatedText("Library maintenance"))}</h4><button type="button" id="${domain === "music" ? "collection-fill-open" : "books-fill-open"}" class="quiet" data-collection-fill-open="${domain}">${html(translatedText("Fill missing metadata"))}</button><div data-collection-fill-banner="${domain}" role="status"></div>`;
      host.append(section);
      section.querySelector("button").addEventListener("click", () => openFill(domain));
      section.querySelector("[data-collection-fill-banner]").addEventListener("click", () => openFill(domain));
      const cache = document.createElement("div"); cache.className = "collection-cache-controls";
      cache.innerHTML = `<p data-coverage-summary role="status"></p><p class="hint">${html(translatedText("A catalog link is not a verified cover. Uncached images have not been checked yet."))}</p><p data-cache-summary role="status"></p><button type="button" class="quiet" data-cache-clear hidden>${html(translatedText("Clear downloaded cover cache"))}</button><p class="hint">${html(translatedText("Only downloaded covers are removed. Uploaded artwork, your library and backups are kept. Covers download again when needed."))}</p>`;
      section.append(cache);
      cache.querySelector("button").addEventListener("click", async event => {
        const button = event.currentTarget;
        if (!await confirmAction(translatedText("Clear downloaded cover cache"), translatedText("Only downloaded covers are removed. Uploaded artwork, your library and backups are kept. Covers download again when needed."), translatedText("Clear cache"))) return;
        button.disabled = true;
        try { await window.api("/api/collections/cache", {method: "DELETE"}); await cacheInfo(cache, domain); }
        catch (error) { showMessage(cache.querySelector('[data-cache-summary]'), error.message, true); }
        finally { button.disabled = false; }
      });
      host.parentElement.querySelector('[data-collection-settings-tab="metadata"]').addEventListener("click", () => { pollFill(domain); cacheInfo(cache, domain); });
    }
    const dialog = document.createElement("dialog"); dialog.id = "collection-fill-dialog"; dialog.className = "collection-import-dialog";
    dialog.innerHTML = `<form method="dialog" class="dialog-head"><h2 id="collection-fill-heading">${html(translatedText("Fill missing metadata"))}</h2><button class="icon-button dialog-close" aria-label="${html(translatedText("Close"))}">${icon("close")}</button></form><p>${html(translatedText("Sends titles and artists to MusicBrainz, or titles, authors and ISBNs to Open Library. No account is required. Uncertain matches stay unchanged for review."))}</p><p class="hint">${html(translatedText("Ratings, notes, progress and uploaded artwork are kept. Work continues in the background and resumes when PMT restarts."))}</p><progress id="collection-fill-progress" max="1" value="0" aria-label="${html(translatedText("Metadata progress"))}"></progress><p id="collection-fill-summary" role="status" aria-live="polite"></p><div class="dialog-footer"><button id="collection-fill-start" type="button">${html(translatedText("Check missing metadata"))}</button><button id="collection-fill-cancel" type="button" class="quiet" hidden>${html(translatedText("Stop checking"))}</button></div><div id="collection-fill-review"></div>`;
    document.body.append(dialog);
    const aliases = document.createElement("label"); aliases.id = "collection-fill-wikidata-option"; aliases.className = "check";
    aliases.innerHTML = `<input id="collection-fill-wikidata" type="checkbox" checked><span>${html(translatedText("Use Wikidata aliases for unresolved albums (optional)"))}<small>${html(translatedText("Sends unresolved titles to Wikidata to check album and artist identities. No notes or ratings are sent."))}</small></span>`;
    $("#collection-fill-progress").before(aliases);
    const providerCopy = $('[data-settings-panel="music"] .collection-provider-copy');
    const aliasInfo = document.createElement("p"); aliasInfo.className = "hint";
    aliasInfo.innerHTML = `${html(translatedText("Optional Wikidata aliases help identify albums in other languages; MusicBrainz still supplies the selected edition."))} <a href="https://www.wikidata.org/wiki/Wikidata:Data_access" target="_blank" rel="noopener noreferrer" data-external>Wikidata</a>`;
    providerCopy.append(aliasInfo);
    const retry = document.createElement("button"); retry.id = "collection-fill-retry"; retry.type = "button"; retry.className = "quiet"; retry.hidden = true; retry.textContent = translatedText("Retry unresolved entries");
    $("#collection-fill-start").after(retry);
    const more = document.createElement("button"); more.id = "collection-fill-more"; more.type = "button"; more.className = "quiet"; more.hidden = true; more.textContent = translatedText("More entries to review");
    $("#collection-fill-review").after(more);
    more.addEventListener("click", () => { fillReviewOffset += 100; pollFill(fillDomain); });
    const previous = document.createElement("button"); previous.id = "collection-fill-previous"; previous.type = "button"; previous.className = "quiet"; previous.hidden = true; previous.textContent = translatedText("Previous");
    more.before(previous); previous.addEventListener("click", () => { fillReviewOffset = Math.max(0, fillReviewOffset - 100); pollFill(fillDomain); });
    const scope = document.createElement("label"); scope.textContent = translatedText("Check scope");
    scope.innerHTML += `<select id="collection-fill-scope">${[["all", "All missing fields"], ["identity", "Unresolved identities"], ["artwork", "Missing artwork"], ["optional", "Missing optional fields"], ["unavailable", "Previously unavailable"]].map(([value, text]) => `<option value="${value}">${html(translatedText(text))}</option>`).join("")}</select>`;
    $("#collection-fill-progress").before(scope);
    dialog.addEventListener("close", async () => {
      if (!state.importReturnToSettings) return;
      state.importReturnToSettings = false; await openSettings(); selectSettingsTab("data");
    });
    async function startCheck(event) {
      const button = event.currentTarget, domain = fillDomain; button.disabled = true;
      $("#collection-fill-start").disabled = true; retry.disabled = true;
      try {
        const data = await window.api(`/api/collections/${domain}/metadata-fill`, {method: "POST", body: JSON.stringify({language: state.interfaceLanguage || "en", scope: $("#collection-fill-scope").value, retry_review: button === retry, use_wikidata: domain === "music" && $("#collection-fill-wikidata").checked})});
        if (domain !== fillDomain) return;
        renderFill(data); if (data.pending) pollFill(domain);
      } catch (error) { if (domain === fillDomain) { $("#collection-fill-start").disabled = false; retry.disabled = false; showMessage($("#collection-fill-summary"), error.message, true); } }
    }
    $("#collection-fill-start").addEventListener("click", startCheck);
    retry.addEventListener("click", startCheck);
    $("#collection-fill-cancel").addEventListener("click", async event => {
      const button = event.currentTarget, domain = fillDomain, run = fillStatus?.run_id; if (!run) return;
      button.disabled = true;
      showMessage($("#collection-fill-summary"), translatedText("Stopping after the current lookup…"));
      try { await window.api(`/api/collections/${domain}/metadata-fill/${run}`, {method: "DELETE"}); await pollFill(domain); }
      catch (error) { showMessage($("#collection-fill-summary"), error.message, true); }
      finally { button.disabled = false; }
    });
    $("#collection-fill-review").addEventListener("click", async event => {
      const target = event.target.closest("[data-fill-review]"); if (!target) return;
      const domain = fillDomain; state.importReturnToSettings = false; dialog.close();
      review.open(domain, fillStatus.review, target.dataset.fillReview);
    });
    if (active()) pollFill(getMode());
  }
  function reset() { clearTimeout(fillTimer); fillRevision++; fillStatus = null; }
  return {openFill, pollFill, installMetadataFill, reset};
}};
