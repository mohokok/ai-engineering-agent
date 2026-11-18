import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { getTrackedTextFiles } from "./helpers.mjs";

test("all committed text files are valid UTF-8 without BOM", () => {
  const files = getTrackedTextFiles();
  assert.ok(files.length > 0, "Expected at least one tracked text file");

  const decoder = new TextDecoder("utf-8", { fatal: true });
  const failures = [];

  for (const filePath of files) {
    const buf = fs.readFileSync(filePath);
    if (buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
      failures.push(`${filePath}: has UTF-8 BOM`);
      continue;
    }
    if (
      buf.length >= 2 &&
      ((buf[0] === 0xff && buf[1] === 0xfe) || (buf[0] === 0xfe && buf[1] === 0xff))
    ) {
      failures.push(`${filePath}: has UTF-16 BOM`);
      continue;
    }
    try {
      decoder.decode(buf);
    } catch (err) {
      failures.push(`${filePath}: invalid UTF-8 (${err.message})`);
    }
  }

  assert.deepEqual(failures, [], `Encoding failures:\n${failures.join("\n")}`);
});

test("Arabic sample file is tracked and decodes as valid UTF-8 with Arabic script", () => {
  const samplePath = "docs/arabic-utf8-sample.md";
  const tracked = getTrackedTextFiles();
  assert.ok(tracked.includes(samplePath), `${samplePath} must be committed/tracked in git`);

  const content = new TextDecoder("utf-8", { fatal: true }).decode(fs.readFileSync(samplePath));
  assert.match(content, /[\u0600-\u06FF]/, "Expected Arabic Unicode characters in sample file");
});
