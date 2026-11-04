/* A standalone collection workspace. Movie/anime/TV data and preferences stay intact. */
(() => {
  const musicViews = new Set(["music_library", "music_listening", "music_rankings", "music_lists", "music_insights", "music_recommendations", "music_notifications"]);
  const viewMap = {library: "music_library", currently_watching: "music_listening", rankings: "music_rankings", lists: "music_lists", insights: "music_insights", recommendations: "music_recommendations", notifications: "music_notifications"};
  const headings = {music_library: "Music library", music_listening: "Listening", music_rankings: "Music rankings", music_lists: "Music lists", music_insights: "Music insights", music_recommendations: "Recommendations", music_notifications: "Notifications"};
  const statusLabels = {collected: "Not set", listening: "Listening", listened: "Listened", plan_to_listen: "Plan to listen"};
  const overrideFields = ["genre_additions", "genre_removals", "subgenre_additions", "subgenre_removals"];
  const fields = ["title", "artist", "year", "release_type", "status", "rating", "favorite", "genres", "subgenres", "tags", "notes", "artwork_url", "artwork_data", "provider_id", "release_group_id", "tracks", "description", "publisher", "isbn", "page_count", "current_page", "work_id", "chapters", "edition_info", "completion_count", ...overrideFields];
  let mode = "screen", page = 1, pages = 0, searchRevision = 0, searchController = null;
  let editor = null, baseline = "", artworkData = null, selectedList = null, listRows = [], importDraft = null;
  let screenUrl = null, busy = false, importRevision = 0;
  let importDomain = null, importCommitting = false;
  let preferences = {}, visibleRows = [], searchPurpose = "metadata", searchTimer = null;
  let searchRows = [], workResults = null;
  const requests = window.PMTCollectionNavigation.create();
  let refreshTimer = null, refreshNeeded = false;
  let renderedPage = 1, renderedRequest = "", renderedTotal = 0;
  const originalListFields = new Map();
  let originalTracks = [], trackBaseline = "[]", listSort = "name", listDirection = "asc";
  let pageSize = 24, sortDirection = "desc", detailTab = "details", listeningScope = "all", artworkSelection = null;
  let catalogEdit = null, trackEdit = null;
  const bookCopy = {
    "Music": "Books", "music": "books", "Your music collection": "Your book collection", "Music collection": "Book collection", "Music library": "Book library", "Music rankings": "Book rankings", "Music lists": "Book lists", "Music insights": "Book insights",
    "Add music": "Add book", "Save music": "Save book", "Refresh music": "Refresh books", "Music status": "Reading status", "All music": "All books", "Sort music": "Sort books", "Rated music": "Rated books", "Find album or artist": "Find book or author",
    "Listening": "Reading", "Listened": "Read", "Plan to listen": "Plan to read", "Artist": "Author", "Artists": "Authors", "Album": "Book", "Artist (optional)": "Author (optional)", "Album title": "Book title", "Album details": "Book details", "Open album": "Open book", "Release type": "Book format", "Album artwork": "Book cover", "Find album metadata": "Find book metadata", "Music metadata": "Book metadata",
    "releases": "books", "Releases": "Books", "new releases": "new books", "Release decades": "Publication decades", "No music here yet": "No books here yet", "Add an album, EP or single, or change your filters.": "Add a book or change your filters.",
    "Ordered by your personal ratings. Unrated music stays in your library.": "Ordered by your personal ratings. Unrated books stay in your library.", "Music you manually marked as Listening. No playback is tracked.": "Books you manually marked as Reading. Page progress is optional and entered by you.", "Collection insights, not listening history. No play counts or listening time are inferred.": "Collection insights, not reading history. No reading time or rereads are inferred.",
    "Loading music…": "Loading books…", "Loading album…": "Loading book…", "Saving music…": "Saving book…", "Music saved": "Book saved", "Searching MusicBrainz…": "Searching Open Library…", "Loading artwork and tracklist…": "Loading cover and book details…", "Artwork ready. Save music to keep it.": "Cover ready. Save book to keep it.",
    "No matches. Try another spelling or add music manually.": "No matches. Try another spelling or add the book manually.", "Uploaded artwork stays with your music and backups.": "Uploaded covers stay with your books and backups.",
    "Optional MusicBrainz lookup sends only your search and selected release ID. No listening tracking or account required.": "Optional Open Library lookup sends only your search and selected edition ID. No account or synchronization required.",
    "Remove from music": "Remove from books", "Remove from music?": "Remove from books?", "Only this music entry is removed. Movies, TV, anime and other music are unchanged. Full backups retain removed entries.": "Only this book is removed. Your other collections are unchanged. Full backups retain removed entries.", "Only the list is removed. Your music stays in the collection.": "Only the list is removed. Your books stay in the collection.", "Create a music list on the Lists page first.": "Create a book list on the Lists page first.", "Add albums to lists from their details page.": "Add books to lists from their details page.",
    "MusicBrainz supplies album, artist and track details. Cover Art Archive supplies available cover images. No API key is needed.": "Open Library supplies book editions, authors, descriptions and available cover images. No API key is needed.", "Search is optional and only runs when you request it. Artwork and genres are not available for every release; you can upload artwork and edit all details yourself.": "Search is optional. Cover images, subjects, page counts and contents may be incomplete; you can upload a cover and edit the details yourself.", "Nothing is played, scrobbled or synchronized. Your movie and TV provider settings are unchanged.": "Nothing is downloaded or synchronized. Your music, movie and TV settings are unchanged."
  };
  const t = text => translatedText(mode === "books" ? bookCopy[text] || text : text);
  const html = text => esc(text ?? "");
  const icon = name => `<svg aria-hidden="true"><use href="#icon-${mode === "books" && name === "music" ? "library" : name}"></use></svg>`;
  const active = () => mode !== "screen";
  const isBooks = () => mode === "books";
  const mediaTypeLabel = row => t(({ep: "EP", single: "Single", compilation: "Compilation", other: "Other", paperback: "Paperback", hardcover: "Hardcover", ebook: "Ebook", book: "Book"})[row.release_type] || "Album");
  const taxonomy = row => window.PMTCollectionTaxonomy?.summarize(row, mode) || {genres: (row.genres || []).map(label => ({label, raw: [label]})), subgenres: (row.subgenres || []).map(label => ({label, raw: [label]})), sourceGenres: row.genres || [], sourceSubgenres: row.subgenres || []};
  const taxonomyLabel = label => window.PMTCollectionTaxonomy?.label?.(label) || translatedText(label);
  const sourceLabel = label => window.PMTCollectionTaxonomy.capitalize(label);
  const bookFields = ["title", "author", "year", "book_format", "status", "rating", "favorite", "genres", "subgenres", "tags", "notes", "artwork_url", "artwork_data", "provider_id", "description", "publisher", "isbn", "page_count", "current_page", "work_id", "chapters", "edition_info", "completion_count", ...overrideFields];
  const toBook = data => {
    const mapped = {...data, author: data.artist, book_format: data.release_type, status: ({listening: "reading", listened: "read", plan_to_listen: "plan_to_read"})[data.status] || data.status};
    return Object.fromEntries([...bookFields, "version"].filter(key => mapped[key] !== undefined).map(key => [key, mapped[key]]));
  };
  const fromBook = data => ({...data, artist: data.author, release_type: data.book_format, tracks: [], release_group_id: null, status: ({reading: "listening", read: "listened", plan_to_read: "plan_to_listen"})[data.status] || data.status});
  async function api(path, options = {}, workspace = mode) {
    if (workspace !== "books" || !path.startsWith("/api/music/")) return window.api(path, options);
    let destination = path.replace("/api/music/", "/api/books/").replace("/albums", "/entries");
    destination = destination.replace(/([?&])artist=/, "$1author=").replace("sort=artist", "sort=author").replace("status=listening", "status=reading").replace("status=listened", "status=read").replace("status=plan_to_listen", "status=plan_to_read");
    if (options.body && typeof options.body === "string") {
      const data = JSON.parse(options.body);
      if (path.includes("/albums")) options = {...options, body: JSON.stringify(toBook(data))};
      else if (path.includes("/lists")) { const {album_ids, ...rest} = data; options = {...options, body: JSON.stringify({...rest, book_ids: album_ids})}; }
    }
    const data = await window.api(destination, options);
    if (!data) return data;
    if (path.includes("/lists") && data.items) data.items = data.items.map(row => ({...row, album_ids: row.book_ids}));
    else if (path.includes("/lists") && data.book_ids) return {...data, album_ids: data.book_ids};
    else if (path.includes("/insights")) { data.artists = data.authors; data.statuses = Object.fromEntries(Object.entries(data.statuses).map(([key, value]) => [({reading: "listening", read: "listened", plan_to_read: "plan_to_listen"})[key] || key, value])); }
    else if (data.items) data.items = data.items.map(fromBook);
    else if (data.results) data.results = data.results.map(fromBook);
    else if (data.title) return fromBook(data);
    return data;
  }
  const staticCopy = [];
  function refreshLabels() {
    staticCopy.forEach(({node, text, attr}) => { if (attr) node.setAttribute(attr, t(text)); else node.textContent = t(text); });
    const kind = $("#music-form")?.elements.release_type;
    if (kind) {
      const previous = kind.value;
      kind.innerHTML = (isBooks() ? [["book", "Book"], ["paperback", "Paperback"], ["hardcover", "Hardcover"], ["ebook", "Ebook"], ["other", "Other"]] : [["album", "Album"], ["ep", "EP"], ["single", "Single"], ["compilation", "Compilation"], ["other", "Other"]]).map(([value, text]) => `<option value="${value}">${html(t(text))}</option>`).join("");
      if ([...kind.options].some(option => option.value === previous)) kind.value = previous;
    }
    $('[data-collection-tab="contents"]')?.toggleAttribute("hidden", !isBooks());
    $('.music-nav[data-view="music_library"] use')?.setAttribute("href", isBooks() ? "#icon-library" : "#icon-music");
    $('.music-nav[data-view="music_listening"] use')?.setAttribute("href", isBooks() ? "#icon-reading" : "#icon-listening");
    // Keep canonical labels separate from their display text: generic reverse
    // translation can confuse genre names with unrelated interface labels.
    // Updating just these nodes also preserves open reveals and unsaved edits.
    $$('[data-collection-taxonomy]').forEach(element => {
      const labels = JSON.parse(element.dataset.collectionTaxonomy);
      element.textContent = labels.map(taxonomyLabel).join(", ") || t("Not available");
    });
  }
  function setMode(value) {
    const previous = mode;
    mode = ["music", "books"].includes(value) ? value : "screen";
    if (previous !== mode) {
      requests.abort(); searchRevision++; searchController?.abort();
      clearTimeout(refreshTimer); refreshTimer = null; refreshNeeded = false; renderedRequest = ""; renderedPage = 1; renderedTotal = 0; pages = 0;
      selectedList = null; listRows = []; editor = null; page = 1; visibleRows = [];
      $$(".music-dialog[open]").forEach(dialog => dialog.close());
      $("#music-content")?.replaceChildren();
      if ($("#music-pagination")) $("#music-pagination").hidden = true;
      maintenance.reset();
      $$('[data-collection-fill-banner]').forEach(banner => banner.replaceChildren());
      $("#collection-fill-dialog")?.close();
    }
    document.documentElement.dataset.workspace = mode;
    document.querySelectorAll("button[data-workspace]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.workspace === mode)));
    try { localStorage.setItem("pmt-workspace", mode); } catch (_) { /* device UI preference */ }
    refreshLabels();
    if (active() && $("#collection-fill-dialog")) pollFill(mode);
  }
  function restore(params) {
    let saved = "screen";
    try { saved = localStorage.getItem("pmt-workspace") || "screen"; } catch (_) { /* optional */ }
    const view = params.get("view") || "";
    setMode(params.has("view") ? (view.startsWith("book_") || params.get("mode") === "books" ? "books" : view.startsWith("music_") || params.get("mode") === "music" ? "music" : "screen") : saved);
    if (view.startsWith("book_")) params.set("view", view.replace("book_", "music_").replace("music_reading", "music_listening"));
  }
  async function activate(value) {
    if (busy) return;
    if (value === mode) return;
    if (mode === "screen") screenUrl = window.location.search;
    requests.abort();
    searchRevision += 1; searchController?.abort();
    $$(".music-dialog[open]").forEach(dialog => dialog.close());
    setMode(value);
    page = 1; selectedList = null; listRows = []; editor = null;
    $("#music-query").value = ""; $("#music-status").value = ""; $("#music-sort").value = "recent";
    $("#music-content").replaceChildren();
    settings();
    if (active()) switchView("music_library", {push: true, scrollTop: true});
    else {
      if (screenUrl) { history.pushState(navigationHistoryState(), "", `${location.pathname}${screenUrl}`); restoreNavigationState(); applyNavigationControls(); }
      switchView(musicViews.has(state.view) ? "library" : state.view, {push: !screenUrl, scrollTop: true});
    }
  }
  function persist({push = false} = {}) {
    const params = new URLSearchParams(window.location.search);
    const keep = new URLSearchParams({mode, view: isBooks() ? state.view.replace("music_", "book_").replace("book_listening", "book_reading") : state.view});
    if (state.view === "settings") keep.set("settings_tab", state.settingsTab);
    for (const key of ["desktop", "client_return"]) if (params.has(key)) keep.set(key, params.get(key));
    history[push ? "pushState" : "replaceState"](navigationHistoryState(), "", `${window.location.pathname}?${keep}`);
  }
  function route(view, options) {
    if (view === "settings") { requests.abort(); return false; }
    if (view === "server_console") { setMode("screen"); return false; }
    if (!active()) return false;
    view = musicViews.has(view) ? view : viewMap[view] || "music_library";
    if (state.view !== view) { page = 1; selectedList = null; }
    state.view = view;
    $$(".app-view").forEach(section => { section.hidden = section.id !== "music-view"; });
    $$(".nav-button").forEach(button => {
      const selected = button.dataset.view === view || viewMap[button.dataset.view] === view;
      button.classList.toggle("active", selected);
      if (selected) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
    });
    if (options.persist !== false) persist(options);
    $("#music-heading").textContent = t(headings[view]);
    $("#music-filters").hidden = ["music_lists", "music_insights", "music_recommendations", "music_notifications"].includes(view);
    $("#music-sort").disabled = view === "music_rankings";
    $("#music-status").disabled = false;
    $("#music-page-hint").textContent = t(view === "music_rankings" ? "Ordered by your personal ratings. Unrated music stays in your library." : view === "music_listening" ? "Active and planned entries. Progress is entered by you." : "");
    load();
    if (options.scrollTop) { $("#music-heading").focus({preventScroll: true}); window.scrollTo({top: 0, behavior: "auto"}); }
    return true;
  }
  const {cover, images} = window.PMTCollectionImages.create({html, icon});
  function applyPreferences(data = {}) {
    const changed = ["music", "books"].some(domain => (`${domain}_show_counts` in data && Boolean(data[`${domain}_show_counts`]) !== Boolean(preferences[`${domain}_show_counts`])) || ["tint", "full_color", "reveal"].some(feature => {
      const key = `${domain}_artwork_${feature}`;
      return key in data && Boolean(data[key]) !== Boolean(preferences[key]);
    }));
    preferences = {...preferences, ...data};
    for (const domain of ["music", "books"]) for (const feature of ["tint", "full_color", "reveal"]) document.documentElement.dataset[`${domain}Artwork${feature.split("_").map(word => word[0].toUpperCase() + word.slice(1)).join("")}`] = String(Boolean(preferences[`${domain}_artwork_${feature}`]));
    if (changed) requests.invalidate();
    if (changed && active() && visibleRows.length && $("#music-content .music-grid")) {
      $("#music-content .music-grid").outerHTML = cards(visibleRows);
      images($("#music-content"));
    }
  }
  function duration(ms) { if (ms == null) return ""; const seconds = Math.round(ms / 1000); return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`; }
  function seconds(value) {
    if (!value.trim()) return null;
    const match = /^(\d{1,4}):([0-5]\d)$/.exec(value.trim());
    if (!match || Number(match[1]) > 1440) throw new Error(t("Track duration must use minutes:seconds, or be left blank."));
    return (Number(match[1]) * 60 + Number(match[2])) * 1000;
  }
  function cards(items) {
    const ranking = state.view === "music_rankings", reveal = Boolean(preferences[`${mode}_artwork_reveal`]) && !ranking;
    return `<div class="music-grid ${ranking ? "rankings-list music-ranking-grid" : "library grid"} ${reveal ? "music-reveal-grid" : ""}">${items.map((row, index) => {
      if (ranking) return `<article class="music-card ranking-tile" data-music-id="${row.id}" data-cover="${html(row.cover_url || "")}"><span class="ranking-position music-rank">${(page - 1) * pageSize + index + 1}</span><div class="poster music-cover-button">${cover(row.cover_url, row.title)}</div><div class="ranking-copy"><h3 translate="no">${html(row.title)}</h3><p class="entry-meta">${row.year || "—"} · ${html(mediaTypeLabel(row))}</p><p class="music-card-artist" translate="no">${html(row.artist)}</p></div><div class="ranking-scores personal"><span><small>${html(t("Personal rating"))}</small><strong class="music-rating">${row.rating == null ? "—" : row.rating}</strong></span></div><div class="ranking-footer"><button type="button" class="quiet media-info-button" data-open-music="${row.id}" aria-label="${html(t("Album details"))}: ${html(row.title)}">${icon("info")}</button></div></article>`;
      const terms = taxonomy(row), signals = [...terms.genres, ...terms.subgenres].slice(0, 2);
      const copy = `<div class="entry-copy music-card-copy"><h3 translate="no">${html(row.title)}</h3><p class="entry-meta music-card-meta">${row.year || "—"} · ${html(mediaTypeLabel(row))}</p><p class="music-card-artist" translate="no">${html(row.artist)}</p></div>`;
      const badges = `<div class="entry-signals music-card-signals">${row.status !== "collected" ? `<span class="chip status-chip">${html(t(statusLabels[row.status]))}</span>` : ""}${signals.map(term => `<span class="chip genre-chip" translate="no" data-collection-taxonomy="${html(JSON.stringify([term.label]))}">${html(taxonomyLabel(term.label))}</span>`).join("")}</div>`;
      const progress = mode === "books" && row.current_page != null ? `<span class="card-episode-progress music-page-progress" aria-label="${html(t("Current page"))}: ${row.current_page}${row.page_count ? ` / ${row.page_count}` : ""}"><span><strong>${row.current_page}</strong>/${row.page_count || "—"}</span></span>` : "";
      const count = preferences[`${mode}_show_counts`] && row.completion_count != null ? `<span class="chip collection-count-chip">${row.completion_count} ${html(t(isBooks() ? "reads" : "listens"))}</span>` : "";
      const actions = `<div class="entry-actions music-card-footer">${count}${progress}<button type="button" class="favorite-toggle music-heart ${row.favorite ? "active" : ""}" data-favorite-music="${row.id}" aria-pressed="${row.favorite}" aria-label="${html(t("Favorite"))}: ${html(row.title)}">${icon("heart")}</button><button type="button" class="quiet media-info-button" data-open-music="${row.id}" aria-label="${html(t("Album details"))}: ${html(row.title)}">${icon("info")}</button></div>`;
      const art = reveal ? `<button type="button" class="poster music-cover-button" data-reveal-music aria-expanded="false" aria-controls="music-copy-${row.id}" aria-label="${html(t("Reveal details"))}: ${html(row.title)}">${cover(row.cover_url, row.title)}</button>` : `<div class="poster music-cover-button">${cover(row.cover_url, row.title)}</div>`;
      const card = `<article class="music-card entry-card media-regular-card status-${html(row.status)} ${reveal ? "music-reveal-card" : ""}" data-music-id="${row.id}" data-cover="${html(row.cover_url || "")}">${art}${reveal ? `<div class="music-reveal-panel" id="music-copy-${row.id}">${copy}${badges}${actions}</div>` : copy + badges + actions}</article>`;
      return selectedList ? `<div class="collection-list-item">${card}<button type="button" class="quiet-danger list-remove-button" data-remove-collection-item="${row.id}" aria-label="${html(t("Remove from list"))}: ${html(row.title)}">${html(t("Remove from list"))}</button></div>` : card;
    }).join("")}</div>`;
  }
  function listHeader() {
    const listing = state.view === "music_lists" && !selectedList;
    const detail = state.view === "music_lists" && selectedList;
    $("#music-filters").hidden = !detail && ["music_listening", "music_lists", "music_insights", "music_recommendations", "music_notifications"].includes(state.view);
    $("#music-heading").textContent = detail ? selectedList.name : t(headings[state.view]);
    syncToolbar();
    if (detail) $("#music-heading").setAttribute("translate", "no"); else $("#music-heading").removeAttribute("translate");
    if (!listing) $("#music-list-tools")?.remove();
    if (!detail) { $("#music-back-lists")?.remove(); $("#music-selected-list-actions")?.remove(); }
    if (detail && !$("#music-back-lists")) {
      const back = document.createElement("button"); back.id = "music-back-lists"; back.type = "button"; back.className = "quiet"; back.textContent = t("Back to Lists");
      $(".music-toolbar .toolbar-actions").prepend(back);
      back.addEventListener("click", () => { selectedList = null; page = 1; load(); });
    }
    if (detail && !$("#music-selected-list-actions")) {
      const actions = document.createElement("div"); actions.id = "music-selected-list-actions"; actions.className = "collection-list-heading-actions";
      actions.innerHTML = `<button type="button" id="music-list-rename" class="quiet" data-rename-music-list="${selectedList.id}">${html(t("Rename"))}</button><button type="button" id="music-list-delete" class="quiet-danger" data-delete-music-list="${selectedList.id}">${html(t("Delete list"))}</button>`;
      $(".music-toolbar .toolbar-actions").prepend(actions);
    }
    if (!listing || $("#music-list-tools")) return;
    const tools = document.createElement("div"); tools.id = "music-list-tools"; tools.className = "lists-dashboard-actions";
    tools.innerHTML = `<label class="compact">${html(t("Sort by"))}<select id="music-list-sort"><option value="name">${html(t("Name"))}</option><option value="count">${html(t("Number of titles"))}</option></select></label><button type="button" id="music-list-direction" class="quiet" aria-label="${html(t("Sort direction"))}" title="${html(t("Sort direction"))}">${listDirection === "asc" ? "↑" : "↓"}</button><form id="music-create-list" class="create-list-form"><label class="visually-hidden" for="music-list-name">${html(t("List name"))}</label><input id="music-list-name" name="name" placeholder="${html(t("List name"))}" maxlength="150" required><button type="submit">${html(t("Create list"))}</button></form>`;
    $(".music-toolbar .toolbar-actions").prepend(tools);
    $("#music-list-sort").value = listSort;
    $("#music-list-sort").addEventListener("change", event => { listSort = event.currentTarget.value; load(); });
    $("#music-list-direction").addEventListener("click", event => { listDirection = listDirection === "asc" ? "desc" : "asc"; event.currentTarget.textContent = listDirection === "asc" ? "↑" : "↓"; load(); });
    $("#music-create-list").addEventListener("submit", async event => {
      event.preventDefault(); const form = event.currentTarget, button = form.querySelector("button"), workspace = mode; button.disabled = true;
      try { await api("/api/music/lists", {method: "POST", body: JSON.stringify({name: form.elements.name.value})}, workspace); if (workspace === mode) { form.reset(); await load(); } }
      catch (error) { if (workspace === mode) showMessage($("#music-state"), error.message, true); }
      finally { button.disabled = false; }
    });
    localizeTree(tools);
  }
  function syncToolbar() {
    const ranking = state.view === "music_rankings", sort = ranking ? "rating" : $("#music-sort").value;
    const listening = state.view === "music_listening", dashboard = ranking || listening;
    const toolbar = $(".music-toolbar"), filters = $("#music-filters"), refresh = $("#music-refresh").parentElement;
    toolbar.className = `music-toolbar ${ranking ? "section-heading dashboard-heading" : "library-toolbar"}`;
    let eyebrow = $("#music-eyebrow");
    if (!eyebrow) { eyebrow = document.createElement("p"); eyebrow.id = "music-eyebrow"; eyebrow.className = "eyebrow"; $("#music-heading").before(eyebrow); }
    eyebrow.hidden = !ranking;
    eyebrow.textContent = t(ranking ? "Your ordered favourites" : "In progress and up next");
    let scope = $("#music-listening-scope");
    if (!scope) {
      scope = document.createElement("label"); scope.id = "music-listening-scope"; scope.className = "watching-scope";
      scope.addEventListener("change", event => { listeningScope = event.target.value; page = 1; load(); });
      toolbar.querySelector(".toolbar-actions").append(scope);
    }
    scope.hidden = !listening;
    const scopeKey = `${mode}:${state.interfaceLanguage}`;
    if (scope.dataset.labels !== scopeKey) {
      scope.innerHTML = `<span>${html(t("Show"))}</span><select aria-label="${html(t("Show"))}">${[["all", "Both"], ["listening", "Listening"], ["plan_to_listen", "Plan to listen"]].map(([value, label]) => `<option value="${value}">${html(t(label))}</option>`).join("")}</select>`;
      scope.dataset.labels = scopeKey;
    }
    scope.querySelector("select").value = listeningScope;
    toolbar.querySelector(".toolbar-actions").classList.toggle("watching-heading-actions", listening);
    $("#music-updated").hidden = listening;
    const count = $("#music-count");
    if (count.previousElementSibling !== $("#music-heading")) $("#music-heading").after(count);
    filters.hidden = listening || (!selectedList && ["music_lists", "music_insights", "music_recommendations", "music_notifications"].includes(state.view));
    filters.classList.toggle("rankings-toolbar", ranking);
    // Reparenting even the same live form blurs its search/select controls in
    // WebKit and Chromium. Only move it when the page layout actually changes.
    const actions = toolbar.querySelector(".toolbar-actions"), search = filters.querySelector(".toolbar-search");
    if (dashboard) {
      if (filters.previousElementSibling !== toolbar) toolbar.after(filters);
      if (refresh.parentElement !== actions) actions.append(refresh);
    } else {
      if (filters.parentElement !== actions) actions.append(filters);
      if (refresh.previousElementSibling !== search) search.after(refresh);
    }
    $("#music-status").closest("label").hidden = listening;
    const direction = ranking ? "desc" : sortDirection;
    const label = sort === "favorites" ? (direction === "asc" ? "Favorites last" : "Favorites first") : sort === "recent" ? (direction === "asc" ? "Oldest first" : "Newest first") : sort === "rating" ? (direction === "asc" ? "Lowest first" : "Highest first") : direction === "asc" ? "A–Z" : "Z–A";
    $("#music-sort-direction").innerHTML = `<span aria-hidden="true">${direction === "asc" ? "↑" : "↓"}</span><span>${html(t(label))}</span>`;
    $("#music-sort-direction").disabled = ranking;
    $("#music-page-size").value = String(pageSize);
    $("#music-toggle-filters").classList.toggle("active", Boolean($("#music-status").value));
  }
  function collectionCount(count, label = "releases") { $("#music-count").innerHTML = `<strong>${Number(count).toLocaleString(state.interfaceLanguage || "en")}</strong> <span>${html(t(label))}</span>`; }
  function queueMetadataRefresh() {
    requests.invalidate();
    refreshNeeded = true;
    if (refreshTimer) return;
    refreshTimer = setTimeout(async () => {
      refreshTimer = null;
      if (!active() || !refreshNeeded) return;
      // Background work never overtakes a page click or changes a focused tile.
      if (requests.controller || document.hidden || document.querySelector(".music-dialog[open]") || $("#music-content").contains(document.activeElement)) { queueMetadataRefresh(); return; }
      refreshNeeded = false;
      await load({background: true});
    }, 6000);
  }
  async function load({background = false} = {}) {
    if (!active() || !musicViews.has(state.view)) return;
    if (background && requests.controller) { queueMetadataRefresh(); return; }
    const {controller, revision} = requests.begin();
    listHeader();
    const content = $("#music-content");
    const paged = !["music_recommendations", "music_notifications", "music_insights"].includes(state.view) && (state.view !== "music_lists" || selectedList);
    if (!background) { content.setAttribute("aria-busy", "true"); showMessage($("#music-state"), t("Loading music…")); }
    if (!paged) $("#music-pagination").hidden = true;
    try {
      if (["music_recommendations", "music_notifications"].includes(state.view)) {
        visibleRows = [];
        $("#music-count").textContent = t("Music collection");
        content.innerHTML = `<div class="music-empty">${icon(state.view === "music_notifications" ? "notifications" : "recommendations")}<h3>${html(t(headings[state.view]))}</h3><p>${html(t(isBooks() ? "Recommendations and notifications for books are not available yet." : "Recommendations and notifications for music are not available yet."))}</p><p class="hint">${html(t("Switch to Screen to use its existing features. Your collections stay separate."))}</p></div>`;
      } else if (state.view === "music_insights") {
        visibleRows = [];
        const data = await api("/api/music/insights", {signal: controller.signal});
        if (revision !== requests.revision || !active()) return;
        collectionCount(data.total);
        const stat = (label, value) => `<div class="music-stat"><strong>${value ?? "—"}</strong><span>${html(t(label))}</span></div>`;
        const bars = (title, entries, translate = false) => `<section class="music-bars"><h3>${html(t(title))}</h3>${Object.entries(entries).map(([key, value]) => `<div><span ${translate ? "" : 'translate="no"'}${title === "Genres" ? ` data-collection-taxonomy="${html(JSON.stringify([key]))}"` : ""}>${html(translate ? t(statusLabels[key] || key) : title === "Genres" ? taxonomyLabel(key) : key)}</span><progress max="${Math.max(1, ...Object.values(entries))}" value="${value}" aria-label="${html(key)}"></progress><strong>${value}</strong></div>`).join("") || `<p class="muted">${html(t("No data yet"))}</p>`}</section>`;
        content.innerHTML = `<div class="music-insight-grid">${stat("Releases", data.total)}${stat("Artists", data.artists)}${stat("Favorites", data.favorites)}${stat("Average rating", data.average_rating)}</div><p class="hint">${data.rated} ${html(t("rated"))} · ${data.unrated} ${html(t("unrated"))}</p><div class="music-chart-grid">${bars("Collection status", data.statuses, true)}${bars("Genres", data.genres)}${bars("Release decades", data.years)}</div>`;
      } else if (state.view === "music_lists" && !selectedList) {
        visibleRows = [];
        const data = await api("/api/music/lists", {signal: controller.signal});
        if (revision !== requests.revision || !active()) return;
        listRows = data.items;
        const sortedLists = [...listRows].sort((a, b) => {
          const compared = listSort === "count" ? a.album_ids.length - b.album_ids.length : a.name.localeCompare(b.name, state.interfaceLanguage || "en", {sensitivity: "base", numeric: true});
          return (compared || a.name.localeCompare(b.name)) * (listDirection === "asc" ? 1 : -1);
        });
        collectionCount(listRows.length, "lists");
        content.innerHTML = `<p class="hint">${html(t("Add albums to lists from their details page."))}</p><div class="music-list-grid media-lists">${sortedLists.map(row => `<article class="music-list-card"><button type="button" class="media-list-summary" data-open-music-list="${row.id}"><span><small>${html(t("Your own collections"))}</small><strong translate="no">${html(row.name)}</strong></span><span class="media-list-summary-tail"><span class="chip">${row.album_ids.length} ${html(t("releases"))}</span>${icon("chevron")}</span></button></article>`).join("")}</div>`;
      } else {
        const listening = state.view === "music_listening";
        const params = new URLSearchParams({page, page_size: pageSize, q: listening ? "" : $("#music-query").value, sort: listening ? "recent" : state.view === "music_rankings" ? "rating" : $("#music-sort").value, direction: listening || state.view === "music_rankings" ? "desc" : sortDirection});
        const status = state.view === "music_listening" ? (listeningScope === "all" ? "active" : listeningScope) : $("#music-status").value;
        if (status) params.set("status", status);
        if (selectedList) params.set("list_id", selectedList.id);
        const request = `${mode}:${state.view}:${params}`;
        const url = `/api/music/albums?${params}`;
        const scope = `${state.currentUser?.id || "local"}:${mode}:${state.view}:${state.interfaceLanguage}`;
        const workspace = mode, fetchPage = (path, options) => api(path, options, workspace);
        const data = await requests.read(scope, url, fetchPage, {signal: controller.signal, fresh: background});
        if (revision !== requests.revision || !active()) return;
        pages = data.pages;
        if (page > Math.max(1, pages)) { page = Math.max(1, pages); return load(); }
        collectionCount(data.total);
        if (background && request === renderedRequest && data.items.length && data.items.map(row => row.id).join() === visibleRows.map(row => row.id).join()) {
          // Keep unchanged images, hover menus and DOM nodes alive. Metadata
          // filled on another page should not repaint the page being read.
          let template = null;
          data.items.forEach((row, index) => {
            if (JSON.stringify(row) === JSON.stringify(visibleRows[index])) return;
            const old = content.querySelector(`[data-music-id="${row.id}"]`);
            if (!old) return;
            if (!template) { template = document.createElement("template"); template.innerHTML = cards(data.items); }
            const replacement = template.content.querySelector(`[data-music-id="${row.id}"]`);
            if (old.classList.contains("music-reveal-open")) { replacement.classList.add("music-reveal-open"); replacement.querySelector("[data-reveal-music]")?.setAttribute("aria-expanded", "true"); }
            old.replaceWith(replacement);
          });
        } else if (!background || request !== renderedRequest || JSON.stringify(visibleRows) !== JSON.stringify(data.items)) {
          content.innerHTML = data.items.length ? cards(data.items) : `<div class="music-empty">${icon("music")}<h3>${html(t("No music here yet"))}</h3><p>${html(t("Use Quick Add in the navigation, or change your filters."))}</p></div>`;
        }
        visibleRows = data.items;
        const nav = $("#music-pagination");
        if (!background || request !== renderedRequest || renderedTotal !== data.total) {
          renderPagination(page, pages, data.total, {nav, navigate: async target => {
            page = target; await load();
            if (page === target && active()) window.scrollTo({top: $("#music-view").offsetTop - 80, behavior: "smooth"});
          }});
          requests.bindNext(nav, page, scope, url, fetchPage);
        }
        renderedPage = page; renderedRequest = request; renderedTotal = data.total;
        nav.hidden = pages <= 1;
      }
      showMessage($("#music-state"), "");
      $("#music-updated").textContent = new Intl.DateTimeFormat(state.interfaceLanguage || "en", {hour: "2-digit", minute: "2-digit"}).format(new Date());
      images(content);
      localizeTree(content);
    } catch (error) {
      if (revision !== requests.revision || error.name === "AbortError") return;
      if (paged) page = renderedPage;
      showMessage($("#music-state"), error.message, true);
    } finally { if (revision === requests.revision) { requests.end(revision); content.setAttribute("aria-busy", "false"); } }
  }
  function trackRow(track = {}) {
    const tr = document.createElement("tr");
    tr.dataset.trackId = track.id || crypto.randomUUID();
    tr.dataset.recordingId = track.recording_id || "";
    tr.dataset.originalDuration = track.duration_ms == null ? "" : String(track.duration_ms);
    tr.dataset.renderedDuration = duration(track.duration_ms);
    tr.innerHTML = `<td class="collection-track-number">${track.position || "—"}</td><td><input class="track-disc" type="number" min="1" max="100" value="${track.disc || 1}" aria-label="${html(t("Disc"))}" required></td><td><input class="track-title" value="${html(track.title)}" placeholder="${html(t("Track title"))}" aria-label="${html(t("Track title"))}" maxlength="500" required><input class="music-track-artist" value="${html(track.artist)}" placeholder="${html(t("Track artist (optional)"))}" aria-label="${html(t("Track artist (optional)"))}" maxlength="500"></td><td><input class="track-duration" value="${duration(track.duration_ms)}" placeholder="m:ss" aria-label="${html(t("Duration"))}" pattern="[0-9]{1,4}:[0-5][0-9]"></td><td><button type="button" class="icon-button quiet track-remove" aria-label="${html(t("Remove track"))}">${icon("close")}</button></td>`;
    tr.querySelector(".track-remove").addEventListener("click", () => { tr.remove(); dirty(); });
    return tr;
  }
  function trackSnapshot() {
    return JSON.stringify($$("#music-track-rows tr").map(row => [row.dataset.trackId, row.dataset.recordingId, ...$$('input', row).map(input => input.value)]));
  }
  function trackPositions(rows) {
    const sameStructure = rows.length === originalTracks.length && rows.every((row, index) => row.dataset.trackId === originalTracks[index].id && Number($(".track-disc", row).value) === originalTracks[index].disc);
    const positions = {};
    return rows.map((row, index) => {
      if (sameStructure) return originalTracks[index].position;
      const disc = $(".track-disc", row).value;
      return positions[disc] = (positions[disc] || 0) + 1;
    });
  }
  function formValue() {
    const form = $("#music-form"), result = {};
    for (const key of ["title", "artist", "release_type", "status"]) result[key] = form.elements[key].value.trim();
    result.notes = form.elements.notes.value;
    for (const key of ["rating", "year", "completion_count"]) result[key] = form.elements[key].value === "" ? null : Number(form.elements[key].value);
    result.edition_info = {...(editor?.edition_info || {})};
    for (const key of ["genres", "subgenres", "tags", ...overrideFields]) {
      const value = form.elements[key].value, original = originalListFields.get(key);
      // Provider subject labels may themselves contain commas. Reading or editing
      // unrelated fields must never split or normalize those original labels.
      result[key] = original && value === original.rendered ? [...original.values] : value.split(",").map(item => item.trim()).filter(Boolean);
    }
    result.favorite = form.elements.favorite.checked;
    result.artwork_url = form.elements.artwork_url.value.trim() || null;
    result.artwork_data = artworkData;
    result.provider_id = editor?.provider_id || null;
    result.release_group_id = editor?.release_group_id || null;
    if (isBooks()) {
      result.work_id = editor?.work_id || null;
      for (const key of ["description", "publisher"]) result[key] = form.elements[key].value;
      result.isbn = form.elements.isbn.value.trim() || null;
      for (const key of ["page_count", "current_page"]) result[key] = form.elements[key].value === "" ? null : Number(form.elements[key].value);
      const original = originalListFields.get("chapters"), chapterValue = form.elements.chapters.value;
      result.chapters = original && original.rendered === chapterValue ? [...original.values] : chapterValue.split("\n").map(value => value.trim()).filter(Boolean);
    }
    const trackRows = $$("#music-track-rows tr"), positions = trackPositions(trackRows);
    result.tracks = trackSnapshot() === trackBaseline ? originalTracks.map(track => ({...track})) : trackRows.map((tr, index) => {
      const disc = Number($(".track-disc", tr).value);
      const durationValue = $(".track-duration", tr).value;
      const durationMs = durationValue === tr.dataset.renderedDuration ? (tr.dataset.originalDuration === "" ? null : Number(tr.dataset.originalDuration)) : seconds(durationValue);
      return {id: tr.dataset.trackId, disc, position: positions[index], title: $(".track-title", tr).value.trim(), artist: $(".music-track-artist", tr).value.trim(), duration_ms: durationMs, recording_id: tr.dataset.recordingId || null};
    });
    return result;
  }
  function dirty() {
    if (busy) return;
    let unchanged = false;
    try { unchanged = Boolean(editor?.id) && JSON.stringify(formValue()) === baseline; } catch (_) { /* invalid until corrected */ }
    $("#music-save").disabled = unchanged;
    $("#music-edit-state").textContent = unchanged ? "" : t("Unsaved changes");
    const favorite = $("#music-form").elements.favorite.checked;
    $("#music-detail-favorite").classList.toggle("active", favorite);
    $("#music-detail-favorite").setAttribute("aria-pressed", String(favorite));
    updateDetailsHeader();
    renderEffectiveGenres();
    const rows = $$("#music-track-rows tr"), positions = trackPositions(rows);
    rows.forEach((row, index) => { $(".collection-track-number", row).textContent = positions[index]; });
  }
  function previewCover() {
    $("#music-editor-cover").innerHTML = cover(artworkData || $("#music-art-url").value, $("#music-title").value || t("Album artwork"));
    $("#music-editor-cover .music-cover").classList.add("poster");
    const artwork = artworkData || $("#music-art-url").value;
    $("#music-editor").classList.toggle("has-media-art", Boolean(artwork));
    if (artwork) $("#music-editor").style.setProperty("--entry-art", `url(${JSON.stringify(artwork)})`); else $("#music-editor").style.removeProperty("--entry-art");
    images($("#music-editor-cover"));
  }
  function editorTab(tab) {
    if (tab === "overview" || tab === "tracks") tab = "details";
    if (tab === "edit") tab = detailTab;
    if (!["details", "notes", "genres", "metadata", "catalog", "tracks", "contents"].includes(tab)) tab = "details";
    if ((isBooks() && tab === "tracks") || (!isBooks() && tab === "contents")) tab = "details";
    if (tab === "catalog" && editor?.provider_id) tab = "metadata";
    detailTab = tab;
    $("#music-form").hidden = false;
    $$('[data-collection-panel]').forEach(panel => { panel.hidden = panel.dataset.collectionPanel !== tab; });
    $$('[data-collection-tab]').forEach(button => { const selected = button.dataset.collectionTab === (tab === "catalog" ? "metadata" : tab); button.setAttribute("aria-selected", String(selected)); button.tabIndex = selected ? 0 : -1; });
    $("#music-editor").dataset.detailTab = tab;
    if (tab === "details") renderOverview();
    if (!isBooks() && $("#music-track-editor").hidden) renderTrackPreview();
    if (tab === "metadata") { renderSourceTerms(); renderCatalogSummary(); renderEdition(formValue()); }
    if (tab === "genres") renderEffectiveGenres();
  }
  function renderEffectiveGenres() {
    if (!$("#music-effective-genres")) return;
    const terms = taxonomy(formValue());
    $("#music-effective-genres").innerHTML = ["genres", "subgenres"].map(key => `<span><small>${html(t(key === "genres" ? "Genres" : "Subgenres"))}</small><strong translate="no" data-collection-taxonomy="${html(JSON.stringify(terms[key].map(term => term.label)))}">${html(terms[key].map(term => taxonomyLabel(term.label)).join(", ") || "—")}</strong></span>`).join("");
  }
  function editTab(tab) { editorTab(tab === "personal" ? "details" : tab); }
  function updateDetailsHeader() {
    const form = $("#music-form");
    const title = form.elements.title.value, year = form.elements.year.value;
    $("#music-editor-title").textContent = title ? `${title}${year ? ` (${year})` : ""}` : t("Add music");
    if ($("#music-detail-subtitle")) $("#music-detail-subtitle").textContent = `${year || "—"} · ${mediaTypeLabel({release_type: form.elements.release_type.value})}`;
    if ($("#music-detail-creator")) $("#music-detail-creator").textContent = form.elements.artist.value;
  }
  function renderSourceTerms() {
    const element = $("#music-raw-provider-terms");
    if (!element) return;
    let data;
    try { data = formValue(); } catch (_) { data = editor || {}; }
    const values = taxonomy(data);
    element.innerHTML = `<p><strong>${html(t("Genres"))}</strong><span translate="no">${html(values.sourceGenres.map(sourceLabel).join(" · ") || "—")}</span></p><p><strong>${html(t("Subgenres"))}</strong><span translate="no">${html(values.sourceSubgenres.map(sourceLabel).join(" · ") || "—")}</span></p>`;
  }
  function descriptionPresentation(value = "") {
    // Deliberately not an HTML/Markdown renderer. Only extract explicit source
    // suffixes; escape all remaining prose and validate every outgoing link.
    const sources = [];
    let text = value.replace(/\(\s*(?:source|sources|from)\s*:\s*\[([^\]\n]+)\]\(([^\s)]+)\)\s*\)/gi, (match, label, href) => {
      try {
        const url = new URL(href);
        if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return match;
        sources.push({label, url: url.href}); return "";
      } catch (_) { return match; }
    });
    text = text.replace(/\[([^\]\n]+)\]\(https?:\/\/[^\s)]+\)/gi, "$1")
      .replace(/(\*\*|__)([^\n]+?)\1/g, "$2").replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s.,;:!?)]|$)/g, "$1$2").trim();
    return {text, sources};
  }
  function renderCatalogSummary() {
    const data = formValue(), description = descriptionPresentation(data.description);
    const terms = taxonomy(data);
    const rows = [
      ...(isBooks() ? [["ISBN", data.isbn], ["Publisher", data.publisher], ["Pages", data.page_count]] : []),
      ["Genres", terms.genres.map(term => taxonomyLabel(term.label)).join(", ")], ["Subgenres", terms.subgenres.map(term => taxonomyLabel(term.label)).join(", ")],
      ["Provider", data.provider_id ? (isBooks() ? "Open Library" : "MusicBrainz") : t("Manual entry")],
    ];
    $("#music-catalog-summary").innerHTML = `<p class="hint catalog-edit-policy">${html(t(data.provider_id ? "Catalog fields come from your selected source. Change the source to correct them; personal tracking stays editable." : "Manual catalog details can be edited from More actions."))}</p><dl class="collection-catalog-facts">${rows.map(([label, value]) => `<div><dt>${html(t(label))}</dt><dd translate="no">${html(value || t("Not available"))}</dd></div>`).join("")}</dl>${isBooks() && description.text ? `<details class="optional-details"><summary>${html(t("Description"))}</summary><p translate="no">${html(description.text)}</p></details>` : ""}${description.sources.length ? `<section class="collection-description-sources"><h3>${html(t("Description sources"))}</h3>${description.sources.map(source => `<a href="${html(source.url)}" target="_blank" rel="noopener noreferrer" data-external translate="no">${html(source.label)}</a>`).join(" · ")}</section>` : ""}`;
  }
  function renderOverview() {
    let data;
    try { data = formValue(); } catch (_) { data = editor || {}; }
    const terms = taxonomy(data), tracks = data.tracks || [];
    const fact = (label, value, canonical = null) => `<span><small>${html(t(label))}</small><strong translate="no"${canonical ? ` data-collection-taxonomy="${html(JSON.stringify(canonical.map(term => term.label)))}"` : ""}>${html(value || t("Not available"))}</strong></span>`;
    const names = entries => entries.map(term => taxonomyLabel(term.label)).join(", ");
    const known = tracks.filter(track => track.duration_ms != null);
    const facts = fact("Genres", names(terms.genres), terms.genres) + (isBooks() ? fact("Pages", data.page_count) : fact("Duration", known.length === tracks.length && tracks.length ? duration(tracks.reduce((total, track) => total + track.duration_ms, 0)) : ""));
    const description = isBooks() ? descriptionPresentation(data.description).text || t("No description available") : "";
    $("#music-overview").innerHTML = `<div class="entry-fact-grid">${facts}</div>${isBooks() ? `<div class="entry-description"><small>${html(t("Description"))}</small><p id="music-description" class="pmt-description-collapsed" translate="no">${html(description)}</p>${description.length > 400 ? `<button type="button" id="music-description-toggle" class="quiet pmt-description-toggle" aria-expanded="false">${html(t("Read more"))}</button>` : ""}</div>` : ""}${isBooks() && data.provider_id && !data.page_count ? `<button type="button" id="music-missing-pages" class="quiet">${html(t("Pages missing? Choose another edition"))}</button>` : ""}`;
    $("#music-description-toggle")?.addEventListener("click", event => { const button = event.currentTarget, expanded = button.getAttribute("aria-expanded") !== "true"; button.setAttribute("aria-expanded", String(expanded)); button.textContent = t(expanded ? "Show less" : "Read more"); $("#music-description").classList.toggle("pmt-description-collapsed", !expanded); });
    $("#music-missing-pages")?.addEventListener("click", chooseEdition);
    updateDetailsHeader();
  }
  function renderEdition(data) {
    const info = data.edition_info || {};
    const summary = [info.name, info.date || data.year, info.format, info.country, info.language, ...(info.labels || []), ...(info.catalog_numbers || []), isBooks() ? data.publisher : "", isBooks() ? data.isbn : info.barcode].filter(Boolean).join(" · ");
    const missing = isBooks() && data.provider_id && (!data.year || !data.page_count);
    $("#music-edition-info").innerHTML = `<small>${html(t("Selected edition"))}</small><p translate="no">${html(summary || t("Manual entry"))}</p>${data.provider_id ? `<p class="collection-edition-id" translate="no">${html(data.provider_id)}</p>` : ""}${info.artwork_scope ? `<p class="hint">${html(t("Artwork source"))}: ${html(t(info.artwork_scope))}</p>` : ""}${missing ? `<p class="hint">${html(t("This edition has no year or page count from its provider. Choose another edition with those details; PMT never guesses them."))}</p>` : ""}${isBooks() && data.provider_id ? `<button type="button" class="quiet" id="music-choose-edition">${html(t("Choose another edition"))}</button>` : ""}`;
    $("#music-choose-edition")?.addEventListener("click", chooseEdition);
  }
  async function chooseEdition() {
    if (!isBooks() || !editor?.provider_id) return;
    searchPurpose = "metadata";
    workResults = null;
    openDialog($("#music-search-dialog"));
    // Resolve the saved edition's current work membership, rather than trust
    // a potentially stale work_id from an older import or catalog merge.
    return showEditions({...formValue(), work_id: null});
  }
  async function showEditions(row) {
    const workspace = mode;
    clearTimeout(searchTimer); searchController?.abort(); searchController = new AbortController();
    const revision = ++searchRevision, form = $("#music-search-form");
    form.elements.query.value = row.title; form.elements.artist.value = row.artist || "";
    $("#music-edition-context").hidden = false;
    $("#music-edition-title").textContent = row.title;
    $("#music-search-results").replaceChildren();
    $("#music-search-results").setAttribute("aria-busy", "true");
    showMessage($("#music-search-status"), t("Loading editions…"));
    try {
      const params = new URLSearchParams({title: row.title, language: state.interfaceLanguage || "en"});
      if (row.work_id) params.set("preferred", row.provider_id);
      const path = row.work_id ? `works/${row.work_id}` : `metadata/${row.provider_id}`;
      const data = await api(`/api/books/${path}/editions?${params}`, {signal: searchController.signal}, workspace);
      if (revision !== searchRevision || workspace !== mode || !$("#music-search-dialog").open) return;
      // The top-level search groups duplicate catalog records. Keep their
      // specific editions reachable without mixing page counts or ISBNs.
      const editions = [...data.results, ...(row.catalog_alternatives || [])];
      const seen = new Set();
      renderSearchResults(editions.filter(item => { if (seen.has(item.provider_id)) return false; seen.add(item.provider_id); return true; }).map(item => ({...item, artist: item.artist || item.author || row.artist || ""})), false);
      showMessage($("#music-search-status"), t(data.results.length ? "Choose an edition. Review details before saving." : "No alternate editions found. Use Edit entry details to add missing information."));
      if (data.limited) $("#music-search-status").textContent += ` ${t("Showing a selection of editions, not the full catalog.")}`;
    } catch (error) { if (revision === searchRevision && error.name !== "AbortError") showMessage($("#music-search-status"), error.message, true); }
    finally { if (revision === searchRevision) $("#music-search-results").setAttribute("aria-busy", "false"); }
  }
  function renderTrackPreview() {
    const data = formValue(), tracks = data.tracks || [];
    $("#music-track-preview").innerHTML = `<div class="section-heading"><h3>${html(t("Tracklist"))}</h3><small>${tracks.length} ${html(t("tracks"))}</small></div><div class="collection-track-scroll"><table><thead><tr><th>#</th><th>${html(t("Disc"))}</th><th>${html(t("Track / artist"))}</th><th>${html(t("Duration"))}</th></tr></thead><tbody>${tracks.map(track => `<tr><td class="collection-track-number">${track.position}</td><td class="collection-track-disc">${track.disc}</td><td translate="no"><strong>${html(track.title)}</strong>${track.artist && track.artist !== data.artist ? `<small>${html(track.artist)}</small>` : ""}</td><td>${duration(track.duration_ms) || "—"}</td></tr>`).join("")}</tbody></table>${tracks.length ? "" : `<p class="hint">${html(t(data.provider_id ? "No tracklist was supplied by this source. Try another edition from Metadata." : "No tracklist available. You can add one from More actions."))}</p>`}</div>`;
  }
  async function chooseArtwork() {
    const workspace = mode, id = editor?.id;
    artworkSelection = null;
    $("#music-artwork-apply").disabled = true;
    $("#music-artwork-options").replaceChildren();
    showMessage($("#music-artwork-state"), t(id ? "Loading artwork options…" : "Save this entry first to browse alternate artwork, or upload your own image."));
    openDialog($("#music-artwork-dialog"));
    if (!id) return;
    try {
      const result = await api(`/api/music/albums/${id}/artwork-options`, {}, workspace);
      if (mode !== workspace || editor?.id !== id || !$("#music-artwork-dialog").open) return;
      $("#music-artwork-options").innerHTML = result.options.map(option => `<label class="artwork-option"><input type="radio" name="collection-artwork" value="${html(option.url)}"><span class="collection-artwork-thumbnail">${cover(option.thumbnail_url || option.url, option.label)}</span><strong>${html(t(option.label))}</strong><small>${html(t(option.scope || option.source))}</small></label>`).join("");
      showMessage($("#music-artwork-state"), result.warning || t(result.options.length ? "Choose artwork, then save your changes." : "No alternate artwork is available. You can upload your own image."));
      images($("#music-artwork-options"));
    } catch (error) { if (workspace === mode && editor?.id === id) showMessage($("#music-artwork-state"), error.message, true); }
  }
  function fillForm(data) {
    // Opening another entry or applying a new provider replaces the editing
    // context. A later Cancel must never restore fields from the old identity.
    catalogEdit = null; trackEdit = null;
    const form = $("#music-form");
    for (const key of ["title", "artist", "year", "release_type", "status", "rating", "notes", "artwork_url", "completion_count"]) form.elements[key].value = data[key] ?? "";
    for (const key of ["genres", "subgenres", "tags", ...overrideFields]) {
      const values = [...(data[key] || [])], rendered = values.join(", ");
      originalListFields.set(key, {values, rendered});
      form.elements[key].value = rendered;
    }
    form.elements.favorite.checked = Boolean(data.favorite);
    for (const key of ["description", "publisher", "isbn", "page_count", "current_page"]) form.elements[key].value = data[key] ?? "";
    form.elements.chapters.value = (data.chapters || []).join("\n");
    originalListFields.set("chapters", {values: [...(data.chapters || [])], rendered: form.elements.chapters.value});
    artworkData = data.artwork_data || null;
    $("#music-track-rows").replaceChildren(...(data.tracks || []).map(trackRow));
    $("#music-track-editor").hidden = true;
    $("#music-track-preview").hidden = false;
    originalTracks = (data.tracks || []).map(track => ({...track}));
    trackBaseline = trackSnapshot();
    applyCatalogPolicy();
    previewCover();
    $("#music-source-credit").innerHTML = data.provider_id ? isBooks() ? `<a href="https://openlibrary.org/books/${html(data.provider_id)}" target="_blank" rel="noopener noreferrer" data-external>Open Library</a>` : `<a href="https://musicbrainz.org/release/${html(data.provider_id)}" target="_blank" rel="noopener noreferrer" data-external>MusicBrainz</a> · <a href="https://coverartarchive.org" target="_blank" rel="noopener noreferrer" data-external>Cover Art Archive</a>` : t("Manual entry · your data stays local");
  }
  async function openEditor(id = null) {
    if (busy || !active()) return;
    const revision = ++searchRevision;
    editor = null;
    $("#music-form").reset();
    $("#music-editor-title").textContent = t(id ? "Album details" : "Add music");
    showMessage($("#music-editor-message"), id ? t("Loading album…") : "");
    $("#music-delete").hidden = !id;
    $("#music-membership").hidden = true;
    disableEditorFields(Boolean(id));
    $("#music-save").disabled = Boolean(id);
    fillForm({release_type: isBooks() ? "book" : "album", status: "plan_to_listen", tracks: []});
    editTab(id ? "personal" : "catalog");
    editorTab(id ? "overview" : "edit");
    if (id) $("#music-overview").textContent = t("Loading album…");
    openDialog($("#music-editor"));
    try {
      if (id) {
        const data = await api(`/api/music/albums/${id}`);
        if (revision !== searchRevision || !$("#music-editor").open) return;
        editor = data;
        fillForm(data);
      }
      baseline = JSON.stringify(formValue());
      disableEditorFields(false);
      showMessage($("#music-editor-message"), "");
      dirty();
      editTab(id ? "personal" : "catalog");
      editorTab(id ? "overview" : "edit");
      $("#music-more-actions").open = false;
      (id ? $('[data-collection-tab="details"]') : $("#music-title")).focus({preventScroll: true});
      $("#music-editor").scrollTop = 0;
      if (id) await memberships();
    } catch (error) { if (revision === searchRevision) showMessage($("#music-editor-message"), error.message, true); }
  }
  async function memberships() {
    const id = editor?.id, workspace = mode;
    if (!id) return;
    const data = await api("/api/music/lists");
    if (workspace !== mode || editor?.id !== id || !$("#music-editor").open) return;
    listRows = data.items;
    $("#music-membership").hidden = false;
    $("#music-list-picker").innerHTML = data.items.length ? data.items.map(row => `<label class="check"><input type="checkbox" data-music-membership="${row.id}" ${row.album_ids.includes(id) ? "checked" : ""}><span translate="no">${html(row.name)}</span></label>`).join("") : `<p class="hint">${html(t("Create a music list on the Lists page first."))}</p>`;
  }
  function applyCatalogPolicy() {
    const linked = Boolean(editor?.provider_id), form = $("#music-form");
    for (const name of ["title", "artist", "year", "release_type", "genres", "subgenres", "description", "publisher", "isbn", "page_count"]) form.elements[name].disabled = linked || busy;
    form.elements.chapters.readOnly = linked;
    $("#music-edit-catalog").hidden = linked;
    $("#music-edit-tracklist").hidden = linked || isBooks();
    $$("#music-track-editor input, #music-track-editor button").forEach(control => { control.disabled = linked || busy; });
    if (linked) { $("#music-track-editor").hidden = true; $("#music-track-preview").hidden = false; }
  }
  function disableEditorFields(value) {
    // The header remains operable while a provider is loading. All editing
    // controls, including the separate tracklist, belong to this same form.
    [...$("#music-form").elements].filter(control => !control.matches('fieldset, .dialog-close')).forEach(control => { control.disabled = value; });
    if (!value) applyCatalogPolicy();
  }
  function editorBusy(value, message = "") {
    busy = value;
    disableEditorFields(value);
    $("#music-save").disabled = value;
    $("#music-delete").disabled = value;
    $("#music-editor .dialog-close").disabled = value;
    $("#music-editor-message").textContent = t(message);
    $("#music-form").setAttribute("aria-busy", String(value));
  }
  async function save(event) {
    event.preventDefault();
    if (busy) return;
    const workspace = mode;
    try {
      const payload = formValue();
      if (editor?.id && JSON.stringify(payload) === baseline) { $("#music-editor").close(); return; }
      editorBusy(true, "Saving music…");
      if (editor?.id) payload.version = editor.version;
      const saved = await api(editor?.id ? `/api/music/albums/${editor.id}` : "/api/music/albums", {method: editor?.id ? "PUT" : "POST", body: JSON.stringify(payload)});
      if (workspace !== mode) return;
      editor = saved;
      $("#music-editor").close();
      toast(t("Music saved"));
      await load();
    } catch (error) { showMessage($("#music-editor-message"), error.message, true); }
    finally { busy = false; disableEditorFields(false); $("#music-editor .dialog-close").disabled = false; $("#music-delete").disabled = false; $("#music-form").setAttribute("aria-busy", "false"); dirty(); }
  }
  function renderSearchResults(results, works = false, expanded = false) {
    searchRows = results;
    const shown = expanded ? results : results.slice(0, 8);
    $("#music-search-results").innerHTML = shown.map((row, index) => {
      const work = works && row.work_id;
      return `<button class="music-search-result search-result" type="button" ${work ? `data-book-work="${index}"` : `data-music-result="${html(row.provider_id)}"`}>${cover(row.artwork_url, row.title, row.artwork_fallbacks || [])}<span><strong translate="no">${html(row.title)}</strong><small translate="no">${html(row.artist)}${row.artist ? " · " : ""}${(work ? row.original_year : row.year) || "—"}${!work && isBooks() ? ` · ${html(row.edition || "")}` : row.variant ? ` · ${html(row.variant)}` : ""}</small><small>${work ? html(t("Choose an edition")) : isBooks() ? `${row.page_count || "—"} ${html(t("Pages"))}${row.language ? ` · ${html(row.language)}` : ""}${row.isbn ? ` · ISBN ${html(row.isbn)}` : ""}` : `${row.track_count || "—"} ${html(t("tracks"))}`}</small></span></button>`;
    }).join("");
    if (shown.length < results.length) {
      const more = document.createElement("button"); more.type = "button"; more.className = "quiet"; more.dataset.moreCatalog = "true";
      more.textContent = `${translatedText("More catalog results")} (${results.length - shown.length})`;
      more.addEventListener("click", () => renderSearchResults(results, works, true));
      $("#music-search-results").append(more);
    }
    images($("#music-search-results"));
  }
  async function lookup(event) {
    event?.preventDefault();
    clearTimeout(searchTimer);
    $("#music-edition-context").hidden = true; workResults = null;
    const form = $("#music-search-form");
    const query = form.elements.query.value.trim();
    if (query.length < 2 || (!event && query.length < 3 && !/[\u3400-\u9fff]/u.test(query))) { searchRevision++; searchController?.abort(); $("#music-search-results").replaceChildren(); $("#music-search-results").setAttribute("aria-busy", "false"); showMessage($("#music-search-status"), t("Type three characters, or press Search for a short title.")); return; }
    const revision = ++searchRevision;
    searchController?.abort(); searchController = new AbortController();
    $("#music-search-results").replaceChildren();
    showMessage($("#music-search-status"), t("Searching MusicBrainz…"));
    $("#music-search-results").setAttribute("aria-busy", "true");
    try {
      const params = new URLSearchParams({q: form.elements.query.value.trim(), artist: form.elements.artist.value.trim()});
      if (isBooks()) params.set("language", state.interfaceLanguage || "en");
      const data = await api(`/api/music/search?${params}`, {signal: searchController.signal});
      if (revision !== searchRevision) return;
      workResults = isBooks() ? {rows: data.results, query: form.elements.query.value, artist: form.elements.artist.value} : null;
      renderSearchResults(data.results, isBooks());
      showMessage($("#music-search-status"), t(data.results.length ? (isBooks() ? "Choose a book, then choose its edition." : "Choose an album. Review details before saving.") : "No matches. Try another spelling or add music manually."));
    } catch (error) { if (revision === searchRevision && error.name !== "AbortError") showMessage($("#music-search-status"), error.message, true); }
    finally { if (revision === searchRevision) $("#music-search-results").setAttribute("aria-busy", "false"); }
  }
  async function selectResult(id) {
    const revision = ++searchRevision;
    $$("[data-music-result]").forEach(button => { button.disabled = true; });
    showMessage($("#music-search-status"), t("Loading artwork and tracklist…"));
    try {
      const details = await api(`/api/music/metadata/${id}`);
      if (revision !== searchRevision || !$("#music-search-dialog").open) return;
      const current = formValue();
      const merged = {...current};
      const differentEdition = current.provider_id !== details.provider_id;
      for (const key of ["title", "artist", "year", "release_type", "artwork_url", "genres", "subgenres", "tracks", "provider_id", "release_group_id", "description", "publisher", "isbn", "page_count", "work_id", "chapters", "edition_info"]) {
        const value = details[key];
        // Older collection versions stored personal subgenre labels in this
        // field. A provider with no classification must not erase those labels.
        if (key === "subgenres" && Array.isArray(value) && !value.length) continue;
        if (key in details && (differentEdition || (value != null && value !== "" && (!Array.isArray(value) || value.length)))) merged[key] = value;
      }
      if (differentEdition) merged.artwork_data = null;
      // Stable track UUIDs survive repeated selection of the same provider recording.
      const oldTracks = new Map(current.tracks.map(track => [`${track.disc}:${track.position}:${track.recording_id || track.title}`, track.id]));
      merged.tracks = merged.tracks.map(track => ({...track, id: oldTracks.get(`${track.disc}:${track.position}:${track.recording_id || track.title}`) || track.id}));
      editor = {...editor, provider_id: details.provider_id, release_group_id: details.release_group_id, work_id: details.work_id, edition_info: merged.edition_info};
      fillForm(merged);
      $("#music-search-dialog").close();
      if (!$("#music-editor").open) openDialog($("#music-editor"));
      editTab(searchPurpose === "add" ? "personal" : "metadata");
      editorTab("edit");
      showMessage($("#music-editor-message"), t("Metadata loaded. Review and save to keep it."));
      if (isBooks() && merged.current_page > merged.page_count && merged.page_count) showMessage($("#music-editor-message"), t("This edition has fewer pages than your current progress. Review your page count before saving."));
      dirty();
    } catch (error) { if (revision === searchRevision) showMessage($("#music-search-status"), error.message, true); }
    finally { $$("[data-music-result]").forEach(button => { button.disabled = false; }); }
  }
  function settings() {
    if (!$("#settings-view")) return;
    const scope = $("#collection-export-scope");
    if (!scope) return;
    if (!scope.dataset.chosen) scope.value = mode;
    exportScope();
  }
  function openImportChooser() {
    if (importCommitting) return;
    importRevision++; importDraft = null; importDomain = null;
    $("#music-import-file").value = ""; $("#music-import-confirm").hidden = true;
    showMessage($("#music-import-status"), "");
    openDialog($("#collection-import-chooser"));
  }
  function installImports() {
    const chooser = document.createElement("dialog"); chooser.id = "collection-import-chooser"; chooser.className = "collection-import-dialog";
    chooser.innerHTML = `<form method="dialog" class="dialog-head"><h2>Import a list</h2><button class="icon-button dialog-close" aria-label="Close">${icon("close")}</button></form><p>Which collection is this list for?</p><div class="collection-import-choices"><button type="button" data-import-domain="screen"><strong>Screen</strong><small>Movies, TV &amp; anime · CSV / ZIP</small></button><button type="button" data-import-domain="music"><strong>Music</strong><small>Albums · PMT collection JSON</small></button><button type="button" data-import-domain="books"><strong>Books</strong><small>Books · PMT collection JSON</small></button></div>`;
    const dialog = document.createElement("dialog"); dialog.id = "collection-import-dialog"; dialog.className = "collection-import-dialog";
    dialog.innerHTML = `<form method="dialog" class="dialog-head"><h2 id="collection-import-heading">Import a list</h2><button class="icon-button dialog-close" aria-label="Close">${icon("close")}</button></form><p>Choose a PMT collection JSON file. Review the preview before adding entries; existing entries are not overwritten.</p><p class="hint">For another list format, use the matching conversion prompt in Data &amp; Backup.</p><label>Collection file<input id="music-import-file" type="file" accept=".json,application/json"></label><p id="music-import-status" class="message" role="status" aria-live="polite"></p><button id="music-import-confirm" type="button" hidden>Import new entries without overwriting</button>`;
    document.body.append(chooser, dialog);
    const enrich = document.createElement("label"); enrich.className = "collection-fill-opt-in";
    enrich.innerHTML = `<input id="collection-import-fill" type="checkbox" checked><span>${html(translatedText("Find metadata and artwork after import"))}<small>${html(translatedText("Sends titles and artists to MusicBrainz, or titles, authors and ISBNs to Open Library. No account is required. Uncertain matches stay unchanged for review."))}</small></span>`;
    $("#music-import-status").before(enrich);
    chooser.addEventListener("click", event => {
      const button = event.target.closest("[data-import-domain]"); if (!button) return;
      importDomain = button.dataset.importDomain; chooser.close();
      if (importDomain === "screen") { openDialog($("#import-dialog")); return; }
      $("#collection-import-heading").textContent = `${translatedText("Import a list")} · ${translatedText(importDomain === "books" ? "Books" : "Music")}`;
      openDialog(dialog);
    });
    const returnToSettings = async () => {
      if ($("#collection-import-chooser").open || dialog.open || $("#import-dialog").open || $("#collection-fill-dialog")?.open || !state.importReturnToSettings) return;
      state.importReturnToSettings = false; await openSettings(); selectSettingsTab("data");
    };
    chooser.addEventListener("close", returnToSettings);
    dialog.addEventListener("cancel", event => { if (importCommitting) event.preventDefault(); });
    dialog.addEventListener("close", () => { importRevision++; importDraft = null; importDomain = null; returnToSettings(); });
    const screenPrompt = $("#ai-import-prompt").textContent;
    $("#import-prompt-mode").addEventListener("change", event => {
      const domain = event.currentTarget.value;
      if (domain === "screen") { $("#ai-import-prompt").textContent = screenPrompt; return; }
      const book = domain === "books", creator = book ? "author" : "artist", entries = book ? "books" : "albums";
      $("#ai-import-prompt").textContent = `Convert my ${book ? "book" : "music album"} list into a UTF-8 PMT collection JSON file.
First ask whether it contains personal ratings and what scale they use. Preserve the complete credited ${creator}, original spelling/script and edition/version qualifiers. Ask about missing or truncated names; never expand an uncertain name from memory. Keep supplied stable provider IDs or source links in notes for verification; never invent them. Do not send my list to metadata providers during conversion. PMT can optionally look up metadata and artwork after I confirm the import, using the real titles and ${creator} names. Do not invent catalog IDs or artwork URLs to simulate a metadata match.
Return raw JSON only, no Markdown. Use this exact envelope:
{"format":"${book ? "pmt-book-collection" : "pmt-music-collection"}","version":1,"${entries}":[],"lists":[]}
Put one object per ${book ? "book edition" : "album"} in ${entries}. Required fields: id (a newly generated unique UUID), title (string), ${creator} (string). UUIDs are structural identifiers, not catalog IDs.
Allowed optional fields: year (integer or null), rating (null or 1–10, at most one decimal), favorite (boolean), status, tags (array of strings), notes (string), genres and subgenres (arrays of strings), completion_count (nonnegative integer or null).
Only if explicitly present in my original data, preserve ${book ? "provider_id (Open Library edition OL…M), work_id (OL…W)" : "provider_id (MusicBrainz release UUID), release_group_id (MusicBrainz group UUID)"}. Otherwise omit these fields. A source link may be kept in notes for manual verification; never infer IDs from memory.
${book ? "Book fields: book_format (book, paperback, hardcover, ebook, other), publisher (string), isbn (valid ISBN or null), page_count (positive integer or null), current_page (nonnegative integer or null), description (string). Pages and year must belong to the specific edition; do not borrow another edition's values." : "Album fields: release_type (album, ep, single, compilation, other). Do not convert individual songs into albums. Leave tracks empty unless accurate track information is provided."}
Status must be ${book ? "reading, read, plan_to_read" : "listening, listened, plan_to_listen"}, or collected for unknown status. Always write collected when status is unknown, instead of inferring intent.
Never invent titles, creators, ratings, years, artwork URLs, provider IDs, completion counts or metadata. Omit unknown optional fields. Preserve notes only when explicitly included. Convert ratings only after I confirm the scale. Do not infer counts from status or add listening/reading dates.
Keep lists empty for this first import. Output must validate as JSON; escape quotes and line breaks. I will save it as .json, choose ${book ? "Books" : "Music"} in Import a list, review the preview and confirm. No entries should be overwritten.`;
    });
  }
  const maintenance = window.PMTCollectionMaintenance.create({getMode: () => mode, active, html, icon, cover, images, activate, openEditor, queueMetadataRefresh});
  const {openFill, pollFill, installMetadataFill} = maintenance;
  function quickAdd() {
    if (busy || !active()) return;
    editor = null; baseline = ""; searchPurpose = "add";
    $("#music-form").reset();
    fillForm({release_type: isBooks() ? "book" : "album", status: "plan_to_listen", tracks: []});
    $("#music-editor-title").textContent = t("Add music");
    $("#music-delete").hidden = true; $("#music-membership").hidden = true;
    disableEditorFields(false);
    $("#music-search-form").reset(); $("#music-manual-entry").open = false;
    clearTimeout(searchTimer); searchRevision++; searchController?.abort(); workResults = null;
    $("#music-edition-context").hidden = true;
    $("#music-search-results").replaceChildren();
    showMessage($("#music-search-status"), t("Type at least two characters to search."));
    openDialog($("#music-search-dialog"));
    $("#music-search-form").elements.query.focus();
  }
  function exportScope() {
    const scope = $("#collection-export-scope").value;
    $("#collection-export").href = ({screen: "/api/exports/watch-log.csv", music: "/api/exports/music-collection.json", books: "/api/exports/book-collection.json", everything: "/api/exports/portable-library.zip"})[scope];
    $("#collection-export-help").textContent = t(({screen: "Screen-only CSV: titles and personal tracking. For all metadata and history, use Everything.", music: "Music-only JSON: albums, tracklists, ratings, lists and uploaded artwork. Remote artwork remains linked.", books: "Books-only JSON: books, reading progress, ratings, lists and uploaded covers. Remote covers remain linked.", everything: "Full archive of all three collections. Restoring replaces all three after a safety backup."})[scope]);
  }
  function installDialogs() {
    const shell = document.createElement("div");
    shell.innerHTML = `<dialog id="music-editor" class="music-dialog music-editor"><form method="dialog" class="dialog-head"><h2 id="music-editor-title">Add music</h2><button class="icon-button dialog-close" aria-label="Close">${icon("close")}</button></form>
      <form id="music-form"><fieldset id="music-form-fields" class="music-form-fields"><div class="music-editor-body"><aside class="music-art-column"><div id="music-editor-cover"></div><div class="music-art-actions"><label class="button-link quiet">Upload artwork<input id="music-art-file" type="file" accept="image/png,image/jpeg,image/webp" hidden></label><button type="button" id="music-art-remove" class="quiet">Clear artwork</button></div><label>Artwork link (HTTPS)<input id="music-art-url" name="artwork_url" type="url" placeholder="https://…" maxlength="2000"></label><p class="hint">Uploaded artwork stays with your music and backups.</p><button type="button" id="music-find-metadata" class="quiet">Find album metadata</button><p id="music-source-credit" class="hint"></p></aside>
      <div class="music-editor-fields"><div class="form-grid"><label class="music-wide">Title<input id="music-title" name="title" maxlength="500" required></label><label class="music-wide">Artist<input name="artist" maxlength="500" required></label><label>Year<input name="year" type="number" min="1000" max="2200"></label><label>Release type<select name="release_type"><option value="album">Album</option><option value="ep">EP</option><option value="single">Single</option><option value="compilation">Compilation</option><option value="other">Other</option></select></label><label>Status<select name="status"><option value="collected">Collected</option><option value="listening">Listening</option><option value="listened">Listened</option><option value="plan_to_listen">Plan to listen</option></select></label><label>Personal rating<input name="rating" type="number" min="1" max="10" step="0.1" placeholder="1–10"></label><label class="check music-wide"><input name="favorite" type="checkbox"> Favorite</label><label>Genres<input name="genres" placeholder="Comma separated"></label><label>Tags<input name="tags" placeholder="Comma separated"></label><label class="music-wide">Notes<textarea name="notes" maxlength="20000" rows="2"></textarea></label></div>
      <div class="music-track-heading"><h3>Tracklist</h3><button type="button" id="music-add-track" class="quiet">Add track</button></div><p class="hint">Order follows the rows within each disc. Duration is optional, not time listened.</p><table class="music-track-table"><thead><tr><th>Disc</th><th>Track / artist</th><th>Duration</th><th><span class="visually-hidden">Actions</span></th></tr></thead><tbody id="music-track-rows"></tbody></table>
      <details id="music-membership" hidden><summary>Music lists</summary><p class="hint">List membership saves immediately.</p><div id="music-list-picker" class="music-list-picker"></div></details></div></div></fieldset><p id="music-editor-message" class="message" role="status" aria-live="polite"></p><div class="music-editor-footer"><button type="button" id="music-delete" class="quiet-danger" hidden>Remove from music</button><span id="music-edit-state" class="hint"></span><button type="submit" id="music-save">Save music</button></div></form></dialog>
      <dialog id="music-search-dialog" class="music-dialog music-search-dialog"><form method="dialog" class="dialog-head"><h2>Find album metadata</h2><button class="icon-button dialog-close" aria-label="Close">${icon("close")}</button></form><p class="hint">Optional MusicBrainz lookup sends only your search and selected release ID. No listening tracking or account required.</p><form id="music-search-form" class="music-search-form"><label>Album title<input name="query" minlength="2" maxlength="200" required></label><label>Artist (optional)<input name="artist" maxlength="200"></label><button type="submit">Search</button></form><p id="music-search-status" class="message" role="status" aria-live="polite"></p><div id="music-search-results" class="music-search-results"></div></dialog>`;
    document.body.append(...shell.children);
    const artworkHint = document.createElement("p"); artworkHint.className = "hint";
    artworkHint.textContent = "Use a Cover Art Archive, Internet Archive or Open Library image link, or upload the image.";
    $("#music-art-url").closest("label").after(artworkHint);
    const bookFieldsElement = document.createElement("div");
    bookFieldsElement.className = "book-fields form-grid";
    bookFieldsElement.innerHTML = '<label>ISBN<input name="isbn" maxlength="30" placeholder="ISBN-10 / ISBN-13"></label><label>Publisher<input name="publisher" maxlength="500"></label><label>Pages<input name="page_count" type="number" min="1" max="100000"></label><label>Current page<input name="current_page" type="number" min="0" max="100000"></label><label class="music-wide">About<textarea name="description" rows="3" maxlength="20000"></textarea></label><label class="music-wide">Contents (optional)<textarea name="chapters" rows="4" placeholder="One chapter per line"></textarea></label><p class="hint music-wide">Reading progress is manual. Changing status never invents a reading date or page count.</p>';
    $(".music-editor-fields").insertBefore(bookFieldsElement, $(".music-track-heading"));
    for (const element of [$(".music-track-heading"), $(".music-track-heading").nextElementSibling, $(".music-track-table")]) element.classList.add("music-only-detail");
    compactDialogs();
    for (const root of [$("#music-view"), $("#music-editor"), $("#music-search-dialog"), $("#music-artwork-dialog"), ...$$(".music-nav")]) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        const node = walker.currentNode, text = node.textContent.trim();
        if (text && !node.parentElement.closest("svg, [translate='no']")) staticCopy.push({node, text});
      }
      root.querySelectorAll("[placeholder], [aria-label], [title]").forEach(node => {
        for (const attr of ["placeholder", "aria-label", "title"]) if (node.hasAttribute(attr)) staticCopy.push({node, text: node.getAttribute(attr), attr});
      });
    }
  }
  function compactDialogs() {
    const dialog = $("#music-editor"), form = $("#music-form"), fieldset = $("#music-form-fields");
    dialog.classList.add("entry-dialog", "media-details", "detail-window");
    $("#music-editor-title").setAttribute("translate", "no");
    const labels = new Map($$(".music-editor-fields label").filter(label => label.querySelector("[name]")).map(label => [label.querySelector("[name]").name, label]));
    const subgenres = document.createElement("label"); subgenres.innerHTML = 'Subgenres<input name="subgenres" placeholder="Comma separated">'; labels.set("subgenres", subgenres);
    const coverElement = $("#music-editor-cover"), credit = $("#music-source-credit"), artworkActions = $(".music-art-actions"), artworkLabel = $("#music-art-url").closest("label"), lookupButton = $("#music-find-metadata"), membership = $("#music-membership");
    const trackHeading = $(".music-track-heading"), trackTable = $(".music-track-table");
    const numberHeading = document.createElement("th"); numberHeading.textContent = "#"; trackTable.querySelector("tr").prepend(numberHeading);
    const shell = document.createElement("div"); shell.className = "entry-dialog-shell";
    const art = document.createElement("aside"); art.id = "music-detail-art"; art.className = "entry-dialog-art";
    art.append(coverElement);
    const subtitle = document.createElement("p"); subtitle.id = "music-detail-subtitle";
    const creator = document.createElement("p"); creator.id = "music-detail-creator"; creator.setAttribute("translate", "no");
    const artMeta = document.createElement("div"); artMeta.className = "detail-art-meta";
    const artCopy = document.createElement("div"); artCopy.className = "detail-art-copy"; artCopy.append(subtitle, creator, credit);
    const favoriteInput = form.elements.favorite; favoriteInput.hidden = true;
    const favorite = document.createElement("button"); favorite.id = "music-detail-favorite"; favorite.type = "button"; favorite.className = "favorite-toggle"; favorite.setAttribute("aria-label", "Favorite"); favorite.setAttribute("aria-pressed", "false"); favorite.innerHTML = icon("heart");
    favorite.addEventListener("click", () => { favoriteInput.checked = !favoriteInput.checked; favoriteInput.dispatchEvent(new Event("change", {bubbles: true})); });
    artMeta.append(artCopy, favorite, favoriteInput); art.append(artMeta);
    const content = document.createElement("div"); content.className = "entry-dialog-content";
    const tabs = document.createElement("div"); tabs.className = "dialog-tabs"; tabs.setAttribute("role", "tablist"); tabs.setAttribute("aria-label", "Entry sections");
    tabs.innerHTML = [["details", "Details"], ["notes", "Notes & tags"], ["genres", "Genres"], ["metadata", "Metadata"], ["contents", "Contents (optional)"]].map(([key, label]) => `<button type="button" role="tab" data-collection-tab="${key}" aria-selected="${key === "details"}" aria-controls="music-panel-${key}" tabindex="${key === "details" ? "0" : "-1"}">${html(t(label))}</button>`).join("");
    content.append(tabs, form); shell.append(art, content); dialog.append(shell);
    fieldset.replaceChildren();
    const panels = {};
    for (const key of ["details", "notes", "genres", "metadata", "catalog", "contents"]) {
      const panel = document.createElement("section"); panel.id = `music-panel-${key}`; panel.className = `entry-panel ${["notes", "genres", "catalog", "contents"].includes(key) ? "form-grid" : ""}`; panel.dataset.collectionPanel = key; panel.setAttribute("role", "tabpanel"); panel.hidden = key !== "details"; fieldset.append(panel); panels[key] = panel;
    }
    const detailsMain = document.createElement("div"); detailsMain.className = "collection-details-main"; panels.details.append(detailsMain);
    const overview = document.createElement("div"); overview.id = "music-overview"; overview.className = "entry-overview-facts"; detailsMain.append(overview);
    const tracking = document.createElement("div"); tracking.className = "entry-detail-controls"; detailsMain.append(tracking);
    for (const name of ["status", "rating"]) { const label = labels.get(name); label.classList.remove("music-wide"); if (name === "current_page") label.classList.add("book-fields"); tracking.append(label); }
    labels.get("status").classList.add("entry-status-control");
    const count = document.createElement("label"); count.className = "music-only-detail"; count.innerHTML = 'Completion count<input name="completion_count" type="number" min="0" max="1000000" placeholder="Not set" title="Manual total; never inferred from status.">'; tracking.append(count);
    labels.get("current_page").classList.remove("music-wide"); labels.get("current_page").classList.add("book-fields"); tracking.append(labels.get("current_page"));
    labels.get("favorite").remove();
    const edition = document.createElement("section"); edition.id = "music-edition-info"; edition.className = "collection-edition-info";
    const legacy = form.elements.status.querySelector('[value="collected"]'); legacy.textContent = t("Not set"); legacy.disabled = true; legacy.hidden = true;
    const rating = form.elements.rating, stepper = document.createElement("span"); stepper.className = "number-stepper"; rating.id = "music-personal-rating"; rating.closest("label").htmlFor = rating.id; rating.before(stepper);
    for (const [amount, label] of [[-1, "Decrease personal rating"], [1, "Increase personal rating"]]) { const button = document.createElement("button"); button.type = "button"; button.className = "quiet"; button.textContent = amount < 0 ? "−" : "+"; button.setAttribute("aria-label", t(label)); button.addEventListener("click", () => { const next = rating.value === "" ? 1 : Number(rating.value) + amount * .1; rating.value = Math.max(1, Math.min(10, Math.round(next * 10) / 10)); rating.dispatchEvent(new Event("input", {bubbles: true})); }); if (amount < 0) stepper.append(button, rating); else stepper.append(button); }
    for (const name of ["tags", "notes"]) { labels.get(name).classList.add("span-all"); panels.notes.append(labels.get(name)); }
    labels.get("notes").querySelector("textarea").rows = 4;
    panels.notes.append(membership); membership.classList.add("span-all");
    const effective = document.createElement("div"); effective.id = "music-effective-genres"; effective.className = "span-all entry-fact-grid"; panels.genres.append(effective);
    for (const [name, label] of [["genre_additions", "Add genres"], ["genre_removals", "Remove genres"], ["subgenre_additions", "Add subgenres"], ["subgenre_removals", "Remove subgenres"]]) { const field = document.createElement("label"); field.innerHTML = `${label}<input name="${name}" placeholder="Comma separated">`; panels.genres.append(field); }
    const catalogHeading = document.createElement("div"); catalogHeading.className = "section-heading span-all"; catalogHeading.innerHTML = '<h3>Edit entry details</h3><div class="form-actions"><button type="button" id="music-cancel-catalog" class="quiet">Cancel edit</button><button type="button" id="music-back-metadata" class="quiet">Done editing</button></div>'; panels.catalog.append(catalogHeading);
    for (const name of ["title", "artist", "year", "release_type", "isbn", "publisher", "page_count", "description"]) { const label = labels.get(name); if (["isbn", "publisher", "page_count", "description"].includes(name)) label.classList.add("book-fields"); panels.catalog.append(label); }
    const artControls = document.createElement("section"); artControls.className = "collection-art-controls span-all"; artControls.append(artworkActions, artworkLabel); panels.catalog.append(artControls);
    const metadataHeading = document.createElement("div"); metadataHeading.className = "section-heading"; metadataHeading.innerHTML = '<h3>Catalog metadata</h3>'; metadataHeading.append(lookupButton); panels.metadata.append(metadataHeading);
    const catalogSummary = document.createElement("div"); catalogSummary.id = "music-catalog-summary"; panels.metadata.append(catalogSummary);
    panels.metadata.append(edition);
    const sourceTerms = document.createElement("details"); sourceTerms.className = "optional-details span-all"; sourceTerms.innerHTML = '<summary><span class="disclosure-chevron" aria-hidden="true">›</span> Original source labels</summary><div id="music-raw-provider-terms"></div>'; panels.metadata.append(sourceTerms);
    const catalogTerms = document.createElement("details"); catalogTerms.className = "optional-details span-all"; catalogTerms.innerHTML = '<summary>Edit catalog labels</summary>'; catalogTerms.append(labels.get("genres"), labels.get("subgenres")); panels.catalog.append(catalogTerms);
    const sidecar = document.createElement("aside"); sidecar.id = "music-track-sidecar"; sidecar.className = "connected-sidecar music-only-detail"; sidecar.setAttribute("aria-label", t("Tracklist"));
    const preview = document.createElement("div"); preview.id = "music-track-preview"; preview.className = "collection-track-preview"; sidecar.append(preview);
    const trackEditor = document.createElement("section"); trackEditor.id = "music-track-editor"; trackEditor.hidden = true;
    const trackActions = document.createElement("details"); trackActions.className = "compact-action-menu track-edit-actions"; trackActions.innerHTML = '<summary aria-label="Tracklist actions">•••</summary><div><button type="button" id="music-cancel-tracks" class="quiet">Cancel edit</button><button type="button" id="music-done-tracks" class="quiet">Done editing</button></div>';
    trackActions.querySelector("div").prepend(trackHeading.querySelector("#music-add-track")); trackHeading.append(trackActions);
    trackEditor.append(trackHeading, trackTable); sidecar.append(trackEditor);
    labels.get("chapters").classList.add("span-all"); panels.contents.append(labels.get("chapters"));
    const footer = $(".music-editor-footer"); footer.classList.add("dialog-footer");
    const more = document.createElement("details"); more.id = "music-more-actions"; more.className = "more-actions"; more.innerHTML = '<summary>More actions</summary><div><button type="button" id="music-edit-catalog" class="quiet">Edit entry details</button><button type="button" id="music-edit-tracklist" class="quiet music-only-detail">Edit tracklist</button><button type="button" id="music-browse-artwork" class="quiet">Change artwork</button></div>'; more.querySelector("div").append($("#music-delete")); footer.prepend(more); $("#music-save").textContent = "Save changes";
    // Keep every input inside the same form/disabled fieldset, while the main
    // panels and the connected tracklist scroll independently.
    const panelHost = document.createElement("div"); panelHost.className = "collection-panels";
    panelHost.append(...Object.values(panels));
    content.replaceChildren(tabs, panelHost, $("#music-editor-message"), $("#music-edit-state"));
    const oldHead = dialog.querySelector(".dialog-head"), head = document.createElement("div"); head.className = "dialog-head"; head.append(...oldHead.childNodes); oldHead.remove();
    const close = head.querySelector("button"); close.type = "button"; close.addEventListener("click", () => dialog.close());
    const main = document.createElement("div"); main.className = "detail-main"; main.append(head, shell, footer);
    fieldset.replaceChildren(main, sidecar); form.replaceChildren(fieldset); dialog.append(form);
    const manual = document.createElement("details"); manual.id = "music-manual-entry"; manual.className = "optional-details"; manual.innerHTML = '<summary>Cannot find it?</summary><p class="hint">Try another spelling or add a manual entry. You can attach metadata later.</p><button type="button" id="music-manual-add" class="quiet">Add manually</button>'; $("#music-search-dialog").append(manual);
    const editionContext = document.createElement("div"); editionContext.id = "music-edition-context"; editionContext.hidden = true; editionContext.innerHTML = '<button type="button" id="music-back-book-search" class="quiet">Back to book search</button><strong id="music-edition-title" translate="no"></strong>'; $("#music-search-form").after(editionContext);
    $("#music-back-book-search").addEventListener("click", () => {
      clearTimeout(searchTimer); searchRevision++; searchController?.abort();
      editionContext.hidden = true; $("#music-search-results").setAttribute("aria-busy", "false");
      if (!workResults) { lookup(new Event("submit")); return; }
      const form = $("#music-search-form"); form.elements.query.value = workResults.query; form.elements.artist.value = workResults.artist;
      renderSearchResults(workResults.rows, true); showMessage($("#music-search-status"), t("Choose a book, then choose its edition."));
    });
    const artworkDialog = document.createElement("dialog"); artworkDialog.id = "music-artwork-dialog"; artworkDialog.className = "music-dialog artwork-dialog"; artworkDialog.innerHTML = `<form method="dialog" class="dialog-head"><h2>Change artwork</h2><button class="icon-button dialog-close" aria-label="Close">${icon("close")}</button></form><p id="music-artwork-state" class="message" role="status" aria-live="polite"></p><div id="music-artwork-options" class="artwork-options collection-artwork-options"></div><div class="dialog-footer"><button type="button" id="music-artwork-upload" class="quiet">Upload artwork</button><button type="button" id="music-artwork-apply" disabled>Use selected image</button></div>`; document.body.append(artworkDialog);
    tabs.addEventListener("click", event => { const button = event.target.closest("[data-collection-tab]"); if (button) editorTab(button.dataset.collectionTab); });
    tabs.addEventListener("keydown", event => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; const buttons = $$('[data-collection-tab]:not([hidden])', tabs), index = buttons.indexOf(event.target); if (index < 0) return; event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length; editorTab(buttons[next].dataset.collectionTab); buttons[next].focus(); });
    $("#music-edit-tracklist").addEventListener("click", () => { if (editor?.provider_id) return; trackEdit ??= formValue().tracks.map(track => ({...track})); $("#music-track-editor").hidden = false; $("#music-track-preview").hidden = true; more.open = false; $("#music-track-editor input")?.focus({preventScroll: true}); });
    const finishTracks = cancel => { trackActions.open = false; if (cancel && trackEdit) $("#music-track-rows").replaceChildren(...trackEdit.map(trackRow)); trackEdit = null; $("#music-track-editor").hidden = true; $("#music-track-preview").hidden = false; renderTrackPreview(); dirty(); };
    $("#music-cancel-tracks").addEventListener("click", () => finishTracks(true));
    $("#music-done-tracks").addEventListener("click", () => { const invalid = $("#music-track-editor :invalid"); if (invalid) { invalid.reportValidity(); return; } finishTracks(false); });
    $("#music-browse-artwork").addEventListener("click", () => { more.open = false; chooseArtwork(); });
    const beginCatalogEdit = () => {
      if (editor?.provider_id) return;
      catalogEdit ??= {tab: detailTab === "catalog" ? "details" : detailTab, values: $$('input:not([type="file"]), textarea, select', panels.catalog).map(input => [input, input.value]), artworkData, edition: {...(editor?.edition_info || {})}};
      more.open = false; editorTab("catalog"); $("#music-title").focus({preventScroll: true});
    };
    $("#music-edit-catalog").addEventListener("click", beginCatalogEdit);
    const finishCatalog = cancel => {
      const tab = catalogEdit?.tab || "details";
      if (cancel && catalogEdit) { catalogEdit.values.forEach(([input, value]) => { input.value = value; }); artworkData = catalogEdit.artworkData; if (editor) editor.edition_info = catalogEdit.edition; previewCover(); }
      catalogEdit = null; dirty(); editorTab(tab); $(`[data-collection-tab="${tab}"]`)?.focus({preventScroll: true});
    };
    $("#music-cancel-catalog").addEventListener("click", () => finishCatalog(true));
    $("#music-back-metadata").addEventListener("click", () => { const invalid = $("#music-panel-catalog :invalid"); if (invalid) { invalid.reportValidity(); return; } finishCatalog(false); });
    $("#music-manual-add").addEventListener("click", () => { const title = $("#music-search-form").elements.query.value, artist = $("#music-search-form").elements.artist.value; $("#music-search-dialog").close(); if (searchPurpose === "add") { $("#music-title").value = title; form.elements.artist.value = artist; } openDialog(dialog); editorTab("catalog"); dirty(); $("#music-title").focus({preventScroll: true}); });
    $("#music-artwork-options").addEventListener("change", event => { if (event.target.name !== "collection-artwork") return; artworkSelection = event.target.value; $("#music-artwork-apply").disabled = false; });
    $("#music-artwork-apply").addEventListener("click", () => { if (!artworkSelection) return; artworkData = null; $("#music-art-url").value = artworkSelection; if (editor) editor.edition_info = {...editor.edition_info, artwork_scope: "User-selected artwork"}; previewCover(); dirty(); artworkDialog.close(); editorTab("details"); showMessage($("#music-editor-message"), t("Artwork ready. Save music to keep it.")); });
    $("#music-artwork-upload").addEventListener("click", () => { artworkDialog.close(); $("#music-art-file").click(); });
  }
  document.addEventListener("DOMContentLoaded", () => {
    installImports();
    installMetadataFill();
    installDialogs();
    $$('[data-workspace]').forEach(button => button.addEventListener("click", () => activate(button.dataset.workspace)));
    $("#music-refresh").addEventListener("click", load);
    $("#music-filters").addEventListener("submit", event => event.preventDefault());
    $("#music-toggle-filters").addEventListener("click", () => { const panel = $("#music-filter-options"); panel.hidden = !panel.hidden; $("#music-toggle-filters").setAttribute("aria-expanded", String(!panel.hidden)); });
    document.addEventListener("click", event => { if (!event.target.closest(".collection-filter-control")) { $("#music-filter-options").hidden = true; $("#music-toggle-filters").setAttribute("aria-expanded", "false"); } });
    $("#music-filter-options").addEventListener("keydown", event => { if (event.key === "Escape") { event.stopPropagation(); $("#music-filter-options").hidden = true; $("#music-toggle-filters").setAttribute("aria-expanded", "false"); $("#music-toggle-filters").focus(); } });
    $("#music-sort-direction").addEventListener("click", () => { sortDirection = sortDirection === "desc" ? "asc" : "desc"; page = 1; load(); });
    $("#music-page-size").addEventListener("change", event => { pageSize = Number(event.currentTarget.value); page = 1; load(); });
    let filterTimer;
    $("#music-query").addEventListener("input", () => { clearTimeout(filterTimer); filterTimer = setTimeout(() => { page = 1; load(); }, 180); });
    for (const key of ["music-sort", "music-status"]) $(`#${key}`).addEventListener("change", () => { if (key === "music-sort") sortDirection = ["title", "artist"].includes($("#music-sort").value) ? "asc" : "desc"; page = 1; load(); });
    $("#music-form").addEventListener("input", dirty);
    $("#music-form").addEventListener("change", dirty);
    $("#music-form").addEventListener("submit", save);
    $("#music-form").addEventListener("invalid", event => {
      const panel = event.target.closest("[data-collection-panel]");
      if (panel) editorTab(panel.dataset.collectionPanel);
      if (event.target.closest("#music-track-editor")) { $("#music-track-editor").hidden = false; $("#music-track-preview").hidden = true; }
    }, true);
    const moreActions = $("#music-more-actions");
    document.addEventListener("click", event => { if (!moreActions.contains(event.target)) moreActions.open = false; });
    moreActions.addEventListener("click", event => { if (event.target.closest("button")) moreActions.open = false; });
    $("#music-editor").addEventListener("keydown", event => {
      if (event.key === "Escape" && moreActions.open) { event.preventDefault(); event.stopPropagation(); moreActions.open = false; moreActions.querySelector("summary").focus(); }
    });
    $("#music-editor").addEventListener("cancel", event => { if (busy) event.preventDefault(); });
    $("#music-editor").addEventListener("close", () => { searchRevision++; moreActions.open = false; });
    $("#music-add-track").addEventListener("click", () => { if (editor?.provider_id) return; $(".track-edit-actions").open = false; $("#music-track-rows").append(trackRow()); $("#music-track-rows tr:last-child .track-title").focus(); dirty(); });
    $("#music-art-url").addEventListener("change", previewCover);
    $("#music-art-remove").addEventListener("click", () => { artworkData = null; $("#music-art-url").value = ""; previewCover(); dirty(); });
    $("#music-art-file").addEventListener("change", async event => {
      const input = event.currentTarget, file = input.files[0]; if (!file) return;
      const body = new FormData(); body.append("file", file); editorBusy(true, "Preparing artwork…");
      try { artworkData = (await api("/api/music/artwork", {method: "POST", body})).artwork_data; previewCover(); showMessage($("#music-editor-message"), t("Artwork ready. Save music to keep it.")); }
      catch (error) { showMessage($("#music-editor-message"), error.message, true); }
      finally { input.value = ""; busy = false; disableEditorFields(false); $("#music-editor .dialog-close").disabled = false; $("#music-delete").disabled = false; $("#music-form").setAttribute("aria-busy", "false"); dirty(); }
    });
    $("#music-find-metadata").addEventListener("click", () => {
      searchPurpose = "metadata";
      clearTimeout(searchTimer); searchRevision++; searchController?.abort(); workResults = null; $("#music-edition-context").hidden = true;
      const form = $("#music-search-form"); form.elements.query.value = $("#music-title").value; form.elements.artist.value = $("#music-form").elements.artist.value;
      $("#music-search-results").replaceChildren(); showMessage($("#music-search-status"), ""); openDialog($("#music-search-dialog")); form.elements.query.focus();
    });
    $("#music-search-dialog").addEventListener("close", () => { clearTimeout(searchTimer); searchRevision++; searchController?.abort(); });
    $("#music-search-form").addEventListener("submit", lookup);
    $("#music-search-form").addEventListener("input", () => { clearTimeout(searchTimer); searchRevision++; searchController?.abort(); searchTimer = setTimeout(() => lookup(), 550); });
    $("#music-search-results").addEventListener("click", event => { const work = event.target.closest("[data-book-work]"); if (work) return showEditions(searchRows[Number(work.dataset.bookWork)]); const button = event.target.closest("[data-music-result]"); if (button) selectResult(button.dataset.musicResult); });
    $("#music-delete").addEventListener("click", async event => {
      if (!editor?.id || busy) return;
      const button = event.currentTarget, {id, version} = editor, workspace = mode;
      button.disabled = true;
      try {
        if (!await confirmAction(t("Remove from music?"), t("Only this music entry is removed. Movies, TV, anime and other music are unchanged. Full backups retain removed entries."), t("Remove"))) return;
        if (mode !== workspace || editor?.id !== id || !$("#music-editor").open) return;
        await api(`/api/music/albums/${id}?version=${version}`, {method: "DELETE"}, workspace);
        if (mode === workspace && editor?.id === id) { $("#music-editor").close(); await load(); }
      } catch (error) { if (mode === workspace && editor?.id === id) showMessage($("#music-editor-message"), error.message, true); }
      finally { button.disabled = false; }
    });
    $("#music-list-picker").addEventListener("change", async event => {
      const input = event.target.closest("[data-music-membership]"); if (!input || !editor?.id) return;
      const row = listRows.find(row => row.id === input.dataset.musicMembership); input.disabled = true;
      try { await api(`/api/music/lists/${row.id}`, {method: "PUT", body: JSON.stringify({name: row.name, version: row.version, album_ids: input.checked ? [...row.album_ids, editor.id] : row.album_ids.filter(id => id !== editor.id)})}); await memberships(); }
      catch (error) { input.checked = !input.checked; showMessage($("#music-editor-message"), error.message, true); }
      finally { input.disabled = false; }
    });
    $("#music-view").addEventListener("click", async event => {
      const target = event.target.closest("button"); if (!target) return;
      const workspace = mode;
      if (target.hasAttribute("data-open-music")) return openEditor(target.dataset.openMusic);
      if (target.hasAttribute("data-reveal-music")) { const card = target.closest(".music-card"), open = !card.classList.contains("music-reveal-open"); card.classList.toggle("music-reveal-open", open); target.setAttribute("aria-expanded", String(open)); return; }
      if (target.dataset.openMusicList) { selectedList = listRows.find(row => row.id === target.dataset.openMusicList); page = 1; return load(); }
      try {
        if (target.dataset.removeCollectionItem && selectedList) {
          const listId = selectedList.id, itemId = target.dataset.removeCollectionItem;
          target.disabled = true;
          // Re-read membership before writing; optimistic version checks reject
          // concurrent edits rather than discarding another window's changes.
          const lists = await api("/api/music/lists", {}, workspace), row = lists.items.find(item => item.id === listId);
          if (!row) throw new Error(t("List no longer exists."));
          const remaining = row.album_ids.filter(id => id !== itemId);
          const updated = await api(`/api/music/lists/${listId}`, {method: "PUT", body: JSON.stringify({name: row.name, version: row.version, album_ids: remaining})}, workspace);
          if (workspace === mode && selectedList?.id === listId) { selectedList = {...row, ...updated, album_ids: remaining, version: row.version + 1}; await load(); }
        }
        if (target.dataset.favoriteMusic) {
          target.disabled = true;
          const row = await api(`/api/music/albums/${target.dataset.favoriteMusic}`, {}, workspace), payload = {};
          fields.forEach(key => { payload[key] = row[key]; });
          payload.favorite = !row.favorite; payload.version = row.version;
          await api(`/api/music/albums/${row.id}`, {method: "PUT", body: JSON.stringify(payload)}, workspace); if (workspace === mode) await load();
        }
        if (target.dataset.deleteMusicList) {
          const row = selectedList?.id === target.dataset.deleteMusicList ? selectedList : listRows.find(row => row.id === target.dataset.deleteMusicList);
          if (await confirmAction(t("Delete list"), t("Only the list is removed. Your music stays in the collection."), t("Delete list"))) { await api(`/api/music/lists/${row.id}?version=${row.version}`, {method: "DELETE"}, workspace); if (workspace === mode) { selectedList = null; await load(); } }
        }
        if (target.dataset.renameMusicList) {
          const row = selectedList?.id === target.dataset.renameMusicList ? selectedList : listRows.find(row => row.id === target.dataset.renameMusicList);
          const card = target.closest(".music-list-card") || $("#music-selected-list-actions");
          if (card.querySelector(".music-rename-form")) return;
          const form = document.createElement("form"); form.className = "music-rename-form";
          form.innerHTML = `<input name="name" value="${html(row.name)}" aria-label="${html(t("List name"))}" maxlength="150" required><button type="submit">${html(t("Save"))}</button><button type="button" class="quiet">${html(t("Cancel"))}</button>`;
          card.append(form); form.elements.name.focus();
          form.querySelector('[type="button"]').addEventListener("click", () => form.remove());
          form.addEventListener("submit", async event => {
            event.preventDefault(); const button = form.querySelector('[type="submit"]'); button.disabled = true;
            try { const updated = await api(`/api/music/lists/${row.id}`, {method: "PUT", body: JSON.stringify({name: form.elements.name.value.trim(), album_ids: row.album_ids, version: row.version})}, workspace); if (workspace === mode && selectedList?.id === row.id) { selectedList = {...row, ...updated, name: form.elements.name.value.trim(), version: row.version + 1}; $("#music-selected-list-actions")?.remove(); await load(); } }
            catch (error) { if (workspace === mode) showMessage($("#music-state"), error.message, true); }
            finally { button.disabled = false; }
          });
        }
      } catch (error) { if (workspace === mode) showMessage($("#music-state"), error.message, true); }
      finally { target.disabled = false; }
    });
    $("#collection-export-scope").addEventListener("change", event => { event.currentTarget.dataset.chosen = "true"; exportScope(); });
    $("#music-import-file").addEventListener("change", async event => {
      const revision = ++importRevision;
      importDraft = null; $("#music-import-confirm").hidden = true;
      const file = event.currentTarget.files[0];
      if (!file) { showMessage($("#music-import-status"), ""); return; }
      showMessage($("#music-import-status"), translatedText("Inspecting collection file…"));
      try {
        if (file.size > 20 * 1024 * 1024) throw new Error(translatedText("Choose a collection file smaller than 20 MB."));
        const document = JSON.parse(await file.text());
        if (revision !== importRevision) return;
        const domain = document.format === "pmt-music-collection" ? "music" : document.format === "pmt-book-collection" ? "books" : null;
        if (!domain) throw new Error(translatedText("Choose a PMT music or book collection JSON file."));
        if (!importDomain || domain !== importDomain) throw new Error(translatedText("This file belongs to a different collection. Close this dialog and choose the matching collection."));
        const preview = await window.api(`/api/${domain}/import/preview`, {method: "POST", body: JSON.stringify({document})});
        if (revision !== importRevision) return;
        importDraft = {domain, document, sha256: preview.sha256};
        showMessage($("#music-import-status"), `${preview.new_albums ?? preview.new_books} ${translatedText(domain === "books" ? "new books" : "new releases")} · ${preview.skipped} ${t("already stored")} · ${preview.lists} ${t("lists")}`);
        const checkLabels = {missing_creator: "Missing credited creators", short_creator: "Short or truncated creators — please review", supplied_identity: "Supplied catalog identifiers", conflicting_identity: "Conflicting title or edition for the same identifier"};
        for (const check of preview.identity_checks || []) $("#music-import-status").append(document.createTextNode(` · ${check.count} ${translatedText(checkLabels[check.code] || "Needs review")}`));
        $("#music-import-confirm").hidden = false;
      } catch (error) { if (revision === importRevision) showMessage($("#music-import-status"), error.message, true); }
    });
    $("#music-import-confirm").addEventListener("click", async event => {
      if (!importDraft || importCommitting) return; const button = event.currentTarget; button.disabled = true; importCommitting = true;
      $("#music-import-file").disabled = true; $("#collection-import-dialog .dialog-close").disabled = true;
      const revision = importRevision, draft = importDraft;
      showMessage($("#music-import-status"), translatedText("Importing collection…"));
      try { const {domain, ...payload} = draft; payload.fill_metadata = $("#collection-import-fill").checked; const result = await window.api(`/api/${domain}/import`, {method: "POST", body: JSON.stringify(payload)}); if (revision === importRevision) { importDraft = null; button.hidden = true; showMessage($("#music-import-status"), translatedText("Collection imported. Existing entries were not overwritten.")); if (result.metadata) { $("#collection-import-dialog").close(); openFill(domain); } } if (active()) await load(); }
      catch (error) { if (revision === importRevision) showMessage($("#music-import-status"), error.message, true); }
      finally { button.disabled = false; importCommitting = false; $("#music-import-file").disabled = false; $("#collection-import-dialog .dialog-close").disabled = false; }
    });
    settings();
  });
  window.PMTMusic = {active, activate, restore, route, persist, openEditor, settings, load, refreshLabels, applyPreferences, quickAdd, openImportChooser, diagnostics: () => requests.diagnostics()};
})();
