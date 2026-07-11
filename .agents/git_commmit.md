# Git Commit & Push Playbook

<!-- Loaded when: the user says 「推到git」, "push to git", or any similar phrasing.
     That phrase is a trigger: run the ENTIRE sequence below in one go. -->

## Trigger
- Any variation of "push it to git": 「推到git」, "push to git", 「推上去」, "push it up", etc.
- When triggered, execute all steps below in order. Do not skip any steps.

## Step 1 — Sync Main
Always start by syncing the local main branch with the remote to ensure your base is up to date:
```bash
git switch main
git pull origin main
```

## Step 2 — Status & Branch
Check the current status:
```bash
git s
```
Create and switch to a new branch (name it appropriately based on the task, e.g., `type-summary`):
```bash
git cb {new-branch-name}
```

## Step 3 — Commit
Stage only the intended files. Title format: `TYPE: <short summary>` where TYPE ∈ FEATURE | FIX | CHORE | REFACTOR | DOCS (always uppercase).
```bash
git commit -m "TYPE: <short summary>" -m "<details of what changed and why>"
```

## Step 4 — Push
Push the new branch to the remote:
```bash
git push origin {new-branch-name}
```

## Step 5 — Diff & PR Message
Run a diff to review the changes between main and your new branch:
```bash
git diff main..{new-branch-name}
```
Based on the diff output, generate a clear, concise Pull Request (PR) message summarizing the changes for the user.

## Type Cheat Sheet

| Type | Use for |
| :--- | :--- |
| **FEATURE** | new user-facing capability |
| **FIX** | bug fix |
| **REFACTOR**| behavior-preserving restructuring |
| **CHORE** | tooling, deps, config |
| **DOCS** | documentation only |