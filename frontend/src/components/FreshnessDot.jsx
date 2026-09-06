/**
 * FreshnessDot — the confidence marker, §2.1 and §7.
 *
 * §7 requires that colour is never the only signal, so the dot never travels
 * alone: either it is followed by a visible label, or — in a dense table column
 * where a per-row label is not workable — it carries a visually hidden one and
 * a tooltip. A sighted user reads the column header and the status strip; a
 * screen reader gets the word.
 */

const TONE_CLASS = {
  final: "bg-final",
  provis: "bg-provis",
  stale: "bg-stale",
};

const TONE_WORD = {
  final: "Final",
  provis: "Provisional",
  stale: "Stale",
};

/**
 * @param {object} props
 * @param {"final"|"provis"|"stale"} props.tone
 * @param {React.ReactNode} [props.label] visible text after the dot
 * @param {string} [props.srLabel] override for the hidden label when no visible one
 * @param {boolean} [props.block] lay out as its own line rather than inline
 * @param {string} [props.className]
 */
export default function FreshnessDot({
  tone,
  label,
  srLabel,
  block = false,
  className = "",
}) {
  const word = srLabel ?? TONE_WORD[tone] ?? "Unknown";
  return (
    <span
      className={`${block ? "flex" : "inline-flex"} items-center gap-2 ${className}`.trim()}
    >
      <span
        aria-hidden="true"
        title={word}
        className={`inline-block size-[7px] shrink-0 rounded-full ${
          TONE_CLASS[tone] ?? "bg-stale"
        }`}
      />
      {label ? (
        <span className="text-slate">{label}</span>
      ) : (
        <span className="sr-only">{word}</span>
      )}
    </span>
  );
}
