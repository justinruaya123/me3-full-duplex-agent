import {randomUUID} from "node:crypto";
import {readFileSync, rmSync} from "node:fs";
import {join} from "node:path";
import {setTimeout as delay} from "node:timers/promises";
import {windowUpdate} from "./visual.mjs";

const title = "Publish to GitHub Pages?";
let waiting = false;

export async function confirmPublication(detail, {confirm, current, signal, timeout = 60000}) {
  if (!current() || signal.aborted) return false;
  const folder = process.env.ME3_WINDOW_DIR;
  if (!folder) return confirm(title, detail, {signal, timeout});
  if (waiting) throw Error("A publication approval is already pending.");

  const id = randomUUID();
  const response = join(folder, "publication-response.json");
  const deadline = performance.now() + timeout;
  waiting = true;
  try {
    rmSync(response, {force:true});
    windowUpdate("publication", {id,title,detail});
    while (current() && !signal.aborted && performance.now() < deadline) {
      try {
        const answer = JSON.parse(readFileSync(response, "utf8"));
        if (answer.id === id) return answer.approved === true;
      } catch (err) {
        if (err.code !== "ENOENT") throw err;
      }
      try {
        await delay(40, undefined, {signal});
      } catch (err) {
        if (signal.aborted) return false;
        throw err;
      }
    }
    return false;
  } finally {
    waiting = false;
    windowUpdate("publication", null);
    rmSync(response, {force:true});
  }
}
