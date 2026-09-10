const SUPPORTED_SEASONS = new Set(["2025-26", "2024-25", "2023-24"]);

export function selectedSeason() {
  const href = globalThis.location?.href;
  if (!href) return "2025-26";
  const season = new URL(href, "http://localhost").searchParams.get("season");
  return SUPPORTED_SEASONS.has(season) ? season : "2025-26";
}

export function withSeason(input, season = selectedSeason()) {
  if (season === "2025-26" || typeof input !== "string" || input.startsWith("#")) return input;
  const base = globalThis.location?.href || "http://localhost/";
  const url = new URL(input, base);
  if (url.origin !== new URL(base).origin) return input;
  url.searchParams.set("season", season);
  return input.startsWith("http") ? url.href : url.pathname + url.search + url.hash;
}

export function seasonFetch(input, options) {
  return globalThis.fetch(withSeason(input), options);
}

function initializeSeasonNavigation() {
  const selector = document.querySelector("[data-season-selector]");
  selector?.addEventListener("change", () => {
    const path = /^(\/players\/|\/compare)/.test(location.pathname)
      ? "/performance" : location.pathname;
    location.assign(`${path}?season=${encodeURIComponent(selector.value)}`);
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (link && !link.hasAttribute("download")) {
      link.setAttribute("href", withSeason(link.getAttribute("href")));
    }
  }, true);
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.method?.toLowerCase() !== "get") return;
    let input = form.querySelector('input[name="season"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = "season";
      form.append(input);
    }
    input.value = selectedSeason();
  }, true);
}

if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeSeasonNavigation);
  } else {
    initializeSeasonNavigation();
  }
}
