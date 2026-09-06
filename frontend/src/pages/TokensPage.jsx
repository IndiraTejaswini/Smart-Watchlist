import { useEffect, useState } from "react";
import Num from "../components/Num.jsx";
import FreshnessDot from "../components/FreshnessDot.jsx";
import SessionBadge from "../components/SessionBadge.jsx";
import { Register } from "../lib/register.jsx";
import {
  FRESHNESS_DISPLAY,
  FRESHNESS_STATES,
  MPM_TIER_THRESHOLDS,
} from "../lib/constants.js";

/**
 * /tokens — the design system, rendered.
 *
 * This page exists so that a token can be checked rather than remembered. It
 * reads every colour back out of the live theme with getComputedStyle instead
 * of restating the hex codes, so the swatches cannot drift away from
 * tokens.css: if the theme changes, this page changes with it, and if it ever
 * disagrees with FRONTEND_SPEC §2 that is a real failure and not a stale
 * comment.
 */

const STRUCTURE = [
  ["abyss", "Page ground. Blue-black, never neutral black."],
  ["panel", "Raised surfaces, table row bands, chart plot area."],
  ["panel-hi", "Hover, selected row, active tab."],
  ["hairline", "Every divider and border in the app."],
  ["chalk", "Primary text."],
  ["slate", "Secondary text, metadata, axis labels."],
];

const CONFIDENCE = [
  ["final", "Exchange-final data."],
  ["provis", "Provisional. It will be restated."],
  ["stale", "Stale, absent, or below the liquidity floor."],
];

const DIRECTION = [
  ["up", "Price direction, up. Terminal surfaces only."],
  ["down", "Price direction, down. Terminal surfaces only."],
];

const TYPE_ROLES = [
  ["micro", "12px", "Axis labels, dense table metadata"],
  ["dense", "13px", "Table body, form labels"],
  ["ui", "14px", "UI default, nav, buttons"],
  ["prose-sm", "16px", "Secondary prose"],
  ["read", "20px", "Brief item prose — the reading size"],
  ["section", "28px", "Section headings, cursor sentence"],
  ["hero", "48px", "Landing hero"],
];

export default function TokensPage() {
  return (
    <div className="mx-auto max-w-[1100px] px-8 py-10">
      <PageHead />
      <ColourSection />
      <AmberRule />
      <TypeSection />
      <NumeralSection />
      <RegisterSection />
      <ShapeSection />
      <ComponentSection />
      <FreshnessSection />
    </div>
  );
}

function PageHead() {
  return (
    <div className="mb-12">
      <h1 className="text-section text-chalk">Design tokens</h1>
      <p className="mt-3 max-w-measure text-ui text-slate">
        Six structural values, five semantic, one accent. Three type families,
        seven roles. One radius. No shadows. Everything the interface is allowed
        to say, and nothing else.
      </p>
    </div>
  );
}

// ─── Colour ─────────────────────────────────────────────────────────────────

function useResolvedColour(name) {
  const [value, setValue] = useState("");
  useEffect(() => {
    const resolved = getComputedStyle(document.documentElement)
      .getPropertyValue(`--color-${name}`)
      .trim();
    setValue(resolved.toUpperCase());
  }, [name]);
  return value;
}

function Swatch({ name, role }) {
  const hex = useResolvedColour(name);
  return (
    <div className="flex items-start gap-4 border-b border-hairline py-3">
      <span
        className="mt-0.5 size-10 shrink-0 rounded-edge border border-hairline"
        style={{ backgroundColor: `var(--color-${name})` }}
      />
      <div className="min-w-0">
        <div className="flex items-baseline gap-3">
          <span className="num text-dense text-chalk">--{name}</span>
          <span className="num text-micro text-slate">{hex}</span>
        </div>
        <p className="mt-1 text-dense text-slate">{role}</p>
      </div>
    </div>
  );
}

