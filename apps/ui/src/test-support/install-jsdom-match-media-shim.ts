/**
 * Test-only helper: jsdom has no window.matchMedia, which framer-motion's
 * useReducedMotion needs. Installs a minimal, non-matching implementation.
 * Kept in src/test-support so every screen test shares one shim instead of
 * copy-pasting it (the vitest config is outside this package's ownership).
 */
export function installJsdomMatchMediaShim(): void {
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia;
}
