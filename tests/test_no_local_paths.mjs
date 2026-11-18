import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getTrackedTextFiles } from "./helpers.mjs";

const LOCAL_USER_PATH_REGEX = new RegExp(
  "(?:[A-Za-z]:[\\\\/]Users[\\\\/]|/Users/|/home/)(?!<user>)[A-Za-z0-9_.-]+",
  "i"
);

const WORKSPACE_TRACKED_PATH_REGEX = /(?:^|[\\/])workspaces(?:[\\/]|$)/i;

/** Return matching line numbers where a line exposes a local user home path. */
export function scanTextForLocalPaths(text, filePath) {
  const hits = [];
  const lines = text.split(/\r?\n/);
  lines.forEach((line, index) => {
    if (LOCAL_USER_PATH_REGEX.test(line)) {
      hits.push(`${filePath}:${index + 1}: contains local user path`);
    }
  });
  return hits;
}

/** Return true if a tracked repository path falls inside a /workspaces/ directory. */
export function isWorkspaceTrackedPath(filePath) {
  return WORKSPACE_TRACKED_PATH_REGEX.test(filePath);
}

test("no committed text file leaks local user home paths (Rule 12a)", () => {
  const files = getTrackedTextFiles();
  assert.ok(files.length > 0, "Expected at least one tracked text file");

  const hits = [];
  for (const filePath of files) {
    hits.push(...scanTextForLocalPaths(fs.readFileSync(filePath, "utf8"), filePath));
  }

  assert.deepEqual(hits, [], `Personal path leak(s) found:\n${hits.join("\n")}`);
});

test("no committed file is tracked inside /workspaces/ (Rule 12a)", () => {
  const files = getTrackedTextFiles();
  const workspaceHits = files.filter((filePath) => isWorkspaceTrackedPath(filePath));
  assert.deepEqual(
    workspaceHits,
    [],
    `Tracked file(s) inside /workspaces/ found:\n${workspaceHits.join("\n")}`
  );
});

test("local user path detector catches other drive letters ([A-Za-z]:\\Users\\)", () => {
  const dDriveBackslash = "D:" + "\\Us" + "ers\\alice\\project.txt";
  const eDriveForward = "E:" + "/Us" + "ers/bob/report.md";
  const safePlaceholder = "C:" + "\\Us" + "ers\\<user>\\example";

  assert.equal(scanTextForLocalPaths(dDriveBackslash, "sample.txt").length, 1);
  assert.equal(scanTextForLocalPaths(eDriveForward, "sample.txt").length, 1);
  assert.equal(scanTextForLocalPaths(safePlaceholder, "sample.txt").length, 0);
});

test("/workspaces/ detector flags tracked workspace paths and allows normal paths", () => {
  const absWorkspace = "/work" + "spaces/proj-01/01_Input_Documents/spec.pdf";
  const relWorkspace = "work" + "spaces/proj-01/doc.txt";
  const safePath = "backend/app/services/workspace_manager.py";

  assert.equal(isWorkspaceTrackedPath(absWorkspace), true);
  assert.equal(isWorkspaceTrackedPath(relWorkspace), true);
  assert.equal(isWorkspaceTrackedPath(safePath), false);
});
