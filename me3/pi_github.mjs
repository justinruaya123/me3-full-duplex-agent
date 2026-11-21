// Interactive, host-owned GitHub actions. Workers never load this extension.
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, mkdtemp, open, rename, rm } from "node:fs/promises";
import path from "node:path";

const actions = ["clone", "pull", "commit", "push", "pages"];
const validBranch = (value) =>
  typeof value === "string" &&
  value.length <= 128 &&
  value
    .split("/")
    .every(
      (part) =>
        /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(part) &&
        !part.endsWith(".") &&
        !part.endsWith(".lock") &&
        !part.includes(".."),
    );
const validFile = (name) =>
  typeof name === "string" && name === name.trim() && /^[A-Za-z0-9][A-Za-z0-9 _.-]{0,127}$/.test(name);
const flags = [
  "core.hooksPath=/dev/null", "core.fsmonitor=false", "credential.helper=",
  "credential.https://github.com.helper=!gh auth git-credential",
  "http.followRedirects=false", "submodule.recurse=false", "commit.gpgSign=false",
].flatMap(setting => ["-c", setting]);

export function requestsGitHubAction(text, action) {
  if (
    !actions.includes(action) || typeof text !== "string" ||
    /\b(?:do not|don['’]t|never|without|explain|describe|hypothetically|instead of)\b/i.test(text)
  )
    return false;
  const request = text
    .trim()
    .replace(
      /^(?:(?:hey[, ]+)?(?:pi|me3)[, ]+)?(?:(?:can|could|would|will) you\s+|i(?:'d like| want) you to\s+)?(?:please\s+)?/i,
      "",
    );
  if (/^(?:how|what|why|when|if|should|tell me|show me|help me understand)\b/i.test(request))
    return false;
  const verbs = {
    clone: /^clone\b/i,
    pull: /^pull\b/i,
    commit: /^commit\b/i,
    push: /^push\b/i,
    pages: /^(?:publish|configure|enable|deploy|set up|turn on)\b.*\b(?:github\s+)?pages\b/i,
  };
  return request
    .split(/\s*(?:,\s*(?:and\s+)?|\band then\b|\band\b|\bthen\b)\s*/i)
    .some((part) =>
      verbs[action].test(part.replace(/^(?:please\s+)?(?:(?:use\s+)?github\s+to\s+|git\s+)?/i, "")),
    );
}

function validate(args) {
  const { action, repo, files, message, branch } = args;
  if (!actions.includes(action)) throw Error("Choose clone, pull, commit, push or pages.");
  if (
    typeof repo !== "string" ||
    !/^[a-z\d](?:[a-z\d-]{0,37}[a-z\d])?\/[a-z\d_-][a-z\d._-]{0,99}$/i.test(repo) ||
    repo.endsWith(".") ||
    repo.toLowerCase().endsWith(".git")
  )
    throw Error("Use a GitHub OWNER/REPO name.");
  const keys = ["repo", "action"];
  if (action === "commit") {
    keys.push("files", "message");
    if (
      !Array.isArray(files) ||
      !files.length ||
      files.length > 16 ||
      !files.every(validFile) ||
      new Set(files.map((f) => f.toLowerCase())).size !== files.length
    )
      throw Error("Select 1–16 distinct, visible session filenames.");
    if (
      typeof message !== "string" ||
      !message.trim() ||
      message.length > 200 ||
      /[\p{C}\p{Zl}\p{Zp}]/u.test(message)
    )
      throw Error("Use one printable commit message of up to 200 characters.");
  }
  if (action === "pages") {
    keys.push("path", "branch");
    if (!validBranch(branch) || !["/", "/docs"].includes(args.path))
      throw Error("Pages requires an explicit branch and / or /docs.");
  }
  if (Object.keys(args).some((key) => !keys.includes(key)))
    throw Error("Unexpected GitHub action parameter.");
}

export function runCommand(bin, args, { cwd, signal, input, env } = {}) {
  return new Promise((resolve, reject) => {
    const child = execFile(
      bin,
      args,
      { cwd, env, signal, timeout: 90000, maxBuffer: 65536 },
      (error, out, err) => {
        if (!error) return resolve(out.trimEnd());
        // Never forward raw process output, credential provider text or untrusted refs to Pi.
        const status = bin === "gh" && err.match(/\bHTTP (\d{3})\b/)?.[1];
        const reason = /non-fast-forward|fast-forward|fetch first/i.test(err)
          ? " The branches cannot fast-forward."
          : /identity unknown|email address/i.test(err)
            ? " Configure your Git user.name and user.email."
            : /authentication|credential|could not read Username|HTTP 40[13]/i.test(err)
              ? " Check GitHub CLI authentication and repository permissions."
              : "";
        reject(
          Object.assign(
            Error(`${bin} failed (${error.code || error.signal || "terminated"}).${reason}`),
            { code: error.code, httpStatus: Number(status) },
          ),
        );
      },
    );
    child.stdin.on("error", () => {}); // An early exit can close the pipe before input is consumed.
    child.stdin.end(input);
  });
}

async function directory(dir, create = false) {
  if (create)
    await mkdir(dir, { mode: 0o700 }).catch((e) => {
      if (e.code !== "EEXIST") throw e;
    });
  if (!(await lstat(dir)).isDirectory()) throw Error("Expected a private directory, without symlinks.");
}

async function sourceBytes(folder, name) {
  const handle = await open(
    path.join(folder, name),
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
  );
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > 16384)
      throw Error("Choose a regular session file of at most 16 KiB.");
    const buffer = Buffer.alloc(16385);
    const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
    if (bytesRead !== stat.size || bytesRead > 16384) throw Error("Session file changed during read.");
    const bytes = buffer.subarray(0, bytesRead);
    if (bytes.includes(0)) throw Error("Session files must contain UTF-8 text.");
    new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    return bytes;
  } finally {
    await handle.close();
  }
}

// Explicit arguments and fixed executables. Only the authenticated host can provide these dependencies.
export function githubActions({ getFolder, getTurn, run = runCommand }) {
  const busy = new Set();
  return async function execute(args, ctx, signal, voiceTurn) {
    validate(args);
    const { action, files = [], message } = args,
      repo = args.repo.toLowerCase();
    const folder = getFolder(),
      turn = voiceTurn ?? getTurn();
    if (!folder || !path.isAbsolute(folder) || !turn?.id || !turn?.text)
      throw Error("A current operator request and bound chat folder are required.");
    if (!requestsGitHubAction(turn.text, action))
      throw Error("The operator must explicitly request GitHub " + action + ".");
    if (!ctx?.hasUI || typeof ctx.ui?.confirm !== "function")
      throw Error("An interactive Pi confirmation is required.");
    if (busy.has(folder)) throw Error("A GitHub action is already pending in this chat.");
    const controller = new AbortController();
    if (voiceTurn && typeof voiceTurn.isCurrent !== "function")
      throw Error("A verified voice turn is required.");
    const current = () =>
      getFolder() === folder && (voiceTurn !== undefined || getTurn()?.id === turn.id);
    function check() {
      if (!current()) throw Error("The chat or operator turn changed. Request this action again.");
      if (signal?.aborted || controller.signal.aborted) throw Error("GitHub action cancelled.");
    }
    async function checkAuthority() {
      check();
      if (turn.isCurrent && (await turn.isCurrent()) !== true) {
        throw Error("The verified operator turn changed. Request this action again.");
      }
      check();
    }
    check();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    const timer = setInterval(() => {
      if (!current()) cancel();
    }, 100);
    busy.add(folder);
    const [owner, name] = repo.split("/");
    const base = path.join(folder, ".github-repos"),
      namespace = path.join(base, owner),
      checkout = path.join(namespace, name);
    const url = "https://github.com/" + repo + ".git";
    // Keep operator identity/credentials, isolate Git from global URL rewrites, filters and repository overrides.
    const env = {};
    for (const key of [
      "HOME",
      "PATH",
      "TMPDIR",
      "XDG_CONFIG_HOME",
      "GH_CONFIG_DIR",
      "GH_TOKEN",
      "GITHUB_TOKEN",
      "GIT_AUTHOR_NAME",
      "GIT_AUTHOR_EMAIL",
      "GIT_COMMITTER_NAME",
      "GIT_COMMITTER_EMAIL",
    ]) {
      if (process.env[key] !== undefined) env[key] = process.env[key];
    }
    Object.assign(env, {
      GIT_CONFIG_GLOBAL: "/dev/null",
      GIT_CONFIG_NOSYSTEM: "1",
      GIT_ALLOW_PROTOCOL: "https",
      GIT_TERMINAL_PROMPT: "0",
      GH_PROMPT_DISABLED: "1",
      GH_HOST: "github.com",
      LC_ALL: "C",
    });
    function command(bin, argv, options = {}) {
      check();
      return run(bin, argv, { cwd: checkout, env, signal: controller.signal, ...options });
    }
    const git = (argv, options) => command("git", [...flags, ...argv], options);
    async function head() {
      try {
        return await git(["rev-parse", "--verify", "--quiet", "HEAD"]);
      } catch (e) {
        if (e.code === 1) return "";
        throw e;
      }
    }
    try {
      await directory(folder);
      let branch, revision;
      if (action !== "clone" && action !== "pages") {
        try {
          for (const dir of [base, namespace, checkout, path.join(checkout, ".git")]) await directory(dir);
        } catch (error) {
          if (error.code === "ENOENT") throw Error("Clone " + repo + " into this chat first.");
          throw error;
        }
        branch = await git(["symbolic-ref", "--quiet", "--short", "HEAD"]);
        if (!validBranch(branch)) throw Error("Use a named branch with a supported branch name.");
        revision = await head();
      }
      const sources = [];
      for (const name of files) sources.push({ name, bytes: await sourceBytes(folder, name) });
      const tip = revision || "(empty branch)";
      const manifest = sources.map(({name,bytes}) => {
        const digest = createHash("sha256").update(bytes).digest("hex").slice(0, 12);
        return `${name} · ${bytes.length} bytes · SHA-256 ${digest}`;
      }).join("\n");
      const descriptions = {
        clone: `Download the default branch of ${url} into this chat's .github-repos/${repo} checkout.`,
        pull: `Fast-forward this chat's ${repo} branch ${branch} at ${tip} to the latest GitHub branch of the same name.`,
        push: `Send commit ${tip} from this chat to https://github.com/${repo}, branch ${branch}. This uploads all reachable commits and may trigger configured workflows or publication.`,
        commit: `Create a local commit on ${repo} branch ${branch} at ${tip}. Copy these session files into the repository root, replacing files with the same names:\n${manifest}\nCommit message: ${message}`,
        pages: `Configure GitHub Pages for https://github.com/${repo} from branch ${args.branch}, directory ${args.path}. This can replace the existing Pages source and publish that directory to the public web.`,
      };
      await checkAuthority();
      const approved = await ctx.ui.confirm("Approve GitHub " + action + "?", descriptions[action], {
        signal: controller.signal,
        timeout: 60000,
      });
      if (approved !== true) throw Error("GitHub action declined.");
      await checkAuthority();
      if (action === "pages") {
        const endpoint = "repos/" + repo + "/pages",
          options = { cwd: folder };
        const gh = (argv, input) =>
          command("gh", ["api", "--hostname", "github.com", endpoint, ...argv], { ...options, input });
        let method = "PUT";
        try {
          await gh(["--silent"]);
        } catch (e) {
          if (e.httpStatus !== 404) throw e;
          method = "POST";
        }
        await checkAuthority();
        await gh(
          ["--method", method, "--silent", "--input", "-"],
          JSON.stringify({ build_type: "legacy", source: { branch: args.branch, path: args.path } }),
        );
        return `Pages configured for ${repo} from ${args.branch} ${args.path}. Deployment status is unverified.`;
      }
      if (action === "clone") {
        await directory(base, true);
        await directory(namespace, true);
        if (
          await lstat(checkout).catch((e) => {
            if (e.code !== "ENOENT") throw e;
          })
        )
          throw Error("A checkout already exists for this chat and repository.");
        const temp = await mkdtemp(path.join(namespace, ".clone-"));
        try {
          const target = path.join(temp, "repo");
          await git(
            [
              "clone",
              "--depth",
              "1",
              "--no-tags",
              "--single-branch",
              "--no-recurse-submodules",
              "--template=",
              "--",
              url,
              target,
            ],
            { cwd: temp },
          );
          await checkAuthority();
          await rename(target, checkout);
        } finally {
          await rm(temp, { recursive: true, force: true });
        }
        return "Cloned " + repo + " into " + checkout + ".";
      }
      if ((await head()) !== revision || (await git(["symbolic-ref", "--short", "HEAD"])) !== branch)
        throw Error("Checkout changed after approval. Request this action again.");
      if (action === "push") {
        if (!revision) throw Error("Commit a file before pushing an empty branch.");
        await checkAuthority();
        await git([
          "push",
          "--no-force",
          "--no-follow-tags",
          "--recurse-submodules=no",
          "--",
          url,
          revision + ":refs/heads/" + branch,
        ]);
        return `Pushed ${repo} ${branch} at ${revision}.`;
      }
      if (await git(["status", "--porcelain", "--untracked-files=normal"]))
        throw Error("This action requires a clean managed checkout.");
      if (action === "pull") {
        await checkAuthority();
        await git([
          "pull",
          "--ff-only",
          "--no-rebase",
          "--no-tags",
          "--no-recurse-submodules",
          "--",
          url,
          "refs/heads/" + branch,
        ]);
        return `Pulled ${repo} ${branch} at ${await head()}.`;
      }
      // Build a tree in a temporary index. A failed file or commit never leaves a half-staged checkout.
      const temp = await mkdtemp(path.join(namespace, ".commit-"));
      try {
        const index = { env: { ...env, GIT_INDEX_FILE: path.join(temp, "index") } };
        await git(["read-tree", ...(revision ? [revision] : ["--empty"])], index);
        for (const { name, bytes } of sources) {
          const entry = revision ? await git(["ls-tree", revision, "--", name]) : "";
          if (entry && !/^100(644|755) blob /.test(entry))
            throw Error("Commit destinations must be ordinary files.");
          const blob = await git(["hash-object", "-w", "--stdin"], { input: bytes });
          await git(
            ["update-index", "--add", "--cacheinfo", entry.slice(0, 6) || "100644", blob, name],
            index,
          );
        }
        const tree = await git(["write-tree"], index);
        if (revision && tree === (await git(["rev-parse", revision + "^{tree}"])))
          throw Error("Selected files already match the current commit.");
        // Only read the two identity settings from the operator's normal global Git configuration.
        const identity = [];
        const globalEnv = { ...env };
        delete globalEnv.GIT_CONFIG_GLOBAL;
        for (const key of ["user.name", "user.email"]) {
          try {
            const value = await command("git", ["config", "--global", "--get", key], { env: globalEnv });
            if (value) identity.push("-c", key + "=" + value);
          } catch (e) {
            if (e.code !== 1) throw e;
          }
        }
        const commit = await git([
          ...identity,
          "commit-tree",
          tree,
          ...(revision ? ["-p", revision] : []),
          "-m",
          message,
        ]);
        await checkAuthority();
        await git(["merge", "--ff-only", "--no-edit", commit]);
        return `Committed ${sources.length} session file(s) to ${repo} ${branch} at ${commit}.`;
      } finally {
        await rm(temp, { recursive: true, force: true });
      }
    } finally {
      clearInterval(timer);
      signal?.removeEventListener("abort", cancel);
      busy.delete(folder);
    }
  };
}

export function registerGitHub(pi, { Type, getFolder, getTurn }) {
  const execute = githubActions({ getFolder, getTurn });
  pi.registerTool({
    name: "me3_github",
    label: "GitHub",
    description:
      "Act on an explicitly requested GitHub repository from this chat, after terminal approval. Commit copies only named session files into the clone root. Pages configures a branch publishing source.",
    parameters: Type.Object(
      {
        action: Type.Union(actions.map((a) => Type.Literal(a))),
        repo: Type.String({ maxLength: 140 }),
        files: Type.Optional(Type.Array(Type.String({ maxLength: 128 }), { minItems: 1, maxItems: 16 })),
        message: Type.Optional(Type.String({ maxLength: 200 })),
        branch: Type.Optional(Type.String({ maxLength: 128 })),
        path: Type.Optional(Type.Union([Type.Literal("/"), Type.Literal("/docs")])),
      },
      { additionalProperties: false },
    ),
    async execute(_id, args, signal, _update, ctx) {
      const text = await execute(args, ctx, signal);
      return { content: [{ type: "text", text }], details: {} };
    },
  });
  return execute;
}
