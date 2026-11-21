import {spawn} from "node:child_process";
import {createInterface} from "node:readline";
import {join} from "node:path";
import {randomUUID} from "node:crypto";

// The bridge inherits only the worker's inference configuration and host basics.
export function workerEnv(env, project) {
  const keys = ["PATH", "HOME", "LANG", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "ME3_LIVE_BENCHMARK", "ME3_WORKER_MODEL", "ME3_WORKER_PROVIDER", "ME3_WORKER_THINKING", "ME3_WEBSITE_THINKING", "ME3_VOICE_PROMPT_DIR"];
  const key = env.ME3_WORKER_API_KEY_ENV;
  if (key) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key) || !env[key])
      throw Error("The selected worker API key is missing.");
    keys.push(key);
  }
  return {...Object.fromEntries(keys.filter(k => env[k]).map(k => [k, env[k]])),
    ME3_NODE:process.execPath, ME3_PROJECT_AUTH_DIR:join(project, ".local/pi")};
}

export class JobBridge {
  constructor(python, cwd, session, env, notify, replayDir) {
    const args = ["-m","me3.voicechat_jobs",session];
    if (replayDir) args.push("--replay-drafts", replayDir);
    const child = spawn(python, args, {cwd, env, stdio:"pipe"});
    this.child = child;
    this.pending = new Map();
    child.stderr.resume();
    this.closed = new Promise(resolve => child.once("close", resolve));
    const fail = () => {
      for (const {reject} of this.pending.values()) reject(Error("ME3 job supervisor disconnected"));
      this.pending.clear();
    };
    child.on("error", fail);
    child.stdin.on("error", fail);
    child.on("close", fail);
    createInterface({input:child.stdout}).on("line", line => {
      let record;
      try { record = JSON.parse(line); } catch { child.kill(); return; }
      if (record.event) {notify(record.event); return;}
      const waiting = this.pending.get(record.id);
      if (!waiting) return;
      this.pending.delete(record.id);
      if (record.error) waiting.reject(Error(record.error));
      else waiting.resolve(record.result);
    });
  }
  call(op, fields) {
    if (!this.child.stdin.writable) return Promise.reject(Error("ME3 job supervisor is offline"));
    const id = randomUUID();
    return new Promise((resolve,reject) => {
      this.pending.set(id,{resolve,reject});
      this.child.stdin.write(JSON.stringify({id,op,...fields})+"\n");
    });
  }
  async close() {
    this.child.stdin.end();
    await this.closed;
  }
}
