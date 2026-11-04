/* Fade only clipped text, preserving scroll access and the adjacent actions. */
window.PMTOverflowFades = (() => {
  const nodes = new Set();
  const update = node => {
    const overflow = node.scrollWidth - node.clientWidth > 2;
    node.classList.toggle("fade-overflow-start", overflow && node.scrollLeft > 2);
    node.classList.toggle("fade-overflow-end", overflow && node.scrollLeft + node.clientWidth < node.scrollWidth - 2);
  };
  const observer = new ResizeObserver(entries => entries.forEach(entry => update(entry.target)));
  return {observe(root) {
    for (const node of nodes) if (!node.isConnected) { observer.unobserve(node); nodes.delete(node); }
    root.querySelectorAll(".pmt-artwork-panel .entry-signals, .music-reveal-panel .entry-signals, .music-reveal-panel h3").forEach(node => {
      if (!nodes.has(node)) { nodes.add(node); observer.observe(node); node.addEventListener("scroll", () => update(node), {passive: true}); }
      update(node);
    });
  }};
})();
