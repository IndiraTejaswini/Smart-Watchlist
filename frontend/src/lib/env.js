/**
 * env.js — the only place `import.meta.env` is read.
 *
 * `VITE_USE_MOCK` decides whether the API layer talks to the backend or to
 * src/lib/mock. It is a transport switch and nothing more: the mock answers the
 * same function with the same payload shapes from docs/BUILD_SPEC.md §16, so no
 * component ever knows which one it is talking to. If a component would need to
 * change to accommodate the mock, the mock is wrong.
 */

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === "true";

/** Base path for the real API. Vite proxies this to the backend in dev. */
export const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export const IS_DEV = import.meta.env.DEV;
