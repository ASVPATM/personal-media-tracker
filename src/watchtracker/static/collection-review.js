/* Explicit comparison and saved decisions, separate from automated matching. */
window.PMTCollectionReview = {create({html, icon, images, cover, changed, edit}) {
  let dialog, domain, entries = [], position = 0, current = null, selected = null, revision = 0, pending = false, request = null;
  const tr = text => html(translatedText(text));
  const endpoint = () => `/api/collections/${domain}/review/${entries[position].id}`;
  const message = (text, error = false) => showMessage(dialog.querySelector('[data-review-status]'), translatedText(text), error);
  const busy = value => { pending = value; dialog.setAttribute("aria-busy", String(value)); dialog.querySelectorAll("button:not(.dialog-close), input").forEach(node => { node.disabled = value; }); if (!value) { dialog.querySelector('[data-review-prev]').disabled = position === 0; dialog.querySelector('[data-review-next]').disabled = position === entries.length - 1; } };
  function facts(row, label) {
    const info = row.edition_info || {}, creator = row.artist || row.author;
    return `<section class="collection-review-facts"><h3>${tr(label)}</h3>${cover(row.cover_url || row.artwork_url, row.title)}<strong translate="no">${html(row.title)}</strong><span translate="no">${html(creator)}</span><small>${tr("Album / work year")} · ${html(info.original_year || info.first_release_year || "—")}</small><small>${tr("Edition year")} · ${html(row.year || "—")}</small><small translate="no">${html(info.name || row.variant || "")}</small><small>${html(row.provider_id || "")}</small></section>`;
  }
  async function show() {
    const value = ++revision; request?.abort(); request = new AbortController(); selected = null; current = null;
    dialog.querySelector('[data-review-results]').replaceChildren(); dialog.querySelector('[data-review-comparison]').replaceChildren();
    dialog.querySelector('[data-review-apply]').hidden = true;
    busy(true); message("Loading…");
    try {
      const data = await window.api(endpoint(), {signal: request.signal});
      if (value !== revision) return;
      current = data.entry;
      dialog.querySelector('[name="title"]').value = current.title;
      dialog.querySelector('[name="creator"]').value = current.artist || current.author;
      dialog.querySelector('[data-review-position]').textContent = `${position + 1} / ${entries.length}`;
      dialog.querySelector('[data-review-comparison]').innerHTML = facts(current, "Imported entry") + (data.duplicate ? facts(data.duplicate, "Existing matching entry") : "");
      dialog.querySelector('[data-review-duplicate]').hidden = !data.duplicate;
      dialog.querySelector('[data-review-duplicate]').onclick = () => { const id = data.duplicate.id; dialog.close(); edit(domain, id); };
      images(dialog); message("Check the title, credited creator and edition before applying.");
    } catch (error) { if (value === revision && error.name !== "AbortError") message(error.message, true); }
    finally { if (value === revision) { busy(false); dialog.querySelector('[data-review-prev]').disabled = position === 0; dialog.querySelector('[data-review-next]').disabled = position === entries.length - 1; } }
  }
  async function search(event) {
    event.preventDefault(); if (!current || pending) return;
    const value = ++revision, form = event.currentTarget;
    busy(true); message("Searching…"); selected = null; dialog.querySelector('[data-review-apply]').hidden = true;
    const params = new URLSearchParams({q: form.elements.title.value.trim(), creator: form.elements.creator.value.trim(), language: state.interfaceLanguage || "en"});
    try {
      const data = await window.api(`${endpoint()}/candidates?${params}`, {signal: request.signal});
      if (value !== revision) return;
      if (data.version !== current.version) throw new Error(translatedText("Entry changed during lookup"));
      dialog.querySelector('[data-review-results]').innerHTML = data.results.map((row, index) => `<button type="button" class="music-search-result search-result" data-review-candidate="${index}">${cover(row.artwork_url, row.title)}<span><strong translate="no">${html(row.title)}</strong><small translate="no">${html(row.artist || row.author)} · ${html(row.year || "—")}</small><small>${tr("Search suggestion — confirm identity")}</small></span></button>`).join("");
      dialog.querySelectorAll('[data-review-candidate]').forEach(button => button.addEventListener("click", () => choose(data.results[Number(button.dataset.reviewCandidate)])));
      images(dialog); message(data.results.length ? "Check the title, credited creator and edition before applying." : "No confident match");
    } catch (error) { if (value === revision && error.name !== "AbortError") message(error.message, true); }
    finally { if (value === revision) busy(false); }
  }
  async function choose(row) {
    const value = ++revision; busy(true); message("Loading…");
    try {
      const data = await window.api(`/api/${domain}/metadata/${encodeURIComponent(row.provider_id)}`, {signal: request.signal});
      if (value !== revision) return;
      selected = data;
      dialog.querySelector('[data-review-comparison]').innerHTML = facts(current, "Imported entry") + facts(selected, "Selected edition");
      dialog.querySelector('[data-review-apply]').hidden = false; images(dialog);
      message("Ratings, notes, progress and uploaded artwork are kept.");
    } catch (error) { if (value === revision && error.name !== "AbortError") message(error.message, true); }
    finally { if (value === revision) busy(false); }
  }
  async function decide(action) {
    if (!current || pending || (action === "apply" && !selected)) return;
    const value = ++revision, form = dialog.querySelector('[data-review-search]');
    const payload = {version: current.version, action, provider_id: selected?.provider_id || null};
    if (action === "spelling") {
      payload.title = form.elements.title.value.trim(); payload.creator = form.elements.creator.value.trim();
      const before = `${current.title} · ${current.artist || current.author}`, after = `${payload.title} · ${payload.creator}`;
      if (before === after || !await confirmAction(translatedText("Edit imported spelling"), `${before}\n→ ${after}`, translatedText("Save changes"))) return;
      if (value !== revision || !dialog.open) return;
    }
    busy(true); message("Saving…");
    try {
      const data = await window.api(endpoint(), {method: "POST", body: JSON.stringify(payload)});
      if (value !== revision) return;
      current = data.entry; changed(domain);
      if (action === "spelling") { await show(); return; }
      if (position + 1 < entries.length) { position++; await show(); }
      else { dialog.close(); toast(translatedText("Review decision saved")); }
    } catch (error) { if (value === revision) message(error.message, true); }
    finally { if (value === revision) busy(false); }
  }
  function install() {
    if (dialog) return;
    dialog = document.createElement("dialog"); dialog.id = "collection-review-dialog"; dialog.className = "collection-import-dialog collection-review-dialog";
    dialog.innerHTML = `<form method="dialog" class="dialog-head"><h2>${tr("Review metadata")}</h2><button class="icon-button dialog-close" aria-label="${tr("Close")}">${icon("close")}</button></form><div class="collection-review-navigation"><button type="button" data-review-prev>${tr("Previous")}</button><span data-review-position></span><button type="button" data-review-next>${tr("Next")}</button></div><div data-review-comparison class="collection-review-comparison"></div><form data-review-search class="collection-review-search"><label>${tr("Title")}<input name="title" maxlength="500" required></label><label>${tr("Credited creator")}<input name="creator" maxlength="500" required></label><button type="submit">${tr("Search")}</button><button type="button" data-review-spelling>${tr("Edit imported spelling")}</button></form><p role="status" aria-live="polite" data-review-status></p><div data-review-results></div><div class="dialog-footer"><button type="button" data-review-apply hidden>${tr("Use this edition")}</button><button type="button" data-review-manual class="quiet">${tr("Keep manual")}</button><button type="button" data-review-later class="quiet">${tr("Try again later")}</button><button type="button" data-review-duplicate hidden>${tr("Review existing duplicate")}</button></div><p class="hint">${tr("Keep manual skips future automatic checks until this entry changes. No records are merged or deleted.")}</p>`;
    document.body.append(dialog);
    dialog.querySelector('[data-review-search]').addEventListener("submit", search);
    for (const action of ["apply", "manual", "later", "spelling"]) dialog.querySelector(`[data-review-${action}]`).addEventListener("click", () => decide(action));
    dialog.querySelector('[data-review-prev]').addEventListener("click", () => { if (position > 0) { position--; show(); } });
    dialog.querySelector('[data-review-next]').addEventListener("click", () => { if (position + 1 < entries.length) { position++; show(); } });
    dialog.addEventListener("close", () => { revision++; request?.abort(); current = selected = null; changed(domain); });
  }
  return {open(workspace, rows, id) { install(); domain = workspace; entries = rows; position = Math.max(0, rows.findIndex(row => row.id === id)); openDialog(dialog); show(); }};
}};
