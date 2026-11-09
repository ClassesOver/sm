// ── Sidebar (thumbnails / outline) width: drag the divider to resize; persisted ──
export const SIDEBAR_W_KEY = 'genoffice-pdf-sidebar-width'
export const SIDEBAR_W_DEFAULT = 150
export const SIDEBAR_W_MIN = 120
/** pane padding (10px × 2) + thumb box borders (2px × 2) */
export const SIDEBAR_CHROME = 24

export const clampSidebarW = (w: number): number =>
  Math.min(Math.max(w, SIDEBAR_W_MIN), Math.min(320, Math.round(window.innerWidth * 0.4)))

export const loadSidebarW = (): number => {
  const saved = Number(localStorage.getItem(SIDEBAR_W_KEY))
  return Number.isFinite(saved) && saved > 0 ? clampSidebarW(saved) : SIDEBAR_W_DEFAULT
}
