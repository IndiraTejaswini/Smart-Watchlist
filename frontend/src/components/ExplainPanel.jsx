import { useEffect, useRef } from "react";
import { useExplain } from "../lib/api/queries.js";
import { formatExplainValue } from "../lib/explainFormat.js";

/**
 * ExplainPanel — FRONTEND_SPEC §5.4, ARCHITECTURE §16.2. The N1 endpoint,
 * rendered.
 *
 * "This panel is what you open live when the jury asks why an item ranks
 * second." That sentence sets the bar: every intermediate value, every branch
 * of the classification, every weight and multiplier, presented as a plain
 * definition list in mono so it can be read and checked, not just glanced at.
 *
 * It is a slide-over rather than a route, because it is an annotation on the
 * item that was clicked — leaving that item visible behind it, dimmed, is what
 * makes "why does *this one* rank second" legible while the panel is open.
 */

/**
 * @param {object} props
 * @param {{signal_event_id:string, symbol:string} | null} props.item null closes the panel
 * @param {() => void} props.onClose
 */
export default function ExplainPanel({ item, onClose }) {
  const panelRef = useRef(null);
  const { data, isPending, isError, error } = useExplain(item?.signal_event_id);

  useEffect(() => {
    if (!item) return undefined;
    const previouslyFocused = document.activeElement;
    panelRef.current?.focus();

    function onKeyDown(event) {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab") return;
      const focusable = panelRef.current?.querySelectorAll(
        'button, a[href], input, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    };
  }, [item, onClose]);

  if (!item) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-abyss/70"
      />
      <aside
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="explain-panel-heading"
        className="relative flex h-full w-full max-w-[480px] flex-col overflow-y-auto border-l border-hairline bg-panel"
      >
        <header className="flex items-center justify-between border-b border-hairline px-6 py-4">
          <div>
            <p className="text-micro text-slate">Why this ranks where it does</p>
            <h2 id="explain-panel-heading" className="num text-section text-chalk">
              {item.symbol}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-edge px-2 py-1 text-ui text-slate hover:text-chalk"
          >
            Close
          </button>
        </header>

        <div className="flex-1 px-6 py-6">
          {isPending ? <PanelSkeleton /> : null}
          {isError ? (
            <p className="text-dense text-stale">
              Could not load the explanation. {error?.detail ?? error?.message}
            </p>
          ) : null}
          {data ? <ExplainBody data={data} /> : null}
        </div>
      </aside>
    </div>
  );
}

function ExplainBody({ data }) {
  return (
    <div className="space-y-8">
      <DecisionPath steps={data.decision_path} />

      {data.sections.map((section) => (
        <section key={section.title}>
          <h3 className="text-ui text-chalk">{section.title}</h3>
          {section.note ? (
            <p className="mt-1 text-micro text-slate">{section.note}</p>
          ) : null}
          <dl className="mt-3 divide-y divide-hairline border-y border-hairline">
            {section.rows.map((row) => (
              <div
                key={row.label}
                className="flex items-baseline justify-between gap-4 py-2"
              >
                <div className="min-w-0">
                  <dt className="text-dense text-slate">{row.label}</dt>
                  {row.note ? (
                    <dd className="num mt-0.5 text-micro text-stale">{row.note}</dd>
                  ) : null}
                </div>
                <dd className="num shrink-0 text-dense text-chalk">
                  {formatExplainValue(row.value, row.format)}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}

      <section>
        <h3 className="text-ui text-chalk">Provenance</h3>
        <dl className="mt-3 divide-y divide-hairline border-y border-hairline">
          <div className="flex items-baseline justify-between gap-4 py-2">
            <dt className="text-dense text-slate">Completeness</dt>
            <dd className="num text-right text-dense text-chalk">
              {data.completeness.join(", ")}
            </dd>
          </div>
          <div className="flex items-baseline justify-between gap-4 py-2">
            <dt className="text-dense text-slate">Inputs hash</dt>
            <dd className="num text-dense text-chalk">{data.inputs_hash}</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

/**
 * §11: one classification per candidate, first match wins. Every rule this
 * candidate was tested against, in order, with the one that fired called out —
 * which answers "why not market-wide" as directly as it answers "why this".
 */
function DecisionPath({ steps }) {
  return (
    <section>
      <h3 className="text-ui text-chalk">Classification path</h3>
      <p className="mt-1 text-micro text-slate">
        One classification per candidate. First match wins.
      </p>
      <ol className="mt-3 space-y-3">
        {steps.map((step) => (
          <li
            key={step.step}
            className={`border-l-2 py-1 pl-3 ${
              step.taken ? "border-chalk" : "border-hairline"
            }`}
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className={`text-dense ${step.taken ? "text-chalk" : "text-slate"}`}>
                <span className="num">{step.step}</span> {step.rule}
              </span>
              {step.taken ? (
                <span className="text-micro text-slate">this branch</span>
              ) : null}
            </div>
            <p className="mt-1 text-micro text-slate">{step.test}</p>
            <p className="num mt-0.5 text-micro text-stale">{step.evaluated}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function PanelSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-4 animate-none bg-panel-hi" style={{ width: `${70 - i * 6}%` }} />
      ))}
    </div>
  );
}
