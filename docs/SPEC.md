TaskForge: turns merged PRs from public Python repos into SWE-Bench style
tasks (issue-style instruction, hidden tests, reference solution). Work like
a careful senior engineer: small steps, verify everything, never assume code
works because it looks right.

TECH STACK
- Python 3.11, Typer (CLI), httpx (GitHub API), Pydantic v2, SQLite (cache),
  pytest, ruff, mypy (strict). Git via subprocess. Docker via the docker CLI.
- Optional late stage: small FastAPI + React dashboard
- Layout: /forge (package), /tests, /scripts, /docs, /data (gitignored: clones,
  cache), /output (gitignored except one small committed sample task)

SAFETY AND LICENSE RULES
- Only repos on an allowlist (forge/allowlist.yaml) with MIT, Apache-2.0, or
  BSD licenses. Verify the license through the API and refuse otherwise.
- NEVER run repo code outside the Docker sandbox: no network, CPU and memory
  limits, timeout, read-only mounts for patches, nothing from the host mounted
  except what is needed.
- GitHub token comes from .env only. Never commit it, never print it. Respect
  rate limits (conditional requests, backoff, local cache).
- Every generated task includes ATTRIBUTION.md (repo, license, PR URL, issue
  URL, commit SHAs).
     - The first commit must include a .gitignore covering .env, /data, /output
     (except the one committed sample task), .venv, and __pycache__. Add a
     test that fails if .env is tracked by git.

OUTPUT TASK FORMAT (our own)
output/<task_id>/
  task.json     (task_id, repo, license, pr_url, issue_url, base_commit,
                 difficulty_signals, f2p, p2p, tool_version)
  instruction.md
  solution/solution.patch   (source changes only)
  tests/test.patch          (test changes only)
  tests/config.json         (f2p and p2p test ids)
  ATTRIBUTION.md

PR FILTERS
merged; linked issue via closing keyword; touches 1+ source file and 1+ test
file; at most 5 files and 300 changed lines; not docs-only, binary, lockfile,
or revert. Every rejection records a reason code.

VALIDATION GATES (run in the sandbox)
V1 environment builds at base commit.
V2 with only the test patch applied, at least 1 test fails.
V3 with solution applied, every f2p test passes and every p2p test passes.
V4 three repeat runs give identical results (else reject as flaky).
V5 total runtime under the limit.
V6 fail reason: classify each f2p failure (assertion, import/attribute error,
   other). If import/attribute error, require that instruction.md names the
   missing function and signature, else flag unfair.
V7 leakage: instruction must not contain code lines from solution.patch.
V8 hidden requirement: flag tests asserting exact error messages absent from
   the instruction.

STAGES
1. Setup, config, allowlist with license check, GitHub client with caching and
   rate-limit handling, CLI skeleton.
2. PR fetcher and filters, funnel report with rejection reasons.
3. Patch splitting (source vs tests), linked issue extraction, tests.
4. Docker sandbox runner (image per repo and commit, no network, limits,
   timeout), with tests for the isolation settings.
5. Compute f2p and p2p by running tests before and after the solution.
6. Validation gates V1 to V5 with reject reasons.
7. Quality checks V6 to V8, instruction builder (rule-based first), task
   packager with attribution.
8. Labeled evaluation: hand-label about 30 candidates with a written rubric,
   report precision and recall of the accept decision, save to
   docs/EVALUATION.md as v1.
9. Held-out: run a repo never used for tuning, label by hand without
   looking at the code, record before and after, do not tune against it.
10. Reports (JSON and Markdown), optional small dashboard.
11. Docs and CI: README, docs/DESIGN.md, GitHub Actions workflow.
12. Fresh-clone audit: follow only the README, fix anything missing, confirm
    git tracks no secrets, caches, or clones.

HONESTY RULES
- Never use real company, client, or evaluation-platform task data, formats,
  or rubrics. Use only public repos on the allowlist.
- Never tune labels to match the pipeline. Never tune against a held-out set
  that has been seen.
- Do not inflate results. Tasks are not validated against real agents, so
  difficulty is only an estimate. Say so in the docs.
- Document limitations: Python and pytest only, depends on PR and issue
  quality, public repos may be in model training data, not a security audit.