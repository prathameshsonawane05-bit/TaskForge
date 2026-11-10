# Design

TaskForge keeps the first failing check and records that reason. A later check is not consulted after an earlier one has failed.

## Filter order

A closed pull request is rejected for the first reason below. `considered` later equals `accepted` plus these counts.

1. `not_merged`. `merged_at` is missing. An unmerged pull request is not a candidate.
2. `revert`. The title matches `^\s*revert` with case ignored, or the body contains the sentence `This reverts commit`.
3. `unknown_size`. `changed_files` is missing. A missing count is not zero.
4. `too_many_files`. `changed_files` is greater than 5.
5. `unknown_size`. `additions` or `deletions` is missing.
6. `too_many_lines`. `additions` plus `deletions` is greater than 300.
7. `too_many_files` again, when the file list is longer than 5. The pull field and the file list can differ. Both are applied.
8. `binary`. The file is marked binary, or its suffix is one of the known binary suffixes. A missing patch is not enough.
9. `lockfile`. The basename is `poetry.lock`, `uv.lock`, `Pipfile.lock`, `pdm.lock`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, or `go.sum`.
10. `docs_only`. Every file is documentation: suffix `.md`, `.rst`, `.txt`, `.adoc`, or `.asciidoc`, basename `license`, `copying`, `authors`, or `changelog`, or a path under `doc/` or `docs/`.
11. `missing_source_or_test`. The file list needs at least one Python source file and one Python test file. A test file is `conftest.py`, `test_*.py`, `*_test.py`, or a `.py` file under `test/` or `tests/`. Any other `.py` file is source.
12. `no_linked_issue`. A closing keyword (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) must sit immediately before `#N`, `owner/repo#N`, or `https://github.com/owner/repo/issues/N`. `Since #13714` is not a link. A keyword and a number in different sentences do not link.

## Sandbox

`forge sandbox`, `forge outcomes`, `forge gates`, and `forge package` run repository code only inside Docker. The `docker run` limits are:

- `--network none`
- `--memory 512m`
- `--cpus 1`
- a timeout, 60 seconds unless a command passes `--timeout`. On timeout the container is removed and the process exits 2.
- one read-only mount, the patch file at `/patch` (a patch directory is mounted at `/patches`)

The host checkout, `.env`, and the Docker socket are not mounted. The GitHub token is not passed to git or Docker. The image is `python:3.11-slim` for the host architecture. The command does not pass `--platform`. The eval image installs git and pytest while it is built. When the checkout has `pyproject.toml` or `setup.py`, that build runs `pip install -e .` after the files are copied and does not name any further package. A checkout without those files, including the widget and counter fixtures, keeps the git and pytest image. The build may use the network. The run stays offline.

An existing clone is fetched only when its origin URL is exactly `https://github.com/<owner>/<name>.git`. Any other URL is a sandbox error, and the image is not built. After the commit is checked out, that commit is reset and untracked files are removed. The image build starts only when HEAD is the requested commit and `git status --porcelain` is empty. The sandbox is not a complete security boundary. Residual risks: the build has network and runs the checkout's installer; the container runs as root with a writable filesystem; the token is removed from the build and run environment.

## Gates V1 through V8

The first failure is the only reject reason.

- V1 `build_failed`. The image does not build at the base commit.
- V2 `no_failure_before`. With only the test patch applied, at least one test must fail. A skip is not a failure.
- V3 `no_fail_to_pass`. At least one test must fail before the solution and pass after it. Only a status of pass counts as a pass.
- `regression`. A test that passed before the solution fails after it. This is how a pass-to-pass test is required to stay passing. It is checked before the repeat runs.
- V4 `flaky`. Three repeats must agree on the classification and on the before and after pytest statuses. Each repeat starts a baseline container and a solved container from the same image. The baseline container applies the test patch only. The solved container starts from the image again, applies the test patch, and then applies the solution. Each container is removed when its pytest exits.
- V5 `too_slow`. The sum of every container's wall time is over 30 seconds.
- V6. Each fail-to-pass failure from the before run is `assertion`, `import_or_attribute`, or `other`. An import or attribute failure is `unfair` unless the instruction names the missing function and a signature. Mixed kinds are named in the header. `other` is one kind, not a label for a mix.
- V7. An added source line from `solution.patch`, excluding diff headers, must not equal a whole stripped instruction line. A sentence that merely contains that text is not a leak.
- V8. A quoted `pytest.raises` match, or a quoted equality on exception text, must appear in the instruction. Otherwise the check is `hidden_requirement`. `assert value() == 1` is not an error message.

`forge package` writes a task only when V1 through V5 accept and V6 through V8 are clean. The widget fixture stays rejected for `regression`. `forge package widget` and `forge package counter` are unchanged.

`forge package-pull owner/name NUMBER` checks the allowlist and the SPDX license, then applies the current filters. A filter rejection other than a binary file or a lockfile writes nothing and exits 1 with that reason. A changed file with no patch, a binary file, or a lockfile is `unsupported_file`. That refusal writes nothing and exits 1. It is not a funnel filter. An accepted pull request uses the existing split, the editable eval image, and the existing trial. A Python test file goes only in the test patch. Other Python files, and text files that ride along, go only in the solution patch. The base checkout is not modified by either patch. The base commit is the first parent of the merge commit. The package is written under `output/` only when V1 through V5 accept and V6 through V8 are clean. It records the repository, the SPDX id, the pull-request URL, the issue URL, and the commit SHAs. Difficulty is an estimate.

## Funnel report

`forge report owner/name --limit N` runs the funnel and writes two files under `output/reports/`:

- `<owner>-<name>-<limit>.json`
- `<owner>-<name>-<limit>.md`

Both repeat the funnel fields: `repo`, `limit`, `order created desc`, `considered`, every rejection count, `accepted`, and `older_prs_cut_off` (`yes` or `no`). The closed list is ordered by created time, descending. Each pull stays in the order the list response returns it. The report does not add a timestamp for every pull request. `considered` must equal `accepted` plus the rejection counts. When it does not, the command writes neither file. A refused repository writes neither file. The report does not contain precision or recall.

## Limitations

- Python and pytest only.
- Task quality depends on the pull request and the issue text.
- Public repositories may already be in model training data.
- This is not a security audit.
- Difficulty is only an estimate. Tasks are not validated against real agents.
- The labeled evaluation and the held-out window were written by the same author as the filters. The funnel accepted none in either window, so precision is undefined and recall is undefined. Agreement on those rejects is not evidence that an accept would be right.
- The click window was also written by that author. Precision was 4/4 and recall was 4/4. That agreement is not an independent evaluation.
- The one upstream package is pull request 3858 of `pallets/click`. Nine tests still failed, twenty were skipped, and V6 recorded `other`. It is not committed.
- The only committed task is `output/sample/local-counter`. It has no upstream repository, and it was written to pass the gates.