function ColourSection() {
  return (
    <Section title="Colour" note="FRONTEND_SPEC §2.1">
      <div className="grid gap-x-12 md:grid-cols-2">
        <div>
          <GroupLabel>Structure</GroupLabel>
          {STRUCTURE.map(([name, role]) => (
            <Swatch key={name} name={name} role={role} />
          ))}
        </div>
        <div>
          <GroupLabel>Data confidence</GroupLabel>
          {CONFIDENCE.map(([name, role]) => (
            <Swatch key={name} name={name} role={role} />
          ))}
          <GroupLabel className="mt-8">Price direction</GroupLabel>
          {DIRECTION.map(([name, role]) => (
            <Swatch key={name} name={name} role={role} />
          ))}
          <GroupLabel className="mt-8">The accent</GroupLabel>
          <Swatch
            name="flare"
            role="The cursor. A position in time, and nothing else."
          />
        </div>
      </div>
    </Section>
  );
}

function AmberRule() {
  return (
    <div className="my-10 border-y border-hairline bg-panel px-6 py-5">
      <p className="max-w-measure text-prose-sm text-chalk">
        Amber appears in exactly three places in this application.
      </p>
      <ol className="mt-3 space-y-1.5 text-dense text-slate">
        <li>
          <span className="num text-chalk">1</span> The cursor spine rail and
          handle.
        </li>
        <li>
          <span className="num text-chalk">2</span> The keyboard focus ring —
          tab through this page to see it.
        </li>
        <li>
          <span className="num text-chalk">3</span> The cursor marker on a
          chart.
        </li>
      </ol>
      <p className="mt-4 max-w-measure text-dense text-slate">
        Not a button, not a badge, not a link, not the logo. The constraint is
        what makes it readable: the moment amber appears somewhere decorative,
        the one signal a user has learned to look for stops meaning anything.
      </p>
    </div>
  );
}

// ─── Type ───────────────────────────────────────────────────────────────────

function TypeSection() {
  return (
    <Section title="Type" note="FRONTEND_SPEC §2.2">
      <div className="grid gap-8 border-b border-hairline pb-8 md:grid-cols-3">
        <FamilyCard
          className="font-prose"
          family="Source Serif 4"
          token="--font-prose"
          role="Brief items, landing headline, long copy. Body sizes for actual sentences — never a decorative headline face on interior screens."
          sample="Its largest three-day stock-specific move in fourteen months."
        />
        <FamilyCard
          className="font-ui"
          family="Archivo"
          token="--font-ui"
          role="Nav, labels, buttons, table headers, forms. All interface chrome. Sentence case throughout — no all-caps labels anywhere."
          sample="Your list against the market"
        />
        <FamilyCard
          className="font-num"
          family="JetBrains Mono"
          token="--font-num"
          role="Every numeral in the application. Prices, percentages, z-scores, dates, times, tickers, clause references."
          sample="2,481.50  −7.2%  15:29"
        />
      </div>

      <GroupLabel className="mt-8">Scale</GroupLabel>
      {TYPE_ROLES.map(([token, px, role]) => (
        <div
          key={token}
          className="flex items-baseline gap-6 border-b border-hairline py-4"
        >
          <div className="w-44 shrink-0">
            <div className="num text-micro text-chalk">text-{token}</div>
            <div className="num text-micro text-slate">{px}</div>
          </div>
          <div className="min-w-0 flex-1">
            <div
              className={`truncate text-chalk ${
                token === "read" || token === "hero"
                  ? "font-prose"
                  : "font-ui"
              }`}
              style={{ fontSize: `var(--text-${token})` }}
            >
              Four things changed
            </div>
            <div className="mt-1 text-micro text-slate">{role}</div>
          </div>
        </div>
      ))}

      <div className="mt-8 border border-hairline p-6">
        <GroupLabel>Prose measure</GroupLabel>
        <p className="max-w-measure font-prose text-read text-chalk">
          Every watchlist shows you what changed since the market closed. This
          one shows you what changed since you last looked, and stays quiet the
          rest of the time.
        </p>
        <p className="mt-3 text-micro text-slate">
          Source Serif 4 at <span className="num">20px</span>, line-height{" "}
          <span className="num">1.65</span>, capped at{" "}
          <span className="num">62</span> characters. Serif on dark needs air.
        </p>
      </div>
    </Section>
  );
}

