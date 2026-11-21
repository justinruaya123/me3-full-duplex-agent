---
name: bmo-website
description: Build a website in the BMO IntelligentUI canvas, research a personal portfolio with Pi and Brave, or publish a verified website revision to GitHub Pages.
---

Use `create_website` to build a site in the current Pi chat. The window shows the draft while it changes and embeds the finished HTML after verification. Keep design changes on the same job with `revise_delegated_task` when that job supports revision.

For “Search more about me and build a portfolio website on the canvas,” use `portfolio_research`. The host resolves the public search name and asks the person which sourced facts to include. Submit their selection through that review. The completed portfolio has a standalone HTML download in Agents.

For “Push this site to GitHub Pages for OWNER/REPO,” use `delegated_task_status` to get the completed website job and revision, then call `publish_github_pages`. Ask for the repository if it is missing. Pi shows the file list and public destination for approval. Report the returned commit and Pages source. A live URL needs deployment evidence.
