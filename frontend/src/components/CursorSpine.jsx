import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  buildAxis,
  fractionOfDate,
  indexForInstant,
  nearestIndex,
  sessionsElapsed,
} from "../lib/spineAxis.js";
import { formatDayMonth, formatDayMonthTime, istDateIso } from "../lib/format.js";
import { RESTACK_MS } from "../lib/constants.js";

/**
 * CursorSpine — FRONTEND_SPEC §3. The signature element.
 *
 * A reading cursor for markets, made physical. The product's argument is that
 * "since you last looked" is a better frame than "since the close", and this is
 * that argument you can grab with a mouse: drag the handle back and the whole
 * application re-answers for the period you chose.
 *
 * Three things it does that a slider normally does not:
 *
 *   Real spacing. Ticks sit at their true calendar position, so weekends and
 *   exchange holidays leave genuine gaps. The market's rhythm is visible in the
 *   geometry rather than described in a caption.
 *
 *   Session-unit movement. The handle snaps to sessions, because a session is
 *   the unit the product reasons in. Position is calendar time; value is a
 *   session count. See lib/spineAxis.js.
 *
 *   Honest labelling. Until the user moves it, the label shows the exact
 *   acknowledged instant the server holds. Once moved, it shows a date — the
 *   client has not chosen an hour and will not imply one.
 *
 * Accessibility: the handle is a real <input type="range">, so arrow keys move
 * one session, Home goes to the start of retention and End to now, and the
 * whole thing is announced as a slider with a readable value. Pointer events
 * are handled separately because a native range maps the pointer linearly onto
 * value, which on a calendar axis would drop the handle somewhere the user did
 * not aim.
 */

const NOW_LABEL_CLEARANCE_PX = 44;

/**
 * @param {object} props
 * @param {{date:string, session_type:string}[]} props.sessions
 * @param {{from:string, to:string}} props.window
 * @param {{signal_event_id:string, session_date:string, symbol:string, surfaced:boolean}[]} [props.marks]
 * @param {string|null} props.cursorIso committed cursor, an ISO instant
 * @param {string|null} [props.acknowledgedIso] the server's cursor, for label honesty
 * @param {(sessionDate: string) => void} props.onPreview
 * @param {(sessionDate: string) => void} props.onCommit
 */
