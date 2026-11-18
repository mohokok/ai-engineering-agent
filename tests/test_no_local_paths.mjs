import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getTrackedTextFiles } from "./helpers.mjs";

test("no committed text file leaks local user home paths (Rule 12a)", () => {
  const files = getTrackedTextFiles();
  assert.ok(files.length > 0, "Expected at least one tracked text file");

  const localUserPathRegex = new RegExp(
    "(?:C:[\\\\/]Users[\\\\/]|/Users/|/home/)(?!<user>)[A-Za-z0-9_.-]+",
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
