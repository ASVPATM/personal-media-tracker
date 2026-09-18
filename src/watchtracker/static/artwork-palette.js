/* Small, device-local colour samples. Never uploads artwork or stores history. */
(() => {
  const cache = new Map();
  const remote = new Map();
  const linear = value => { const x = value / 255; return x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4; };
  const luminanceOf = rgb => .2126 * linear(rgb[0]) + .7152 * linear(rgb[1]) + .0722 * linear(rgb[2]);
  const contrast = (one, two) => (Math.max(luminanceOf(one), luminanceOf(two)) + .05) / (Math.min(luminanceOf(one), luminanceOf(two)) + .05);
  function sample(img) {
    const canvas = document.createElement("canvas"); canvas.width = canvas.height = 12;
    const ctx = canvas.getContext("2d", {willReadFrequently: true});
    ctx.drawImage(img, 0, img.naturalHeight * .45, img.naturalWidth, img.naturalHeight * .55, 0, 0, 12, 12);
    const pixels = ctx.getImageData(0, 0, 12, 12).data, rgb = [0, 0, 0]; let n = 0;
    for (let i = 0; i < pixels.length; i += 4) { if (pixels[i + 3] < 180) continue; n++; for (let c = 0; c < 3; c++) rgb[c] += pixels[i + c]; }
    if (!n) return null;
    const average = rgb.map(value => Math.round(value / n));
    return paletteFor(average);
  }
  function paletteFor(average) {
    const luminance = luminanceOf(average);
    const light = luminance > .23;
    // Blend towards a safe light/dark surface so text stays readable even over
    // highly varied artwork underneath the translucent panel.
    let surface = average.map(value => Math.round(value * .45 + (light ? 250 : 12) * .55));
    const ink = light ? [17, 24, 32] : [255, 255, 255], muted = light ? [48, 59, 67] : [225, 232, 237];
    const backdrop = () => surface.map(value => value * .86 + (light ? 0 : 255) * .14);
    // Test the least favorable underlying pixels, not just the average art.
    for (let step = 0; step < 10 && contrast(ink, backdrop()) < 4.5; step++) surface = surface.map(value => Math.round(value * .8 + (light ? 255 : 0) * .2));
    const inkColor = light ? "#111820" : "#ffffff";
    return {bg: `rgb(${surface.join(" ")} / 86%)`, ink: inkColor, muted: contrast(muted, backdrop()) >= 4.5 ? (light ? "#303b43" : "#e1e8ed") : inkColor, surface: `rgb(${surface.join(" ")})`};
  }
  function apply(card, palette) {
    if (!palette || !card.isConnected) return;
    for (const [key, value] of Object.entries(palette)) card.style.setProperty(`--reveal-${key}`, value);
  }
  function inspect(img) {
    const card = img.closest(".entry-card, .ranking-tile, .recommendation-result");
    if (!card || !img.naturalWidth) return;
    const url = img.currentSrc || img.src;
    if (cache.has(url) && cache.get(url)) { apply(card, cache.get(url)); return; }
    if (cache.has(url)) { remoteSample(img, card, url); return; }
    try { const value = sample(img); cache.set(url, value); apply(card, value); }
    catch (_) {
      // Visible cross-origin artwork isn't necessarily readable by canvas.
      // Keep the accessible fallback, without another request or CORS probe.
      cache.set(url, null);
      remoteSample(img, card, url);
    }
    if (cache.size > 256) cache.delete(cache.keys().next().value);
  }
  function remoteSample(img, card, url) {
    // Only visible Screen reveal cards need this fallback. The app resolves an
    // owned entry and samples allowlisted provider artwork; no CORS image probes.
    if (!card.classList.contains("media-artwork-card") || !card.dataset.entry) return;
    const key = `${card.dataset.entry}:${url}`;
    if (!remote.has(key)) {
      const request = fetch(`/api/entries/${encodeURIComponent(card.dataset.entry)}/artwork-palette`)
        .then(response => response.ok ? response.json() : null)
        .then(data => {
          if (data?.url !== url || !Array.isArray(data.rgb) || data.rgb.length !== 3 || !data.rgb.every(n => Number.isFinite(n) && n >= 0 && n <= 255)) return null;
          const value = paletteFor(data.rgb); cache.set(url, value); return value;
        }).catch(() => null);
      remote.set(key, request);
      if (remote.size > 256) remote.delete(remote.keys().next().value);
    }
    remote.get(key).then(value => { if ((img.currentSrc || img.src) === url) apply(card, value); });
  }
  document.addEventListener("load", event => { if (event.target instanceof HTMLImageElement) inspect(event.target); }, true);
  window.PMTArtworkPalette = {inspect};
})();
