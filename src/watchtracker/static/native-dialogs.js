/* Managed desktop dialogs; keeps the native title-bar drag region usable. */
const nativeDialogStack = [];
const nativeDialogReturnFocus = new WeakMap();

function syncNativeDialogLayer() {
  if (!state.nativeWindow) return;
  // DOM order is not opening order: shared confirmations precede dynamically
  // created collection editors in the document. Keep the real nested stack.
  for (let index = nativeDialogStack.length - 1; index >= 0; index--) {
    const dialog = nativeDialogStack[index];
    if (dialog.open && dialog.isConnected) continue;
    nativeDialogStack.splice(index, 1);
    dialog.inert = false;
    dialog.classList.remove("native-dialog-active");
    dialog.style.removeProperty("z-index");
    dialog.removeAttribute("aria-modal");
  }
  const top = nativeDialogStack.at(-1);
  nativeDialogStack.forEach((dialog, index) => {
    dialog.classList.toggle("native-dialog-active", dialog === top);
    dialog.inert = dialog !== top;
    dialog.style.zIndex = String(9001 + index);
    dialog.setAttribute("aria-modal", String(dialog === top));
  });
  if (top) document.documentElement.dataset.nativeDialogOpen = "true";
  else delete document.documentElement.dataset.nativeDialogOpen;
}

function openDialog(dialog) {
  if (!dialog || dialog.open) return;
  if (state.nativeWindow) {
    // A modal dialog enters the browser top layer and covers pywebview's drag
    // regions. Native windows use an equivalent managed non-modal layer so the
    // macOS title bar remains draggable while the app content stays blocked.
    nativeDialogReturnFocus.set(dialog, document.activeElement);
    dialog.inert = false;
    dialog.show();
    nativeDialogStack.push(dialog);
    syncNativeDialogLayer();
    return;
  }
  dialog.showModal();
}

