Git Commit & Push Playbook

<!-- Loaded when: the user says 「推到git」, "push to git", or any similar phrasing.
     That phrase is a trigger: run the ENTIRE sequence below — commit → branch → push → docs sync — in one go.
     It also counts as the explicit instruction that docs/workflow.md requires before pushing to a remote. -->



Trigger

- Any variation of "push it to git": 「推到git」, "push to git", 「推上去」, "push it up", etc.
- When triggered, execute all steps below in order, starting with the review. Do not skip Step 0 and do not stop after the commit.

Step 0 — Code Review (mandatory, before any commit)

- Run the full review flow in docs/code-review.md on the pending diff — including its model-selection step (ask the user to pick the reviewer and fixer models before running).
- Run its review → fix loop to the end: if the fixed code still needs changes, those changes go back into the loop for another round — never commit half-fixed work.
- Only proceed to Step 1 when the loop exits clean, or the user explicitly waives the remaining findings.

Step 1 — Commit

- Stage only the files you intended to change — never git add -A blindly.
- Title format: TYPE: <short summary> where TYPE ∈ FEATURE | FIX | CHORE | REFACTOR | DOCS, always uppercase.
- Always pass two -m flags: the first is the title, the second is the body (what changed and why).

- git commit -m "FIX: handle empty availability payload" \
-            -m "Parser crashed when the feed returned an empty list; skip the update instead."


Step 2 — Branch

- Before branching, sync local main with the remote: git switch main && git pull origin main. Do this even if you think local main is already current — a prior branch's PR may have merged since you last checked.
- After committing, create a new branch named <type>-<改動摘要>: the type plus a short kebab-case summary of the change.

- git switch -c fix-empty-availability-payload


- Branching after the commit carries the commit onto the new branch — that is intended.

Step 3 — Push

- Push the new branch to origin and set upstream:

- git push -u origin fix-empty-availability-payload


- Push ONLY this branch. Never push main/master as part of this flow.

Step 4 — Docs Sync (keep docs/ current with what was just committed)

- Look at what the commit changed and find the affected doc(s) in docs/ (use the routing table in AGENTS.md).
- Update those docs so they describe the code as it is AFTER this commit. Touch only the sections the commit affects — do not rewrite unrelated content.
- If nothing in docs/ is affected, say so and skip the rest of this step.
- MANUAL REVIEW GATE: show the doc changes to the user and WAIT for approval. Never commit or push docs changes without it.
- After approval, commit the docs as a separate DOCS: commit on the same branch and push it.

After Pushing

- Switch back to main and sync it with the remote: git switch main && git pull origin main. Once the branch's PR is merged, this pulls the merge in and keeps local main from drifting ahead with commits that only belong on the feature branch.
- Report back: the commit title, the branch name, the push result, and the docs-sync outcome (which docs changed, or "no docs affected").
- generate pr message
- check AGENTS.md to see if structure needs to be changed, if so update it
- check ROADMAP.md to see if structure needs to be changed, if so update it

Type Cheat Sheet
Type	Use for
FEATURE	new user-facing capability
FIX	bug fix
REFACTOR	behavior-preserving restructuring
CHORE	tooling, deps, config
DOCS	documentation only (incl. the Step 4 docs-sync commit)
