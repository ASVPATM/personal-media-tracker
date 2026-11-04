/* Short-lived, principal-bound page snapshots; speculative work never owns navigation. */
window.PMTCollectionNavigation = {create() {
  let revision = 0, controller = null, speculative = null, family = "", epoch = 0;
  const pages = new Map(), metrics = {hits: 0, misses: 0, warmed: 0, speculativeCovers: 0, jsonMs: 0, renderMs: 0, navigations: 0};
  let started = 0;
  const reset = () => { epoch++; speculative?.abort(); speculative = null; pages.clear(); family = ""; };
  const abort = () => { revision++; controller?.abort(); controller = null; reset(); };
  const allowed = () => {
    const connection = navigator.connection;
    if (document.hidden || document.querySelector("dialog[open]") || connection?.saveData || ["slow-2g", "2g"].includes(connection?.effectiveType)) return false;
    return ![...document.querySelectorAll("#music-content .music-cover img")].some(img => {
      const rect = img.getBoundingClientRect();
      return rect.width && rect.bottom > 0 && rect.top < innerHeight && !img.complete;
    });
  };
  const keyFor = (scope, url) => {
    const parsed = new URL(url, location.origin);
    const number = Number(parsed.searchParams.get("page") || 1);
    parsed.searchParams.delete("page"); parsed.searchParams.sort();
    const next = `${scope}:${parsed.pathname}?${parsed.searchParams}`;
    if (next !== family) { reset(); family = next; }
    return number;
  };
  const store = (number, data, expectedEpoch) => {
    if (epoch !== expectedEpoch || JSON.stringify(data).length > 512 * 1024) return;
    pages.set(number, {data: structuredClone(data), expires: performance.now() + 15000});
    while (pages.size > 3) pages.delete(pages.keys().next().value);
  };
  document.addEventListener("pmt-data-changed", reset);
  document.addEventListener("pmt-principal-changed", abort);
  document.addEventListener("visibilitychange", () => { if (document.hidden) reset(); });
  return {
    get revision() { return revision; }, get controller() { return controller; },
    begin() { controller?.abort(); controller = new AbortController(); revision++; started = performance.now(); metrics.navigations++; return {controller, revision}; },
    end(value) { if (value === revision) { controller = null; metrics.renderMs = performance.now() - started; } },
    abort, invalidate: reset,
    async read(scope, url, fetchPage, {signal, fresh = false} = {}) {
      const number = keyFor(scope, url), current = pages.get(number), expectedEpoch = epoch;
      if (!fresh && current && current.expires > performance.now()) { metrics.hits++; return structuredClone(current.data); }
      metrics.misses++;
      const before = performance.now();
      let data;
      if (!fresh && speculative?.url === url && speculative.promise) {
        try { data = await speculative.promise; }
        catch (error) { if (signal?.aborted) throw error; }
      }
      if (signal?.aborted) throw new DOMException("Navigation superseded", "AbortError");
      if (!data) data = await fetchPage(url, {signal});
      metrics.jsonMs = performance.now() - before;
      store(number, data, expectedEpoch);
      return data;
    },
    bindNext(nav, number, scope, url, fetchPage) {
      const buttons = nav.querySelectorAll(`[data-page="${number + 1}"]:not(:disabled)`);
      const warm = async () => {
        if (!allowed() || controller || speculative) return;
        const parsed = new URL(url, location.origin); parsed.searchParams.set("page", number + 1);
        const target = `${parsed.pathname}?${parsed.searchParams}`, pageNumber = keyFor(scope, target);
        if (pages.get(pageNumber)?.expires > performance.now()) return;
        const expectedEpoch = epoch, work = new AbortController(); speculative = work;
        try {
          work.url = target; work.promise = fetchPage(target, {signal: work.signal});
          const data = await work.promise;
          if (expectedEpoch !== epoch || work.signal.aborted) return;
          store(pageNumber, data, expectedEpoch); metrics.warmed++;
          for (const row of data.items.slice(0, 4)) {
            if (!row.cover_url || !allowed() || expectedEpoch !== epoch || controller) break;
            const imageURL = new URL(row.cover_url, location.origin);
            if (imageURL.origin !== location.origin) continue;
            // One low-priority image at a time, bounded even if the provider stalls.
            await new Promise(resolve => {
              const img = new Image(); let timer;
              const done = () => { clearTimeout(timer); work.signal.removeEventListener("abort", cancel); img.onload = img.onerror = null; resolve(); };
              const cancel = () => { img.src = ""; done(); };
              img.decoding = "async"; img.fetchPriority = "low"; img.onload = img.onerror = done;
              work.signal.addEventListener("abort", cancel, {once: true}); timer = setTimeout(cancel, 2500);
              img.src = imageURL.href; metrics.speculativeCovers++;
            });
          }
        } catch (_) { /* Speculation cannot put an error into the visible page. */ }
        finally { if (speculative === work) speculative = null; }
      };
      buttons.forEach(button => { button.addEventListener("pointerenter", warm); button.addEventListener("focus", warm); });
    },
    diagnostics() { return {...metrics, snapshots: pages.size, inflight: Boolean(controller), speculative: Boolean(speculative)}; }
  };
}};
