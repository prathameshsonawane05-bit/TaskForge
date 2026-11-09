# Working agreement

Unless you were told "you are the mentor", you are the BUILDER.

## Builder rules
1. Read docs/SPEC.md and docs/PROGRESS.md before doing anything.
2. Do ONE stage at a time, then stop and wait for the user to say "next".
3. After each stage, run the checks and show the REAL command output
   (ruff, mypy, pytest). Never say "everything passes" without the output.
4. Fix every bug and warning before committing. No skipped tests, no known
   issues left for later.
5. For CLI stages, run the CLI on a real repo or sample and show the output,
   including at least one error case.
6. Before committing, review your own diff for wrong imports, off-by-one
   errors, unhandled None, hardcoded paths, shared mutable state, leaked
   secrets, and unused code. Fix what you find and re-run all checks.
7. Order of work for each stage: commit the code, then append a report to
   docs/PROGRESS.md with the real commit hash, then make a second small commit
   ("docs: progress report for stage N"). Template:

   ## Stage N: <title> (commit <hash>)
   What was built:
   Commands run and their real output:
   Bugs found and fixed:
   Files changed:
   Decisions and open questions:
   Next stage:

8. Before changing any check or filter, say what it got wrong and why.

## Safety and honesty rules
- Never run repo code outside the Docker sandbox. Never print or commit the
  GitHub token. Only use allowlisted, permissively licensed repos.
- Never use real company, client, or evaluation-platform task data, formats,
  or rubrics.
- Never tune labels to match the pipeline. Never tune against a held-out set
  that has been seen. Write a new one.
- Do not inflate results. State limitations plainly.