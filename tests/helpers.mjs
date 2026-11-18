import { execFileSync } from "node:child_process";
import path from "node:path";

const BINARY_EXTENSIONS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf",
  ".zip", ".gz", ".tar", ".7z", ".exe", ".dll", ".woff", ".woff2", ".ttf",
  ".dwg", ".rvt", ".rfa", ".rte", ".docx", ".xlsx", ".pptx", ".sqlite", ".db",
]);

/** Return all git-tracked file paths from full `git ls-files -z`, including binaries. */
export function getAllTrackedFiles() {
  const out = execFileSync("git", ["ls-files", "-z"], { encoding: "utf8" });
  return out.split("\0").filter(Boolean);
}

/** Return git-tracked file paths excluding known binary extensions. */
export function getTrackedTextFiles() {
  return getAllTrackedFiles().filter(
    (filePath) => !BINARY_EXTENSIONS.has(path.extname(filePath).toLowerCase())
  );
}
