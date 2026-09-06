import Prose from "./Prose.jsx";

/**
 * QuietLine — "N others: nothing notable."
 *
 * §5.4 is explicit: this is set at full item size, not shrunk to a footnote.
 * It is a finding, not an apology — the product's argument is that silence is
 * information, and a first-class output has to look like one. So this renders
 * at the same serif size and measure as a BriefItem's prose, just without a
 * header row, a magnitude bar, or a freshness line, because there is no move
 * to report the freshness of.
 */
export default function QuietLine({ text }) {
  return (
    <div className="border-t border-hairline py-8">
      <Prose text={text} className="max-w-measure font-prose text-read text-chalk" />
    </div>
  );
}
