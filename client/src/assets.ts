import { state } from "./state";

/** URL for a generated asset (/gen/…) or media file (/media/…).
 *  Caddy caches those paths for a day, so the server's asset_version (hash of the atlases + theme) is appended:
 *  a rebuild changes the URL and every browser fetches the new file at once instead of drawing a stale atlas. */
export function assetUrl(path: string): string {
  const v = state.catalog?.assetVersion;
  return v ? `${path}${path.includes("?") ? "&" : "?"}v=${v}` : path;
}

/** Re-point the theme stylesheet (linked statically in index.html) at the versioned URL once the catalog is known. */
export function refreshThemeLink(): void {
  const link = document.querySelector<HTMLLinkElement>('link[href^="/media/theme.css"]');
  if (!link) return;
  const href = assetUrl("/media/theme.css");
  if (link.getAttribute("href") !== href) link.href = href;
}
