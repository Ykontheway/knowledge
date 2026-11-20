import assert from "node:assert/strict";
import { lstat, readFile, readdir } from "node:fs/promises";
import { resolve, relative, sep } from "node:path";

const root = resolve("dist-preview");
const sourceReplay = resolve("public/replay.json");
const required = new Set(["index.html", "replay.json", "favicon.svg"]);
const found = [];

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    const info = await lstat(path);
    assert(!info.isSymbolicLink(), "preview_symlink_rejected");
    const name = relative(root, path).split(sep).join("/");
    assert(!name.startsWith("../"), "preview_path_rejected");
    if (entry.isDirectory()) {
      assert(name === "assets", "preview_directory_rejected");
      await walk(path);
      continue;
    }
    assert(entry.isFile(), "preview_special_file_rejected");
    assert(required.has(name) || /^assets\/[\w.-]+\.(?:js|css|woff2?)$/.test(name), "preview_unexpected_file");
    found.push(name);
    if (/\.(?:js|css|html|json)$/.test(name)) {
      const text = await readFile(path, "utf8");
      assert(!/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{20,}|postgres(?:ql)?(?:\+\w+)?:\/\/[^\s"']+:[^\s"']+@|\/workspace\/|\/Users\//.test(text), "preview_sensitive_content_rejected");
    }
  }
}

await walk(root);
for (const name of required) assert(found.includes(name), "preview_required_file_missing");
assert(found.some((name) => /^assets\/.*\.js$/.test(name)), "preview_script_missing");
assert((await readFile(resolve(root, "replay.json"))).equals(await readFile(sourceReplay)), "preview_replay_asset_drift");
const html = await readFile(resolve(root, "index.html"), "utf8");
for (const match of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
  const url = match[1];
  if (url.startsWith("#")) continue;
  assert(url.startsWith("./"), "preview_asset_not_relative");
  assert(found.includes(url.slice(2)), "preview_asset_missing");
}
const bundle = JSON.parse(await readFile(resolve(root, "replay.json"), "utf8"));
assert.equal(bundle.schema_version, 1);
assert.equal(bundle.mode, "replay");
assert.equal(bundle.resources.jobs.length, 3);
const statuses = ["reference_job_id", "candidate_job_id", "recovery_job_id"].map((role) => bundle.resources.jobs.find((job) => job.id === bundle.story[role])?.status);
assert.deepEqual(statuses, ["passed", "failed", "passed"]);
console.log(JSON.stringify({ passed: true, entry: "#replay/guide", files: found.length, jobs: 3, bytes: (await readFile(resolve(root, "replay.json"))).length }));
