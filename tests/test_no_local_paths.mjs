import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
  ".zip", ".gz", ".tar", ".7z", ".exe", ".dll", ".woff", ".woff2", ".ttf",
  ".dwg", ".rvt", ".rfa", ".rte", ".docx", ".xlsx", ".pptx", ".sqlite", ".db",
]);

function getTrackedTextFiles() {
  const out = execFileSync("git", ["ls-files", "-z"], { encoding: "utf8" });
  return out
    .split("\0")
    .filter(Boolean)
    .filter((filePath) => !BINARY_EXTENSIONS.has(path.extname(filePath).toLowerCase()));
}

test("no committed text file leaks local user home paths (Rule 12a)", () => {
  const files = getTrackedTextFiles();
  assert.ok(files.length > 0, "Expected at least one tracked text file");

  const localUserPathRegex = new RegExp(
    "(?:C:" + "\\\\" + "Users" + "\\\\|/Users/|/home/)(?!<user>)[A-Za-z0-9_.-]+",
    "i"
  );
  const hits = [];

  for (const filePath of files) {
    const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
    lines.forEach((line, index) => {
      if (localUserPathRegex.test(line)) {
        hits.push(`${filePath}:${index + 1}: contains local user path`);
      }
    });
  }

  assert.deepEqual(hits, [], `Personal path leak(s) found:\n${hits.join("\n")}`);
});