export default function CursorSpine({
  sessions,
  window: axisWindow,
  marks = [],
  cursorIso,
  acknowledgedIso,
  onPreview,
  onCommit,
}) {
  const trackRef = useRef(null);
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);
  const [hovered, setHovered] = useState(null);
  const trackWidth = useElementWidth(trackRef);

  const axis = useMemo(
    () => buildAxis(sessions, axisWindow),
    [sessions, axisWindow],
  );

  const index = useMemo(
    // With no cursor yet, rest the handle on the newest session rather than
    // index 0. Index 0 is the oldest session on the axis, which reads as "you
    // last looked ~a year ago" — a confident, wrong claim — where the newest
    // is the same place the cursor hydrates to a moment later.
    () => {
      if (!axis) return 0;
      const newest = axis.points.length - 1;
      if (!cursorIso) return newest;
      return indexForInstant(cursorIso, axis);
    },
    [axis, cursorIso],
  );

  const marksBySession = useMemo(() => groupMarks(marks), [marks]);

  const setFromPointer = useCallback(
    (clientX, commit) => {
      const track = trackRef.current;
      if (!track || !axis) return;
      const rect = track.getBoundingClientRect();
      if (rect.width === 0) return;
      const fraction = (clientX - rect.left) / rect.width;
      const next = axis.points[nearestIndex(fraction, axis)];
      if (!next) return;
      (commit ? onCommit : onPreview)(next.date);
    },
    [axis, onCommit, onPreview],
  );

  if (!axis) return <SpineFrame>{null}</SpineFrame>;

  const point = axis.points[index] ?? axis.points[0];
  const cursorFraction = point.fraction;
  const elapsed = sessionsElapsed(index, axis);
  const lastIndex = axis.points.length - 1;

  // The label tells the truth about what it knows: the acknowledged instant
  // while the cursor is still where the server put it, a bare date once moved.
  const atAcknowledged =
    acknowledgedIso && istDateIso(acknowledgedIso) === point.date;
  const cursorLabel = atAcknowledged
    ? formatDayMonthTime(acknowledgedIso)
    : formatDayMonth(point.date);

  const showNow = trackWidth
    ? cursorFraction * trackWidth < trackWidth - NOW_LABEL_CLEARANCE_PX
    : true;

  return (
    <SpineFrame>
      <div
        ref={trackRef}
        className="relative h-full w-full touch-none select-none"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId);
          setDragging(true);
          inputRef.current?.focus();
          setFromPointer(event.clientX, false);
        }}
        onPointerMove={(event) => {
          if (dragging) setFromPointer(event.clientX, false);
        }}
        onPointerUp={(event) => {
          if (!dragging) return;
          setDragging(false);
          setFromPointer(event.clientX, true);
        }}
        onPointerCancel={() => setDragging(false)}
      >
        {/* The real control. Invisible, never receives the pointer, but fully
            focusable — so arrow keys, Home and End behave natively and screen
            readers announce a slider with a readable value. */}
        <input
          ref={inputRef}
          type="range"
          min={0}
          max={lastIndex}
          step={1}
          value={index}
          onChange={(event) => {
            const next = axis.points[Number(event.target.value)];
            if (next) onCommit(next.date);
          }}
          aria-label="Reading cursor. Move to change the period the brief covers."
          aria-valuetext={valueText(point.date, elapsed)}
          className="pointer-events-none absolute inset-x-0 top-3 h-4 w-full cursor-grab opacity-0"
        />

        {/* ── Labels ──────────────────────────────────────────────────────── */}
        <div className="pointer-events-none absolute inset-x-0 top-[3px] h-3">
          <span
            className="num absolute whitespace-nowrap text-micro text-chalk"
            style={clampedLabel(cursorFraction, trackWidth)}
          >
            {cursorLabel}
          </span>
          {showNow ? (
            <span className="absolute right-0 text-micro text-slate">now</span>
          ) : null}
        </div>

        {/* ── The rail ────────────────────────────────────────────────────── */}
        {/* Full span at low intensity is the retention window; the bright
            segment from the handle to now is the period the brief covers, which
            makes "since you last looked" a length you can see. */}
        <div className="pointer-events-none absolute inset-x-0 top-[22px] h-0.5 bg-flare/25" />
        <div
          className="pointer-events-none absolute top-[22px] h-0.5 bg-flare"
          style={{
            left: `${cursorFraction * 100}%`,
            right: 0,
            transition: dragging ? "none" : `left ${RESTACK_MS}ms var(--ease-cursor)`,
          }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute right-0 top-[19px] size-0 border-y-4 border-l-[6px] border-y-transparent border-l-flare"
        />

        {/* ── Session ticks ───────────────────────────────────────────────── */}
        <div className="pointer-events-none absolute inset-x-0 top-[27px] h-[5px]">
          {axis.points.map((session) => (
            <span
              key={session.date}
              className="absolute top-0 h-[5px] w-px bg-stale"
              style={{ left: `${session.fraction * 100}%` }}
            />
          ))}
        </div>

        {/* ── Signal marks ────────────────────────────────────────────────── */}
        {/* Announced as one summary rather than as twenty-eight unlabelled
            glyphs. The marks are an overview; the signals themselves are read
            on the brief, where each one has prose, provenance and an
            explanation. */}
        <span className="sr-only">{marksSummary(marks)}</span>
        <div className="absolute inset-x-0 top-[34px] h-[7px]">
          {[...marksBySession.entries()].map(([date, group]) => (
            <SignalMark
              key={date}
              group={group}
              fraction={fractionOfDate(date, axis)}
              hovered={hovered?.date === date}
              onHover={setHovered}
            />
          ))}
        </div>

        {/* ── The handle ──────────────────────────────────────────────────── */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-[17px] size-[11px] -translate-x-1/2 rounded-full border-2 border-abyss bg-flare"
          style={{
            left: `${cursorFraction * 100}%`,
            transition: dragging ? "none" : `left ${RESTACK_MS}ms var(--ease-cursor)`,
          }}
        />

        {/* ── The sentence ────────────────────────────────────────────────── */}
        <div className="pointer-events-none absolute inset-x-0 top-[41px] text-micro">
          <span className="text-slate">
            {hovered ? (
              <>
                <span className="num text-chalk">{formatDayMonth(hovered.date)}</span>{" "}
                <span className="num text-chalk">
                  {hovered.group.map((m) => m.symbol).join(", ")}
                </span>{" "}
                {hovered.group.some((m) => m.surfaced)
                  ? "— surfaced in a brief"
                  : "— scored, not surfaced"}
              </>
            ) : (
              <ElapsedSentence elapsed={elapsed} />
            )}
          </span>
        </div>
      </div>
    </SpineFrame>
  );
}

