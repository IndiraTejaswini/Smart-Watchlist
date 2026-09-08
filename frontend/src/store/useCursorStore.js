import { create } from "zustand";

/**
 * useCursorStore — where the reading cursor lives while the user is moving it.
 *
 * The acknowledged cursor is server state and arrives from /api/me. The cursor
 * the user is currently dragging is not: it changes many times a second, it is
 * shared by the spine and by every screen that queries against it, and it must
 * not be written back to the server on every frame. That combination is exactly
 * what Zustand is here for.
 *
 * `pendingIso` is the position the user has dragged to but not yet committed.
 * `cursorIso` is what screens query against. They differ only during a drag,
 * which is what lets the Brief hold still until the handle is released instead
 * of restacking on every pixel.
 */
export const useCursorStore = create((set, get) => ({
  /** The committed cursor — what screens query against. */
  cursorIso: null,
  /** Mid-drag position, or null when not dragging. */
  pendingIso: null,
  /** True once the server's acknowledged cursor has been loaded. */
  hydrated: false,

  /**
   * Seed the query cursor once /api/me resolves, from `me.as_of` — the end
   * of the last session this dataset actually has bars for. Does not
   * overwrite a cursor the user has already moved.
   *
   * Deliberately not the caller's acknowledged-through argument and not the
   * browser's clock:
   *  - The Brief's query window is (acknowledged_through, cursorIso], so
   *    hydrating the query cursor to the same instant the server already
   *    treats as the lower bound always yields an empty window on first
   *    paint, no matter how far back acknowledged_through is.
   *    `acknowledgedIso` (read separately from /api/me by the spine, not
   *    from this store) still carries that value for the "last read" marker.
   *  - This is a pre-seeded, frozen dataset viewed at an arbitrary real-world
   *    time (that is the whole point of pre-seeding it), so the browser's
   *    `new Date()` drifts further past the data's last real session every
   *    day after deployment and eventually walks past the loaded trading
   *    calendar entirely. `me.as_of` is stable regardless of when the URL is
   *    opened.
   */
  hydrate(asOfIso) {
    // A falsy anchor must not latch `hydrated`, or a single early call with
    // nothing useful in it would block every later one and leave the cursor
    // null for the rest of the session.
    if (get().hydrated || !asOfIso) return;
    set({ cursorIso: asOfIso, hydrated: true });
  },

  /** Called continuously during a drag. Cheap, and does not refetch anything. */
  preview(iso) {
    set({ pendingIso: iso });
  },

  /** Called on release, on a keyboard change, and on any programmatic move. */
  commit(iso) {
    set({ cursorIso: iso, pendingIso: null });
  },

  cancelPreview() {
    set({ pendingIso: null });
  },
}));

/** The position to draw the handle at: the drag if there is one, else the cursor. */
export function useDisplayCursor() {
  return useCursorStore((s) => s.pendingIso ?? s.cursorIso);
}