function initializeNativeDialogs() {
  const menuTimers = new WeakMap();
  const floatingMenus = new Set();
  const hideMenuPanel = panel => { if (panel?.hasAttribute("popover") && panel.matches(":popover-open")) panel.hidePopover(); };
  const positionMenu = menu => {
    const panel = menu.querySelector(":scope > div"), anchor = menu.querySelector("summary");
    if (!panel || !anchor || !menu.open || !menu.isConnected || !anchor.getClientRects().length) {
      hideMenuPanel(panel); floatingMenus.delete(menu); return;
    }
    const box = anchor.getBoundingClientRect(), bounds = panel.getBoundingClientRect();
    const viewport = window.visualViewport;
    const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
    const topEdge = viewport?.offsetTop || 0, leftEdge = viewport?.offsetLeft || 0;
    const below = topEdge + height - box.bottom - 12, above = box.top - topEdge - 12;
    const up = bounds.height > below && above > below;
    panel.style.maxHeight = `${Math.max(60, up ? above : below)}px`;
    panel.style.left = `${Math.max(leftEdge + 8, Math.min(box.right - bounds.width, leftEdge + width - bounds.width - 8))}px`;
    panel.style.top = `${up ? Math.max(topEdge + 8, box.top - panel.offsetHeight - 4) : box.bottom + 4}px`;
  };
  const floatMenu = menu => {
    if (!menu.matches(".compact-action-menu")) return;
    const panel = menu.querySelector(":scope > div");
    if (!panel) return;
    // The top layer escapes scrolling sidecars without moving the actions out
    // of their details element, preserving handlers, tab order and labels.
    if (typeof panel.showPopover !== "function") {
      panel.classList.add("menu-inline-fallback"); return;
    }
    panel.setAttribute("popover", "manual");
    if (!panel.matches(":popover-open")) panel.showPopover();
    floatingMenus.add(menu); positionMenu(menu);
  };
  // Restoring focus after a pointer-opened dialog must not leave a second
  // tile highlighted. Keyboard users retain the same focus affordance.
  document.addEventListener("pointerdown", () => { document.documentElement.dataset.inputModality = "pointer"; }, true);
  document.addEventListener("keydown", event => {
    if (["Tab", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key)) document.documentElement.dataset.inputModality = "keyboard";
  }, true);
  const closeMenu = menu => { hideMenuPanel(menu.querySelector(":scope > div")); floatingMenus.delete(menu); menu.open = false; delete menu.dataset.hoverOpened; delete menu.dataset.menuInteraction; };
  document.addEventListener("toggle", event => {
    const menu = event.target;
    if (!menu.matches?.("details.compact-action-menu")) return;
    if (menu.open) floatMenu(menu); else closeMenu(menu);
  }, true);
  document.addEventListener("pointerdown", event => {
    for (const menu of floatingMenus) if (!menu.contains(event.target)) closeMenu(menu);
  }, true);
  document.addEventListener("close", event => {
    for (const menu of floatingMenus) if (event.target.contains(menu)) closeMenu(menu);
  }, true);
  document.addEventListener("scroll", event => {
    for (const menu of floatingMenus) if (!menu.querySelector(":scope > div")?.contains(event.target)) positionMenu(menu);
  }, true);
  window.addEventListener("resize", () => floatingMenus.forEach(positionMenu));
  window.visualViewport?.addEventListener("resize", () => floatingMenus.forEach(positionMenu));
  document.addEventListener("keydown", event => {
    const menu = event.target.closest?.("details:is(.more-actions, .compact-action-menu)");
    if (!menu) return;
    menu.dataset.menuInteraction = "keyboard";
    delete menu.dataset.hoverOpened;
    clearTimeout(menuTimers.get(menu));
    if (event.key === "Escape" && menu.open) {
      event.preventDefault(); event.stopImmediatePropagation(); closeMenu(menu); menu.querySelector("summary").focus();
    } else if (event.target.matches("summary") && ["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      menu.open = true;
      floatMenu(menu);
      const actions = [...menu.querySelectorAll("button:not(:disabled), a[href]")].filter(node => !node.closest("[hidden]"));
      (event.key === "ArrowUp" ? actions.at(-1) : actions[0])?.focus();
    }
  });
  document.addEventListener("pointerover", event => {
    if (!matchMedia("(hover: hover) and (pointer: fine)").matches) return;
    const menu = event.target.closest?.("details:is(.more-actions, .compact-action-menu)");
    // A menu action may hide itself while the pointer is still above it.
    // WebKit then reports that hidden action as relatedTarget when the user
    // returns to the summary; a closed menu must still be able to reopen.
    if (!menu || (menu.open && menu.contains(event.relatedTarget))) return;
    clearTimeout(menuTimers.get(menu));
    menu.dataset.menuInteraction = "pointer";
    if (!menu.open) { menu.dataset.hoverOpened = "true"; menu.open = true; }
    floatMenu(menu);
  });
  document.addEventListener("pointerout", event => {
    const menu = event.target.closest?.("details:is(.more-actions, .compact-action-menu)");
    if (!menu || menu.contains(event.relatedTarget)) return;
    menuTimers.set(menu, setTimeout(() => { if (!menu.matches(":hover") && menu.dataset.menuInteraction !== "keyboard") closeMenu(menu); }, 100));
  });
  document.addEventListener("focusout", event => {
    const menu = event.target.closest?.("details:is(.more-actions, .compact-action-menu)");
    if (menu && !menu.contains(event.relatedTarget) && !menu.matches(":hover")) closeMenu(menu);
  });
  document.addEventListener("click", event => {
    const summary = event.target.closest?.("details:is(.more-actions, .compact-action-menu) > summary");
    if (summary?.parentElement.dataset.hoverOpened) {
      event.preventDefault(); summary.parentElement.open = true;
      delete summary.parentElement.dataset.hoverOpened;
    }
  });
  // A label wrapping several buttons otherwise associates with the first
  // minus button. Label hover/click must target the numeric input itself.
  $$(".number-stepper").forEach(stepper => {
    const input = stepper.querySelector("input"), label = stepper.closest("label");
    if (input?.id && label) label.htmlFor = input.id;
  });
  if (state.nativeWindow) {
    // Capture also covers editors added after the main app initializes.
    document.addEventListener("close", event => {
      if (!(event.target instanceof HTMLDialogElement)) return;
      const wasTop = nativeDialogStack.at(-1) === event.target;
      syncNativeDialogLayer();
      const target = nativeDialogReturnFocus.get(event.target);
      if (wasTop && target?.isConnected && !target.closest("[inert]")) target.focus({preventScroll: true});
    }, true);
    document.addEventListener("keydown", event => {
      const dialog = $("dialog.native-dialog-active[open]");
      if (!dialog) return;
      if (event.key === "Tab") {
        const controls = $$('button, input, select, textarea, a[href], [tabindex="0"]', dialog).filter(node => !node.disabled && !node.closest("[hidden], [inert]") && node.getClientRects().length);
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) { event.preventDefault(); first?.focus(); }
        return;
      }
      if (event.key !== "Escape") return;
      event.preventDefault();
      const cancelEvent = new Event("cancel", {cancelable: true});
      if (dialog.dispatchEvent(cancelEvent)) dialog.close("cancel");
    });
  }
}