/**
 * The band itself. `focus-within` puts the ring around the whole spine when the
 * hidden range has focus — §7 requires a visible focus indicator, and the
 * control it belongs to is the spine, not a 1px input nobody can see.
 */
function SpineFrame({ children }) {
  return (
    <div className="h-spine shrink-0 border-b border-hairline bg-abyss px-5 focus-within:outline-2 focus-within:-outline-offset-2 focus-within:outline-flare">
      {children}
    </div>
  );
}

function ElapsedSentence({ elapsed }) {
  if (elapsed === 0) {
    return <>Nothing has closed since you last looked.</>;
  }
  return (
    <>
      <span className="num text-chalk">{elapsed}</span>{" "}
      {elapsed === 1 ? "session" : "sessions"} since you last looked
    </>
  );
}

/**
 * One glyph per session that carries signals: a filled triangle if any of them
 * reached a brief, a dot if they were only scored. §3.
 *
 * Grouped by session because two names can fire on the same day — 4 September
 * carries both TATAMOTORS and BHARTIARTL — and two glyphs at the same x would
 * simply overprint. Hovering names them.
 */
function SignalMark({ group, fraction, hovered, onHover }) {
  const surfaced = group.some((mark) => mark.surfaced);
  const date = group[0].session_date;
  return (
    <span
      aria-hidden="true"
      className="absolute top-0 flex h-[7px] w-3 -translate-x-1/2 cursor-default items-start justify-center"
      style={{ left: `${fraction * 100}%` }}
      onPointerEnter={() => onHover({ date, group })}
      onPointerLeave={() => onHover(null)}
    >
      {surfaced ? (
        <span
          className={`size-0 border-x-[3px] border-b-[6px] border-x-transparent ${
            hovered ? "border-b-chalk" : "border-b-chalk/80"
          }`}
        />
      ) : (
        <span
          className={`mt-1 size-[3px] rounded-full ${
            hovered ? "bg-chalk" : "bg-slate"
          }`}
        />
      )}
    </span>
  );
}

// ─── helpers ────────────────────────────────────────────────────────────────

function marksSummary(marks) {
  if (!marks.length) return "No signals in this period.";
  const surfaced = marks.filter((mark) => mark.surfaced).length;
  const noun = marks.length === 1 ? "signal" : "signals";
  return `${marks.length} ${noun} scored in this period, ${surfaced} surfaced in a brief.`;
}

function groupMarks(marks) {
  const grouped = new Map();
  for (const mark of marks) {
    const list = grouped.get(mark.session_date);
    if (list) list.push(mark);
    else grouped.set(mark.session_date, [mark]);
  }
  return grouped;
}

function valueText(date, elapsed) {
  const when = formatDayMonth(date);
  if (elapsed === 0) return `${when}, the most recent session`;
  return `${when}, ${elapsed} ${elapsed === 1 ? "session" : "sessions"} before now`;
}

/**
 * Keep the cursor label inside the track. It follows the handle, because a date
 * pinned to the far left while the handle sits three-quarters along reads as
 * two unrelated things rather than as one cursor.
 */
function clampedLabel(fraction, trackWidth) {
  if (!trackWidth) return { left: `${fraction * 100}%`, transform: "translateX(-50%)" };
  const estimatedWidth = 84;
  const centre = fraction * trackWidth;
  const left = Math.min(
    Math.max(centre - estimatedWidth / 2, 0),
    Math.max(trackWidth - estimatedWidth, 0),
  );
  return { left: `${left}px` };
}

/** Track width, for label clamping. */
function useElementWidth(ref) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    setWidth(element.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return width;
}