function FamilyCard({ className, family, token, role, sample }) {
  return (
    <div>
      <div className="flex items-baseline gap-3">
        <span className="text-ui text-chalk">{family}</span>
        <span className="num text-micro text-slate">{token}</span>
      </div>
      <p className={`mt-3 text-read text-chalk ${className}`}>{sample}</p>
      <p className="mt-3 text-micro text-slate">{role}</p>
    </div>
  );
}

// ─── Numerals ───────────────────────────────────────────────────────────────

const PRICE_ROWS = [
  ["RELIANCE", 2481.5, 0.5, 41200000, 0.61, "LIVE"],
  ["TCS", 3902.1, -1.24, 8800000, 0.44, "LIVE"],
  ["HDFCBANK", 1644.75, 2.08, 152000000, 0.58, "DELAYED"],
  ["TATAMOTORS", 918.4, -7.2, 1240000000, 0.72, "LIVE"],
  ["IDEA", 11.05, 0.0, 640000, 0.31, "STALE_THIN"],
];

function NumeralSection() {
  return (
    <Section title="Numerals" note="FRONTEND_SPEC §2.2">
      <p className="mb-6 max-w-measure text-dense text-slate">
        Every number in the application goes through one component. Tabular
        figures mean the decimal points below line up regardless of digit count,
        and a price that ticks from <span className="num">918.40</span> to{" "}
        <span className="num">1,918.40</span> does not shift the column. That is
        the entire reason the rule is non-negotiable.
      </p>

      <div className="border border-hairline">
        <div className="grid grid-cols-[1fr_7rem_6rem_8rem_5rem_6rem] items-center gap-4 border-b border-hairline bg-panel px-4 py-2 text-micro text-slate">
          <span>Symbol</span>
          <span className="text-right">Last</span>
          <span className="text-right">Change</span>
          <span className="text-right">Turnover</span>
          <span className="text-right">Delivery</span>
          <span className="text-right">State</span>
        </div>
        {PRICE_ROWS.map(([sym, ltp, chp, turnover, delivery, state]) => (
          <div
            key={sym}
            className="grid grid-cols-[1fr_7rem_6rem_8rem_5rem_6rem] items-center gap-4 border-b border-hairline px-4 py-2 text-dense last:border-b-0 hover:bg-panel-hi"
          >
            <span className="num text-chalk">{sym}</span>
            <Num
              value={ltp}
              kind="price"
              freshness={state}
              className="text-right"
            />
            <Num
              value={chp}
              kind="percent"
              dp={2}
              tone="direction"
              freshness={state}
              className="text-right"
            />
            <Num value={turnover} kind="turnover" className="text-right text-slate" />
            <Num value={delivery} kind="ratio" className="text-right text-slate" />
            <span className="flex justify-end">
              <FreshnessDot
                tone={FRESHNESS_DISPLAY[state].tone}
                srLabel={FRESHNESS_DISPLAY[state].label}
              />
            </span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-micro text-slate">
        Terminal register: direction carries green and red. The HDFCBANK row is
        delayed and the IDEA row has not traded recently — R5 means neither is
        allowed to look as confident as the rows around it.
      </p>
    </Section>
  );
}

// ─── Register ───────────────────────────────────────────────────────────────

function RegisterSection() {
  return (
    <Section title="Register" note="FRONTEND_SPEC §1.2">
      <p className="mb-6 max-w-measure text-dense text-slate">
        The same component, the same number, on the two kinds of surface. The
        Brief cannot render a directional colour: the constraint lives in a
        context that wraps the route, so it holds even if a call site asks for
        one.
      </p>
      <div className="grid gap-px border border-hairline bg-hairline md:grid-cols-2">
        <div className="bg-abyss p-6">
          <GroupLabel>Terminal</GroupLabel>
          <div className="flex items-baseline gap-6">
            <Num value={-7.2} kind="percent" dp={1} tone="direction" className="text-section" />
            <Num value={4.1} kind="percent" dp={1} tone="direction" className="text-section" />
          </div>
          <p className="mt-3 text-micro text-slate">
            Green and red carry price direction. Show the market as it is.
          </p>
        </div>
        <Register value="dispatch">
          <div className="bg-abyss p-6">
            <GroupLabel>Dispatch — the Brief</GroupLabel>
            <div className="flex items-baseline gap-6">
              <Num value={-7.2} kind="percent" dp={1} tone="direction" className="text-section" />
              <Num value={4.1} kind="percent" dp={1} tone="direction" className="text-section" />
            </div>
            <p className="mt-3 text-micro text-slate">
              Identical markup. Direction is carried by the signed number and by
              a bar extending left or right of a centre rule, never by hue.
            </p>
          </div>
        </Register>
      </div>
    </Section>
  );
}

// ─── Shape ──────────────────────────────────────────────────────────────────

function ShapeSection() {
  return (
    <Section title="Shape and elevation" note="FRONTEND_SPEC §2.3">
      <div className="grid gap-8 md:grid-cols-3">
        <div>
          <GroupLabel>Radius</GroupLabel>
          <div className="flex items-center gap-4">
            <span className="flex size-16 items-center justify-center rounded-edge border border-hairline bg-panel">
              <span className="num text-micro text-slate">3px</span>
            </span>
            <p className="text-micro text-slate">
              One radius, on inputs, buttons and chart panels. An instrument has
              machined edges, not pillows.
            </p>
          </div>
        </div>
        <div>
          <GroupLabel>Value step</GroupLabel>
          <div className="flex border border-hairline">
            <span className="flex h-16 flex-1 items-end bg-abyss p-2">
              <span className="num text-micro text-slate">abyss</span>
            </span>
            <span className="flex h-16 flex-1 items-end bg-panel p-2">
              <span className="num text-micro text-slate">panel</span>
            </span>
            <span className="flex h-16 flex-1 items-end bg-panel-hi p-2">
              <span className="num text-micro text-slate">panel-hi</span>
            </span>
          </div>
          <p className="mt-2 text-micro text-slate">
            Separation is the value step and the hairline. Nothing else.
          </p>
        </div>
        <div>
          <GroupLabel>Shadows</GroupLabel>
          <div className="flex h-16 items-center border border-dashed border-hairline px-4">
            <span className="text-micro text-slate">None. Zero. Removed from the theme.</span>
          </div>
          <p className="mt-2 text-micro text-slate">
            The shadow namespace is wiped in tokens.css, so `shadow-md` is not a
            utility that exists. Shadows on a near-black ground are invisible
            anyway, and reaching for them is the card reflex.
          </p>
        </div>
      </div>
    </Section>
  );
}

// ─── Components ─────────────────────────────────────────────────────────────

function ComponentSection() {
  return (
    <Section title="Component states" note="FRONTEND_SPEC §6, §7">
      <div className="grid gap-10 md:grid-cols-2">
        <div>
          <GroupLabel>Buttons</GroupLabel>
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" className="rounded-edge bg-chalk px-4 py-2 text-ui text-abyss">
              Open the demo account
            </button>
            <button type="button" className="rounded-edge border border-hairline px-4 py-2 text-ui text-chalk hover:bg-panel-hi">
              Sign in
            </button>
            <button type="button" className="rounded-edge px-2 py-1 text-ui text-slate underline decoration-hairline underline-offset-4 hover:text-chalk">
              why this?
            </button>
          </div>
          <p className="mt-3 text-micro text-slate">
            No amber. No arrow glyph inside button text. Tab to any of these for
            the focus ring.
          </p>

          <GroupLabel className="mt-8">Input</GroupLabel>
          <input
            type="text"
            placeholder="Search a symbol"
            className="w-full max-w-80 rounded-edge border border-hairline bg-panel px-3 py-2 text-ui text-chalk placeholder:text-stale"
          />
        </div>

        <div>
          <GroupLabel>Freshness dot</GroupLabel>
          <div className="space-y-2 text-dense">
            <FreshnessDot
              block
              tone="final"
              label={
                <>
                  As of <span className="num">15:29</span> on{" "}
                  <span className="num">4 Sep</span> · final
                </>
              }
            />
            <FreshnessDot
              block
              tone="provis"
              label="Provisional — will be restated after bhavcopy"
            />
            <FreshnessDot
              block
              tone="stale"
              label="No trade in the last five minutes"
            />
          </div>

          <GroupLabel className="mt-8">Session badge</GroupLabel>
          <div className="flex flex-wrap gap-2">
            {["PRE_OPEN", "REGULAR", "POST_CLOSE", "CLOSED", "HALTED"].map((s) => (
              <SessionBadge key={s} session={s} />
            ))}
          </div>

          <GroupLabel className="mt-8">Regulatory reference</GroupLabel>
          <table className="w-full border border-hairline text-dense">
            <thead>
              <tr className="bg-panel text-micro text-slate">
                <th className="px-3 py-2 text-left font-normal">Share price</th>
                <th className="px-3 py-2 text-right font-normal">Threshold</th>
              </tr>
            </thead>
            <tbody>
              {MPM_TIER_THRESHOLDS.map((tier, i) => (
                <tr key={tier.thresholdPct} className="border-t border-hairline">
                  <td className="px-3 py-2 text-slate">
                    {tier.priceUpTo === Infinity ? (
                      <>Above <Num value={MPM_TIER_THRESHOLDS[i - 1].priceUpTo} kind="price" dp={0} prefix="₹" /></>
                    ) : (
                      <>Up to <Num value={tier.priceUpTo} kind="price" dp={0} prefix="₹" /></>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Num value={tier.thresholdPct} kind="price" dp={1} suffix="%" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-micro text-slate">
            Material Price Movement framework, NSE/BSE, 21 May 2024, under SEBI
            LODR Reg 30(11). Rendered from the constants registry, never typed
            into a component.
          </p>
        </div>
      </div>
    </Section>
  );
}

// ─── Freshness ──────────────────────────────────────────────────────────────

function FreshnessSection() {
  return (
    <Section title="Freshness states" note="ARCHITECTURE §14.2">
      <p className="mb-6 max-w-measure text-dense text-slate">
        Nine states, and the plain-English sentence each one puts in the status
        strip. A stock sitting at its price band is not halted, and the copy for
        that state never says it is.
      </p>
      <table className="w-full border border-hairline text-dense">
        <thead>
          <tr className="bg-panel text-micro text-slate">
            <th className="px-4 py-2 text-left font-normal">State</th>
            <th className="px-4 py-2 text-left font-normal">Tone</th>
            <th className="px-4 py-2 text-left font-normal">What the strip says</th>
            <th className="px-4 py-2 text-right font-normal">Price shown as</th>
          </tr>
        </thead>
        <tbody>
          {FRESHNESS_STATES.map((state) => {
            const d = FRESHNESS_DISPLAY[state];
            return (
              <tr key={state} className="border-t border-hairline">
                <td className="px-4 py-2">
                  <span className="num text-chalk">{state}</span>
                </td>
                <td className="px-4 py-2">
                  <FreshnessDot tone={d.tone} label={d.tone} />
                </td>
                <td className="px-4 py-2 text-slate">{d.label}</td>
                <td className="px-4 py-2 text-right">
                  <Num value={2481.5} kind="price" freshness={state} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Section>
  );
}

// ─── Layout helpers ─────────────────────────────────────────────────────────

function Section({ title, note, children }) {
  return (
    <section className="mb-16">
      <div className="mb-6 flex items-baseline justify-between border-b border-hairline pb-2">
        <h2 className="text-ui text-chalk">{title}</h2>
        <span className="num text-micro text-slate">{note}</span>
      </div>
      {children}
    </section>
  );
}

function GroupLabel({ children, className = "" }) {
  return (
    <div className={`mb-3 text-micro text-slate ${className}`.trim()}>
      {children}
    </div>
  );
}
