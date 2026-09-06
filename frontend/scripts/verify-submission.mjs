#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SRC = join(ROOT, "src");
const DIST = join(ROOT, "dist");
const NPM = process.platform === "win32" ? "npm.cmd" : "npm";

function walk(dir, files = []) {
  if (!existsSync(dir)) return files;
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, files);
    else files.push(path);
  }
  return files;
}

function fail(message) {
  throw new Error(message);
}

function stripComments(source) {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

function runNpm(args) {
  if (process.platform === "win32") {
    execFileSync(process.env.ComSpec, ["/d", "/c", NPM, ...args], { cwd: ROOT, stdio: "inherit" });
    return;
  }
  execFileSync(NPM, args, { cwd: ROOT, stdio: "inherit" });
}

console.log("1/5 Checking file extensions");
const forbidden = walk(fileURLToPath(new URL("../../", import.meta.url)))
  .filter((path) => !path.includes(`${join("node_modules", "")}`))
  .filter((path) => /\.(ts|tsx)$/.test(path) || path.endsWith("tsconfig.json"));
if (forbidden.length) fail(`Forbidden TypeScript files:\n${forbidden.join("\n")}`);

console.log("2/5 Running prohibition and copy checks");
execFileSync(process.execPath, ["scripts/check-prohibitions.mjs"], { cwd: ROOT, stdio: "inherit" });

console.log("3/5 Checking token purity");
const flareAllowed = new Set([
  "src/styles/tokens.css",
  "src/styles/base.css",
  "src/components/CursorSpine.jsx",
  "src/components/PriceChart.jsx",
  "src/pages/TokensPage.jsx",
  "scripts/check-prohibitions.mjs",
  "scripts/verify-submission.mjs",
]);
const flareFiles = walk(SRC).filter((path) => /\bflare\b/.test(stripComments(readFileSync(path, "utf8"))));
const unexpectedFlare = flareFiles
  .map((path) => relative(ROOT, path).replaceAll("\\", "/"))
  .filter((path) => !flareAllowed.has(path));
if (unexpectedFlare.length) fail(`Unexpected flare usage:\n${unexpectedFlare.join("\n")}`);

if (existsSync(DIST)) {
  const css = walk(DIST)
    .filter((path) => path.endsWith(".css"))
    .map((path) => readFileSync(path, "utf8"))
    .join("\n");
  if (/\b(?:text|bg|border)-(?:red|green|blue|gray|slate|amber)-\d{2,3}\b/.test(css)) {
    fail("Compiled CSS contains a standard Tailwind color class.");
  }
}

console.log("4/5 Running unit tests");
runNpm(["test"]);

console.log("5/5 Building and checking output");
runNpm(["run", "build"]);
const fonts = walk(DIST).filter((path) => path.endsWith(".woff2"));
if (fonts.length < 14) fail(`Expected the complete font set, found ${fonts.length} WOFF2 files.`);
const chunks = walk(join(DIST, "assets")).filter((path) => /\.(js|css)$/.test(path));
if (!chunks.length) fail("No production output chunks were emitted.");
console.log(`verify-submission: clean — ${fonts.length} font files, ${chunks.length} output chunks.`);
