---
name: me3-github
description: Use the interactive ME3 GitHub tool when the operator asks to clone, pull, commit, push, or publish a repository with GitHub Pages.
---

Use `me3_github` from the main Pi chat. Every call requires the operator to approve its exact effect in the terminal. Ask for a missing repository, selected filenames, commit message, or Pages source. Repository names use `OWNER/REPO` on github.com.

- `clone` downloads the default branch into this chat’s private managed checkout.
- `pull` fast-forwards its current branch from the branch with the same name on GitHub.
- `commit` takes `files` and `message`. Supply 1–16 named text files already in this chat’s work folder. The tool copies their exact contents to same-named files at the checkout root and commits them locally. For example, use `files: ["index.html"]`. Each file can contain up to 16 KiB. Use the session-file tool to prepare files at the operator’s request.
- `push` uploads the approved commit and its history to the same branch on GitHub.
- `pages` takes an explicit `branch` and `path` of `/` or `/docs`. It configures branch publishing on GitHub, which can expose that directory publicly. The requested source must already exist on GitHub. Report the configuration result and distinguish it from a verified live deployment.

A publication request can require separate commit, push and Pages approvals. Keep a declined action declined. Local Git operations run on the client, with GitHub authentication supplied by the operator’s GitHub CLI.
