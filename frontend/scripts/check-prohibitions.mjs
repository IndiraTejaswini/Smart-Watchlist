#!/usr/bin/env node
/**
 * check-prohibitions.mjs — the build-failing lint.
 *
 * BUILD_PLAN.md R12 requires a build-time check for banned copy. The brief
 * additionally fixes a set of hard prohibitions — no TypeScript, no component
 * kit, no icon library, amber in exactly three places, no box shadows. All of
 * them are checked here, because a rule that is only written down is a rule
 * that survives until the first deadline.
 *
 * Run: npm run check:prohibitions
 * Exit code 1 on any violation, with file and line for every hit.
 */

import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SRC = join(ROOT, "src");

/** @type {{file:string,line:number,rule:string,detail:string}[]} */
const violations = [];

function fail(file, line, rule, detail) {
  violations.push({ file: relative(ROOT, file).split(sep).join("/"), line, rule, detail });
}

// ─── File walking ───────────────────────────────────────────────────────────

const IGNORED_DIRS = new Set(["node_modules", "dist", ".git", "coverage"]);

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (IGNORED_DIRS.has(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const allFiles = walk(SRC);
const codeFiles = allFiles.filter((f) => [".js", ".jsx"].includes(extname(f)));
const cssFiles = allFiles.filter((f) => extname(f) === ".css");

function lineOf(text, index) {
  return text.slice(0, index).split("\n").length;
}

// ─── 1. No TypeScript ───────────────────────────────────────────────────────

for (const file of allFiles) {
  if ([".ts", ".tsx"].includes(extname(file))) {
    fail(file, 1, "no-typescript", "TypeScript file. The stack is JavaScript only.");
  }
}
for (const name of ["tsconfig.json", "tsconfig.app.json", "tsconfig.node.json"]) {
  if (existsSync(join(ROOT, name))) {
    fail(join(ROOT, name), 1, "no-typescript", "TypeScript config present.");
  }
}

// ─── 2. Banned dependencies ─────────────────────────────────────────────────

const BANNED_DEPS = [
  [/^next$/, "no-nextjs", "Next.js. Plain React 18 SPA on Vite."],
  [/^(react-native|expo|@capacitor\/)/, "no-native", "Mobile app scaffolding. Web only."],
  [/^(i18next|react-i18next|@lingui\/|react-intl|vue-i18n)/, "no-i18n", "i18n library. English literals only."],
  [/^(@mui\/|@chakra-ui\/|antd|@ant-design\/|@radix-ui\/|shadcn|@headlessui\/|react-bootstrap)/, "no-component-kit", "Component library. Hand-build against the tokens."],
  [/^(lucide-react|react-icons|@heroicons\/|@phosphor-icons\/|feather-icons|@tabler\/icons)/, "no-icon-library", "Icon library."],
  [/^vite-plugin-pwa$/, "no-pwa", "PWA tooling. Web only, no manifest."],
];

const pkg = JSON.parse(readFileSync(join(ROOT, "package.json"), "utf8"));
const declared = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
for (const dep of declared) {
  for (const [pattern, rule, detail] of BANNED_DEPS) {
    if (pattern.test(dep)) fail(join(ROOT, "package.json"), 1, rule, `${dep} — ${detail}`);
  }
}
if (existsSync(join(ROOT, "public", "manifest.json"))) {
  fail(join(ROOT, "public/manifest.json"), 1, "no-pwa", "PWA manifest.");
}

// ─── 3. Banned copy · R12 ───────────────────────────────────────────────────
//
// Matched on word boundaries so legitimate market vocabulary survives: BUYBACK
// is a corporate action, "Sensex" is an index. Only user-facing text is
// scanned — string literals and JSX text nodes — because comments and this
// project's own documentation must be able to name the words they forbid.

const BANNED_WORDS = [
  "buy", "sell", "should", "consider", "opportunity", "target price",
  "undervalued", "overvalued", "bullish", "bearish", "act now",
  "don't miss", "hurry",
];

/** Files permitted to contain the banned words, with the reason. */
const COPY_ALLOWLIST = new Map([
  ["src/lib/constants.js", "declares BANNED_COPY, the list itself"],
]);

/**
 * Test files are exempt from the copy rule. R12 governs *user-facing* text, and
 * an assertion message ("26 June should not be a session") is read by a
 * developer running the suite and never rendered. Exempting them by pattern
 * rather than by name also means a future test that deliberately asserts the
 * banned list works does not have to be allowlisted by hand.
 */
const isTestFile = (rel) => /\.test\.jsx?$/.test(rel);

function stripComments(source) {
  // Replace comment bodies with equal-length whitespace so line numbers hold.
  return source
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(^|[^:])\/\/[^\n]*/g, (m, p1) => p1 + m.slice(p1.length).replace(/./g, " "));
}

/** Extract user-facing text: string literals and JSX text nodes. */
function userFacingText(source) {
  const found = [];
  const code = stripComments(source);

  const stringLiteral = /(['"`])((?:\\.|(?!\1)[^\\])*)\1/g;
  let m;
  while ((m = stringLiteral.exec(code)) !== null) {
    found.push({ text: m[2], index: m.index });
  }

  // JSX text between a closing > and an opening <, containing a letter.
  //
  // JavaScript operators live in the same character space, so the pattern has
  // to refuse them or every `a >= b` and `(x) => y` in the file reads as prose:
  // the lookbehind rejects `=>`, `>>` and friends, `(?!=)` rejects `>=`, and
  // the excluded characters keep the body from spanning an expression.
  const jsxText = /(?<![=!<>&|-])>(?!=)([^<>{}=;&|]*[A-Za-z][^<>{}=;&|]*)</g;
  while ((m = jsxText.exec(code)) !== null) {
    found.push({ text: m[1], index: m.index });
  }
  return found;
}

for (const file of codeFiles) {
  const rel = relative(ROOT, file).split(sep).join("/");
  if (COPY_ALLOWLIST.has(rel) || isTestFile(rel)) continue;
  const source = readFileSync(file, "utf8");
  for (const { text, index } of userFacingText(source)) {
    for (const word of BANNED_WORDS) {
      const re = new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i");
      if (re.test(text)) {
        fail(file, lineOf(source, index), "banned-copy", `"${word}" in: ${text.trim().slice(0, 70)}`);
      }
    }
    if (text.includes("!")) {
      fail(file, lineOf(source, index), "banned-copy", `exclamation mark in: ${text.trim().slice(0, 70)}`);
    }
  }
}

// ─── 4. Amber in exactly three places ───────────────────────────────────────

const FLARE_ALLOWLIST = new Map([
  ["src/styles/tokens.css", "defines the token"],
  ["src/styles/base.css", "the focus ring — sanctioned use 2"],
  ["src/components/CursorSpine.jsx", "the cursor spine — sanctioned use 1"],
  ["src/components/PriceChart.jsx", "the chart cursor marker — sanctioned use 3"],
  ["src/pages/TokensPage.jsx", "the design-system reference page documents the token"],
  ["scripts/check-prohibitions.mjs", "this check"],
]);

for (const file of [...codeFiles, ...cssFiles]) {
  const rel = relative(ROOT, file).split(sep).join("/");
  if (FLARE_ALLOWLIST.has(rel)) continue;
  const source = readFileSync(file, "utf8");
  // Comments are stripped first: a comment explaining why this element is
  // deliberately NOT amber is the correct thing to write, and must not trip the
  // rule it is documenting.
  const scanned = stripComments(source);
  const re = /\bflare\b/g;
  let m;
  while ((m = re.exec(scanned)) !== null) {
    fail(
      file,
      lineOf(source, m.index),
      "flare-misuse",
      "Amber marks a position in time: the cursor spine, the focus ring, a chart marker. Nowhere else.",
    );
  }
}

// ─── 5. No box shadows ──────────────────────────────────────────────────────

const SHADOW_ALLOWLIST = new Set([
  "src/styles/tokens.css", // wipes the shadow namespaces
  "src/pages/TokensPage.jsx", // the reference page names the utility it forbids
  "scripts/check-prohibitions.mjs",
]);

for (const file of [...codeFiles, ...cssFiles]) {
  const rel = relative(ROOT, file).split(sep).join("/");
  if (SHADOW_ALLOWLIST.has(rel)) continue;
  const source = readFileSync(file, "utf8");
  const scanned = stripComments(source);
  const re = /box-shadow\s*:|\bshadow-(?:sm|md|lg|xl|2xl|inner|\[)/g;
  let m;
  while ((m = re.exec(scanned)) !== null) {
    fail(file, lineOf(source, m.index), "no-shadow", "Separation is the hairline and the value step.");
  }
}

// ─── 6. No i18n wrappers in source ──────────────────────────────────────────

for (const file of codeFiles) {
  const source = stripComments(readFileSync(file, "utf8"));
  const re = /\buseTranslation\b|\bi18n\b|\bt\(['"`]/g;
  let m;
  while ((m = re.exec(source)) !== null) {
    fail(file, lineOf(source, m.index), "no-i18n", "English string literals only.");
  }
}

// ─── Report ─────────────────────────────────────────────────────────────────

const RULES_CHECKED = [
  "no-typescript", "no-nextjs", "no-native", "no-i18n", "no-component-kit",
  "no-icon-library", "no-pwa", "banned-copy", "flare-misuse", "no-shadow",
];

if (violations.length === 0) {
  console.log(`check-prohibitions: clean — ${RULES_CHECKED.length} rules, ${allFiles.length} files.`);
  process.exit(0);
}

const byRule = new Map();
for (const v of violations) {
  if (!byRule.has(v.rule)) byRule.set(v.rule, []);
  byRule.get(v.rule).push(v);
}

console.error(`check-prohibitions: ${violations.length} violation(s).\n`);
for (const [rule, hits] of byRule) {
  console.error(`  ${rule}`);
  for (const h of hits) console.error(`    ${h.file}:${h.line}  ${h.detail}`);
  console.error("");
}
process.exit(1);
