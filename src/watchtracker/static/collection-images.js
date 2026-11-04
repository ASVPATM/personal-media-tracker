/* Bounded image listeners, fallbacks and visible-first artwork. */
window.PMTCollectionImages = {create({html, icon}) {
  const boundCoverImages = new WeakSet(), boundRevealCards = new WeakSet();
  function cover(url, title, fallbacks = []) {
    return `<span class="music-cover">${icon("music")}${url ? `<img src="${html(url)}" alt="${html(title)}" loading="lazy" decoding="async" data-artwork-fallbacks="${html(JSON.stringify(fallbacks.slice(0, 3)))}" referrerpolicy="no-referrer">` : ""}</span>`;
  }
  function images(root) {
    window.PMTOverflowFades?.observe(root);
    root.querySelectorAll(".music-cover img").forEach(img => { if (img.complete) window.PMTArtworkPalette?.inspect(img); });
    root.querySelectorAll(".music-cover img").forEach(img => {
      if (boundCoverImages.has(img)) return;
      boundCoverImages.add(img);
      const ready = () => {
        if (!img.naturalWidth) return;
        img.hidden = false;
        const card = img.closest(".music-card");
        // Do not let the decorative CSS background bypass image lazy loading.
        if (card) card.style.setProperty("--collection-art", `url(${JSON.stringify(img.currentSrc || img.src)})`);
        window.PMTArtworkPalette?.inspect(img);
      };
      const rect = img.getBoundingClientRect();
      if (rect.width && rect.bottom > 0 && rect.top < innerHeight) {
        img.loading = "eager";
        img.fetchPriority = "high";
      }
      const remaining = JSON.parse(img.dataset.artworkFallbacks || "[]");
      const failed = () => { const next = remaining.shift(); if (next) img.src = next; else img.hidden = true; };
      img.addEventListener("error", failed);
      img.addEventListener("load", ready);
      if (img.complete && !img.naturalWidth) failed();
      else if (img.complete) ready();
    });
    root.querySelectorAll(".music-reveal-card").forEach(card => {
      if (boundRevealCards.has(card)) return;
      boundRevealCards.add(card);
      const trigger = card.querySelector("[data-reveal-music]");
      const toggle = value => { card.classList.toggle("music-reveal-open", value); trigger.setAttribute("aria-expanded", String(value)); };
      card.addEventListener("pointerenter", event => { if (event.pointerType === "mouse") toggle(true); });
      card.addEventListener("pointerleave", event => { if (event.pointerType === "mouse" && !card.contains(document.activeElement)) toggle(false); });
      card.addEventListener("focusout", () => requestAnimationFrame(() => { if (!card.contains(document.activeElement)) toggle(false); }));
      card.addEventListener("keydown", event => { if (event.key === "Escape") { toggle(false); trigger.focus(); event.stopPropagation(); } });
    });
  }
  return {cover, images};
}};
