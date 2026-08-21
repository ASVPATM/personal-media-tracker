try {
  if (new URLSearchParams(window.location.search).get("desktop") === "macos") {
    document.documentElement.dataset.desktop = "macos";
  }
  const theme = localStorage.getItem("watchtracker-theme");
  if (theme && theme !== "system") document.documentElement.dataset.theme = theme;
  const accent = localStorage.getItem("watchtracker-accent");
  if (accent) document.documentElement.dataset.accent = accent;
  if (localStorage.getItem("watchtracker-media-artwork-tint") === "true") {
    document.documentElement.dataset.mediaArtworkTint = "true";
  }
  const customAccent = localStorage.getItem("watchtracker-accent-custom");
  if (customAccent && /^#[0-9a-f]{6}$/i.test(customAccent)) {
    const accentChannels = customAccent.slice(1).match(/.{2}/g).map(value => Number.parseInt(value, 16) / 255);
    const accentLuminance = accentChannels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    document.documentElement.dataset.customAccent = "true";
    document.documentElement.dataset.accentTone = accentLuminance < .34 ? "dark" : "light";
    document.documentElement.style.setProperty("--accent-choice", customAccent);
  }
  const background = localStorage.getItem("watchtracker-background");
  if (background && /^#[0-9a-f]{6}$/i.test(background)) {
    const strengthValue = Number(localStorage.getItem("watchtracker-background-strength"));
    const strength = Number.isFinite(strengthValue) && strengthValue >= 0 && strengthValue <= 100 ? strengthValue : 16;
    const mode = localStorage.getItem("watchtracker-background-mode") === "full" ? "full" : "adaptive";
    const channels = background.slice(1).match(/.{2}/g).map(value => Number.parseInt(value, 16) / 255);
    const luminance = channels.map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
    document.documentElement.dataset.customBackground = "true";
    document.documentElement.dataset.backgroundMode = mode;
    document.documentElement.dataset.backgroundTone = luminance < .34 ? "dark" : "light";
    document.documentElement.style.setProperty("--background-choice", background);
    document.documentElement.style.setProperty("--background-strength", `${strength}%`);
    document.documentElement.style.setProperty("--surface-tint-strength", `${Math.max(3, strength * .55)}%`);
    document.documentElement.style.setProperty("--raised-tint-strength", `${Math.max(2, strength * .36)}%`);
    document.documentElement.style.setProperty("--line-tint-strength", `${Math.max(8, strength * .8)}%`);
  }
  const language = localStorage.getItem("watchtracker-interface-language");
  document.documentElement.lang = ["fr", "zh-CN"].includes(language) ? language : "en";
} catch (_) {
  // Local preferences are optional.
}
