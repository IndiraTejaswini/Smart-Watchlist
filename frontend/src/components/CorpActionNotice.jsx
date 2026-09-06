import Prose from "./Prose.jsx";

/**
 * CorpActionNotice — the suppression explainer, §11.1.
 *
 * "This is the demo's money shot: the naive view screams −50%, ours explains."
 * A corporate action is never scored and never competes for a ranked slot
 * (MULT_CORP_ACTION = 0.00) — it is unranked and informational, which is why it
 * sits after the quiet line rather than among the items. The symbol is set the
 * same way a BriefItem's is, so the notice still reads as being about a named
 * stock and not as boilerplate.
 */
export default function CorpActionNotice({ notice }) {
  return (
    <div className="border-t border-hairline py-8">
      <h3 className="num text-ui text-chalk">{notice.symbol}</h3>
      <Prose
        text={
          notice.text ??
          `${notice.action_type} action, ex-date ${notice.ex_date}. Price adjusted without changing your holding value.`
        }
        className="mt-3 max-w-measure font-prose text-read text-chalk"
      />
    </div>
  );
}
