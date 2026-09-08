import { useCallback, useEffect } from "react";
import { useParams } from "react-router-dom";
import CursorSpine from "../CursorSpine.jsx";
import { useMe, useSignalMarks, useTradingCalendar } from "../../lib/api/queries.js";
import { useCursorStore, useDisplayCursor } from "../../store/useCursorStore.js";

/**
 * SpineRegion — connects the cursor spine to data and to the cursor store.
 *
 * Kept separate from CursorSpine so the spine itself stays a pure function of
 * its props: given sessions, marks and a cursor it draws, and it can be
 * rendered in isolation without a query client. Everything that knows about
 * fetching, routing and shared state lives here.
 *
 * On /symbol/:symbol the spine narrows to that symbol's signals (§3), which is
 * why the route parameter is read here rather than threaded down from a page.
 */
export default function SpineRegion() {
  const { symbol } = useParams();
  const { data: me } = useMe();
  const { data: calendar } = useTradingCalendar();

  const watchlistId = me?.default_watchlist_id;
  const { data: signals } = useSignalMarks(watchlistId, { symbol });

  const hydrate = useCursorStore((s) => s.hydrate);
  const preview = useCursorStore((s) => s.preview);
  const commit = useCursorStore((s) => s.commit);
  const cursorIso = useDisplayCursor();
  const acknowledged = me?.cursor?.acknowledged_through ?? null;
  const asOf = me?.as_of ?? null;

  useEffect(() => {
    if (asOf) hydrate(asOf);
  }, [asOf, hydrate]);

  // A session date is what the spine yields. It is widened to an instant at the
  // IST end of that day, so that "the cursor is on 20 August" means "everything
  // through the 20 August session has been seen" — the same reading the
  // server's acknowledged_through carries.
  const onPreview = useCallback((date) => preview(endOfDayIso(date)), [preview]);
  const onCommit = useCallback((date) => commit(endOfDayIso(date)), [commit]);

  return (
    <CursorSpine
      sessions={calendar?.sessions ?? []}
      window={calendar?.window ?? null}
      marks={signals?.marks ?? []}
      cursorIso={cursorIso}
      acknowledgedIso={acknowledged}
      onPreview={onPreview}
      onCommit={onCommit}
    />
  );
}

/**
 * The end of a trading date in IST.
 *
 * Deliberately 23:59:59 and not the session close: §21's SESSION_CLOSE is the
 * default for a REGULAR day, but a MUHURAT session's hours are notified by
 * circular and the backend stores them as NULL rather than inventing them (R1).
 * The end of the calendar day is true for every session type and asserts no
 * exchange timing the client does not have.
 */
function endOfDayIso(date) {
  return `${date}T23:59:59+05:30`;
}
