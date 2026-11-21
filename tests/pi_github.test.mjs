import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtemp, mkdir, readdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { githubActions, runCommand } from "../me3/pi_github.mjs";

const repo = "octo/example";
const git = (cwd, ...args) =>
  execFileSync(
    "git",
    [
      "-c",
      "core.hooksPath=/dev/null",
      "-c",
      "user.name=Example",
      "-c",
      "user.email=example@localhost",
      ...args,
    ],
    { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
  ).trim();

async function fixture(t) {
  const temp = await mkdtemp(path.join(os.tmpdir(), "me3-git-test-"));
  t.after(() => rm(temp, { recursive: true, force: true }));
  const folder = path.join(temp, "chat"),
    remote = path.join(temp, "remote.git");
  await mkdir(folder);
  git(temp, "init", "--bare", "-b", "main", remote);
  const author = path.join(temp, "author");
  git(temp, "clone", remote, author);
  await writeFile(path.join(author, "README.md"), "original");
  git(author, "add", "README.md");
  git(author, "commit", "-m", "initial");
  git(author, "push", "origin", "main");
  const state = {
    folder,
    turn: { id: "current", text: "Please clone octo/example" },
    confirm: () => true,
    pages: [],
  };
  const dialogs = [];
  const ctx = {
    hasUI: true,
    ui: {
      async confirm(title, body, options) {
        assert.ok(options.signal instanceof AbortSignal);
        dialogs.push([title, body].join("\n"));
        return state.confirm();
      },
    },
  };
  const execute = githubActions({
    getFolder: () => state.folder,
    getTurn: () => state.turn,
    run: async (bin, args, options) => {
      if (bin === "gh") {
        state.pages.push({args, body: options.input && JSON.parse(options.input)});
        if (!args.includes("--method") && !state.existing)
          throw Object.assign(Error("missing"), { httpStatus: 404 });
        return "";
      }
      // Substitute a disposable local bare remote only at the process boundary.
      const argv = args.map((arg) => (arg === "https://github.com/octo/example.git" ? remote : arg));
      return runCommand(
        bin,
        ["-c", "user.name=Example", "-c", "user.email=example@localhost", ...argv],
        { ...options, env: { ...options.env, GIT_ALLOW_PROTOCOL: "file" } },
      );
    },
  });
  return {
    state,
    dialogs,
    folder,
    remote,
    author,
    ctx,
    execute,
    call: (action, extra = {}) => {
      state.turn.text =
        action === "pages" ? "Publish this site on GitHub Pages" : "Please " + action + " octo/example";
      return execute({ action, repo, ...extra }, ctx);
    },
  };
}

test("clone, commit only selected new or changed session files, push and fast-forward pull", async (t) => {
  const f = await fixture(t);
  await f.call("clone");
  assert.match(f.dialogs[0], /octo\/example/);
  await writeFile(path.join(f.folder, "index.html"), "hello world");
  await writeFile(path.join(f.folder, "README.md"), "new readme");
  await writeFile(path.join(f.folder, "secret.txt"), "not selected");
  await f.call("commit", { files: ["index.html", "README.md"], message: "Site update" });
  assert.match(f.dialogs.at(-1), /index.html/);
  assert.match(f.dialogs.at(-1), /Site update/);
  await f.call("push");
  assert.equal(git(f.remote, "show", "main:index.html"), "hello world");
  assert.equal(git(f.remote, "show", "main:README.md"), "new readme");
  assert.equal(git(f.remote, "ls-tree", "--name-only", "main"), "README.md\nindex.html");
  git(f.author, "pull", "--ff-only", "origin", "main");
  await writeFile(path.join(f.author, "incoming"), "external change");
  git(f.author, "add", "incoming");
  git(f.author, "commit", "-m", "incoming");
  git(f.author, "push", "origin", "main");
  await f.call("pull");
  assert.equal(
    await readFile(path.join(f.folder, ".github-repos", "octo", "example", "incoming"), "utf8"),
    "external change",
  );
});

test("cancelled clone, stale voice or typed turns, missing UI and aborted calls fail closed", async (t) => {
  const f = await fixture(t);
  f.state.confirm = () => false;
  await assert.rejects(f.call("clone"), /declined|cancel/i);
  f.state.confirm = () => {
    f.state.turn = { id: "next", text: "other" };
    return true;
  };
  await assert.rejects(f.call("clone"), /stale|changed/i);
  f.state.confirm = () => {
    f.state.folder = "/different-chat";
    return true;
  };
  await assert.rejects(f.call("clone"), /stale|changed/i);
  f.state.folder = f.folder;
  await assert.rejects(f.execute({ action: "clone", repo }, { hasUI: false }), /interactive/i);
  await assert.rejects(
    f.execute({ action: "clone", repo }, f.ctx, AbortSignal.abort()),
    /abort|cancel/i,
  );
  f.state.confirm = () => true;
  await assert.rejects(
    f.execute({ action: "clone", repo }, f.ctx, undefined, {
      id: "voice",
      text: "clone",
      isCurrent: () => false,
    }),
    /stale|changed/i,
  );
  assert.deepEqual(await readdir(f.folder), []);
});

test("invalid repository, branch, commit file and extra arguments are rejected before prompting", async (t) => {
  const f = await fixture(t);
  for (const args of [
    { action: "clone", repo: "https://other/owner/r" },
    { action: "clone", repo: "a/.." },
    { action: "pull", repo, force: true },
    { action: "pages", repo, branch: "--upload-pack=x", path: "/" },
    { action: "pages", repo, branch: "main", path: "/private" },
    { action: "commit", repo, files: ["../private"], message: "test" },
  ]) {
    await assert.rejects(f.execute(args, f.ctx));
  }
  assert.equal(f.dialogs.length, 0);
});

test("session file symlinks and checkout directory symlinks are refused", async (t) => {
  const f = await fixture(t);
  await f.call("clone");
  await symlink(path.join(f.author, "README.md"), path.join(f.folder, "leak"));
  await assert.rejects(f.call("commit", { files: ["leak"], message: "forbidden" }));
  const alt = path.join(f.folder, "unrelated");
  await mkdir(alt);
  await symlink(path.join(f.folder, ".github-repos"), path.join(alt, ".github-repos"));
  f.state.folder = alt;
  await assert.rejects(f.call("pull"), /directory|symlink/i);
});

test("Pages shows public source, creates or updates only after approval and reports configuration", async (t) => {
  const f = await fixture(t);
  f.state.confirm = () => false;
  await assert.rejects(f.call("pages", { branch: "main", path: "/docs" }));
  assert.equal(f.state.pages.length, 0);
  f.state.confirm = () => true;
  for (const [existing, method] of [
    [false, "POST"],
    [true, "PUT"],
  ]) {
    f.state.existing = existing;
    const result = await f.call("pages", { branch: "main", path: "/docs" });
    assert.match(result, /configured/i);
    assert.match(result, /deployment/i);
    assert.match(f.dialogs.at(-1), /public/i);
    assert.match(f.dialogs.at(-1), /main/);
    assert.match(f.dialogs.at(-1), /\/docs/);
    assert.ok(f.state.pages.at(-1).args.includes(method));
    assert.ok(f.state.pages.at(-1).args.includes("repos/octo/example/pages"));
    assert.deepEqual(f.state.pages.at(-1).body, { build_type: "legacy", source: { branch: "main", path: "/docs" } });
  }
});

test("the host can revoke asynchronous voice authority while the dialog is open", async (t) => {
  const f = await fixture(t);
  let authorized = true;
  f.state.turn.isCurrent = async () => authorized;
  f.state.confirm = () => {
    authorized = false;
    return true;
  };
  await assert.rejects(f.call("clone"), /turn changed/);
  assert.deepEqual(await readdir(f.folder), []);
});

test("unborn default branch accepts a first commit and push", async (t) => {
  const f = await fixture(t);
  git(f.remote, "update-ref", "-d", "refs/heads/main");
  await f.call("clone");
  await writeFile(path.join(f.folder, "index.html"), "first file");
  await f.call("commit", { files: ["index.html"], message: "Initial page" });
  await f.call("push");
  assert.equal(git(f.remote, "show", "HEAD:index.html"), "first file");
});

test("push and pull on diverged branches preserve both commit histories", async (t) => {
  const f = await fixture(t);
  await f.call("clone");
  await writeFile(path.join(f.folder, "index.html"), "local change");
  await f.call("commit", { files: ["index.html"], message: "Local" });
  await writeFile(path.join(f.author, "README.md"), "remote change");
  git(f.author, "add", "README.md");
  git(f.author, "commit", "-m", "Remote");
  git(f.author, "push", "origin", "main");
  const remoteHead = git(f.remote, "rev-parse", "HEAD");
  const clone = path.join(f.folder, ".github-repos", "octo", "example");
  const localHead = git(clone, "rev-parse", "HEAD");
  await assert.rejects(f.call("push"));
  await assert.rejects(f.call("pull"));
  assert.equal(git(f.remote, "rev-parse", "HEAD"), remoteHead);
  assert.equal(git(clone, "rev-parse", "HEAD"), localHead);
});

test("a pre-staged unrelated file stays staged and outside any ME3 commit", async (t) => {
  const f = await fixture(t);
  await f.call("clone");
  const checkout = path.join(f.folder, ".github-repos", "octo", "example");
  await writeFile(path.join(checkout, "other"), "staged by operator");
  git(checkout, "add", "other");
  await writeFile(path.join(f.folder, "index.html"), "selected by operator");
  const original = git(checkout, "rev-parse", "HEAD");
  await assert.rejects(
    f.call("commit", { files: ["index.html"], message: "One selected file" }),
    /clean/,
  );
  assert.equal(git(checkout, "rev-parse", "HEAD"), original);
  assert.equal(git(checkout, "diff", "--cached", "--name-only"), "other");
});

test("unrelated questions, explanations and negated actions cannot open approvals", async (t) => {
  const f = await fixture(t);
  for (const text of [
    "Summarize this note",
    "How do I push to GitHub?",
    "Please do not push that",
    "What does git push do?",
    "Clone octo/example",
  ]) {
    f.state.turn.text = text;
    await assert.rejects(f.execute({ action: "push", repo }, f.ctx), /request.*push/i);
  }
  assert.equal(f.dialogs.length, 0);
});
