#!/usr/bin/env node
// Changed-file coverage gate. Fails if any line that this branch added/changed
// in a source file is an executable statement that vitest recorded as uncovered.
// Mirrors the python leaf's diff-cover gate (gates changed lines, not a global %).
//
// Inputs:
//   - Istanbul-format coverage at coverage/coverage-final.json
//     (vitest: reporters include "json"; @vitest/coverage-v8).
//   - BASE_REF env (e.g. "main"); compares against origin/$BASE_REF, falling
//     back to the repo root commit on a first push (diff then empty → passes).
// BASE_REF arrives via env from the workflow — never inline a CI expression here.

import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";

const COVERAGE_FILE = "coverage/coverage-final.json";
const SRC_PREFIX = "src/";

function git(args) {
  return execFileSync("git", args, { encoding: "utf8" });
}

function resolveBase() {
  const ref = process.env.BASE_REF || "main";
  const candidate = `origin/${ref}`;
  try {
    git(["rev-parse", "--verify", candidate]);
    return candidate;
  } catch {
    // No base branch yet (first push) → root commit; on the bootstrap commit
    // that equals HEAD, so the diff is empty and the gate passes. If there are
    // no commits at all, there is nothing to gate.
    try {
      return git(["rev-list", "--max-parents=0", "HEAD"]).trim().split("\n").pop();
    } catch {
      return null;
    }
  }
}

// Parse `git diff` unified hunks into a map of file → Set(changed line numbers
// on the NEW side). Handles renames/deletes: only added/context-new lines count.
function changedLines(base) {
  const diff = git(["diff", "--unified=0", "--diff-filter=ACMR", base, "--", SRC_PREFIX]);
  const byFile = new Map();
  let current = null;
  let newLine = 0;
  for (const line of diff.split("\n")) {
    if (line.startsWith("+++ ")) {
      const path = line.slice(4).replace(/^b\//, "");
      current = path === "/dev/null" ? null : path;
      if (current && !byFile.has(current)) byFile.set(current, new Set());
      continue;
    }
    const hunk = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/);
    if (hunk) {
      newLine = Number(hunk[1]);
      continue;
    }
    if (!current) continue;
    if (line.startsWith("+") && !line.startsWith("+++")) {
      byFile.get(current).add(newLine);
      newLine += 1;
    }
  }
  return byFile;
}

function loadCoverage() {
  if (!existsSync(COVERAGE_FILE)) {
    console.error(`coverage gate: ${COVERAGE_FILE} not found — did 'vitest run --coverage' run?`);
    process.exit(1);
  }
  return JSON.parse(readFileSync(COVERAGE_FILE, "utf8"));
}

// Build file → { line → covered? } from istanbul statementMap + s counts.
function lineCoverage(fileCov) {
  const lines = new Map();
  const map = fileCov.statementMap || {};
  const hits = fileCov.s || {};
  for (const [id, loc] of Object.entries(map)) {
    const count = hits[id] || 0;
    for (let l = loc.start.line; l <= loc.end.line; l += 1) {
      // A line is covered if ANY statement on it ran.
      lines.set(l, (lines.get(l) || false) || count > 0);
    }
  }
  return lines;
}

const base = resolveBase();
if (!base) {
  console.log("coverage gate: no commits to compare against — pass");
  process.exit(0);
}
const changed = changedLines(base);
if (changed.size === 0) {
  console.log("coverage gate: no changed source files — pass");
  process.exit(0);
}

const coverage = loadCoverage();
// Index coverage by repo-relative path (istanbul keys are absolute).
const covByRel = new Map();
for (const [absPath, data] of Object.entries(coverage)) {
  covByRel.set(relative(process.cwd(), resolve(absPath)), lineCoverage(data));
}

const failures = [];
for (const [file, lines] of changed) {
  if (!file.endsWith(".ts") || file.endsWith(".d.ts")) continue;
  const cov = covByRel.get(file);
  const uncovered = [];
  for (const line of [...lines].sort((a, b) => a - b)) {
    // Only executable statements appear in the map; non-code changed lines
    // (blank, comment, type-only) simply have no entry and are skipped.
    if (cov && cov.has(line) && cov.get(line) === false) uncovered.push(line);
  }
  if (uncovered.length) failures.push(`${file}: lines ${uncovered.join(", ")}`);
}

if (failures.length) {
  console.error("coverage gate: changed lines not covered by tests:");
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log("coverage gate: all changed source lines covered — pass");
