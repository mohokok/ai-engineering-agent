import { execFileSync } from "node:child_process";
import path from "node:path";

const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
  ".zip", ".gz", ".tar", ".7z", ".exe", ".dll", ".woff", ".woff2", ".ttf",
  ".dwg", ".rvt", ".rfa", ".rte", ".docx", ".xlsx", ".pptx", ".sqlite", ".db",
]);

/** Return git-tracked file paths excluding known binary extensions. */
export function getTrackedTextFiles() {
  const out = execFileSync("git", ["ls-files", "-z"], { encoding: "utf8" });
  return out
    .split("\0")
    .filter(Boolean)
    .filter((filePath) => !BINARY_EXTENSIONS.has(path.extname(filePath).toLowerCase()));
}
