---
name: draft-pr
description: Inspect the current git diff and write a PR title + body suitable for posting to GitHub.
allowed_tools:
  - Bash
  - Read
  - Glob
model_override: claude-sonnet-4-6
execution_mode: inline
---

# Draft PR

You are writing a pull request description for the changes the operator has staged. Workflow:

1. **Inspect.** Run these via `Bash`:
   - `git status -s` — what's changed?
   - `git diff --stat` — overall scope
   - `git log --oneline -5` — convention for commit style on this repo
   - `git diff main...HEAD` (or `git diff` for unstaged) — read the actual changes

   Don't read every file — use `git diff` summary first, then drill into specific files via `Read` only when the diff alone doesn't tell the story.

2. **Classify.** What kind of change is this? `feat` / `fix` / `refactor` / `docs` / `test` / `chore`. The repo's recent history (step 1) is the source of truth on convention.

3. **Title.** One imperative-mood sentence under 70 characters, prefixed by the type. E.g. `feat(canvas): widen pipeline visualization to 21 stages`. NO emoji, NO "feat!:" syntax unless the repo already uses it.

4. **Body.** Three sections:
   - **Summary** — 2–4 sentence prose describing what + why. Link to issue / cycle docs if the diff references one.
   - **Test plan** — bullet list of test commands or manual steps.
   - **Risk** — one sentence on rollback path or "additive — safe revert".

5. **Output.** Print the title on the first line, then a blank line, then the body. The operator will copy-paste into `gh pr create`.

Don't invent context that isn't in the diff. If something looks intentional but unexplained, either ask the operator or note "rationale unclear from diff" in the Summary instead of fabricating.
