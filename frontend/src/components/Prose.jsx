/**
 * Prose — serif copy with its numerals in JetBrains Mono.
 *
 * §2.2 is unqualified: "every numeral in the application is JetBrains Mono."
 * The Brief's copy is generated server-side as plain sentences — "Down 7.2%
 * across the three sessions since you last looked." — so a digit run inside
 * that sentence needs to be lifted into mono without the frontend re-writing
 * the sentence or guessing what the field means (R3). Splitting out digit runs
 * is typographic, not semantic: it never changes what the string says, only how
 * the numerals in it are set.
 *
 * A digit run also captures a trailing `%` and an internal `.` or `:` or `,`,
 * so "7.2%", "15:29" and "1,240" stay one glyph run rather than fragmenting at
 * the decimal point.
 */

const NUMERAL_RUN = /\d[\d:.,]*%?/g;

/**
 * @param {{text: string, as?: keyof JSX.IntrinsicElements, className?: string}} props
 */
export default function Prose({ text, as: Tag = "p", className = "" }) {
  const parts = [];
  let last = 0;
  let match;
  NUMERAL_RUN.lastIndex = 0;
  while ((match = NUMERAL_RUN.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index));
    parts.push(
      <span key={match.index} className="num">
        {match[0]}
      </span>,
    );
    last = match.index + match[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));

  return <Tag className={className}>{parts}</Tag>;
}
