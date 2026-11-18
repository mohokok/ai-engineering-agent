import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getAllTrackedFiles, getTrackedTextFiles } from "./helpers.mjs";

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

/** Filter a file path list for any path located under /workspaces/. */
export function findTrackedWorkspaceFiles(filePaths) {
  return filePaths.filter((filePath) => isWorkspaceTrackedPath(filePath));
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

test("no committed file (including binaries) is tracked inside /workspaces/ (Rule 12a)", () => {
  const allFiles = getAllTrackedFiles();
  assert.ok(allFiles.length > 0, "Expected at least one tracked file");
  const workspaceHits = findTrackedWorkspaceFiles(allFiles);
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

test("/workspaces/ detector flags tracked binary and text workspace paths", () => {
  const binaryWorkspace = "work" + "spaces/p/drawing.pdf";
  const absWorkspace = "/work" + "spaces/proj-01/01_Input_Documents/spec.pdf";
  const safePath = "backend/app/services/workspace_manager.py";

  assert.deepEqual(
    findTrackedWorkspaceFiles([safePath, binaryWorkspace, absWorkspace]),
    [binaryWorkspace, absWorkspace]
  );
});
