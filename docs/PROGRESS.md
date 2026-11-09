# Progress log

## Stage 0: environment setup (commit a729864e83dae5ac016441f50365e3bf732e25bb)

What was built:
Docker was already installed and the daemon answered, so nothing was installed. Git was initialized. Added `.gitignore` (`.env`, `.venv/`, `__pycache__/`, `/data/`, `/output/*` with `!/output/sample/` left committable), `.env` containing only `GITHUB_TOKEN=` (not committed), and `.env.example` with `GITHUB_TOKEN=your_token_here`.

Commands run and their real output:

`docker --version`

```
Docker version 27.4.1, build b9d17ea
```

`docker info`

```
Client:
 Version:    27.4.1
 Context:    colima
 Debug Mode: false
 Plugins:
  buildx: Docker Buildx (Docker Inc.)
    Version:  v0.19.3
    Path:     /Users/shubhambaviskar/.docker/cli-plugins/docker-buildx
  compose: Docker Compose (Docker Inc.)
    Version:  v2.32.4
    Path:     /Users/shubhambaviskar/.docker/cli-plugins/docker-compose

Server:
 Containers: 0
  Running: 0
  Paused: 0
  Stopped: 0
 Images: 15
 Server Version: 27.4.0
 Storage Driver: overlay2
  Backing Filesystem: extfs
  Supports d_type: true
  Using metacopy: false
  Native Overlay Diff: true
  userxattr: false
 Logging Driver: json-file
 Cgroup Driver: cgroupfs
 Cgroup Version: 2
 Plugins:
  Volume: local
  Network: bridge host ipvlan macvlan null overlay
  Log: awslogs fluentd gcplogs gelf journald json-file local splunk syslog
 Swarm: inactive
 Runtimes: io.containerd.runc.v2 runc
 Default Runtime: runc
 Init Binary: docker-init
 containerd version: 88bf19b2105c8b17560993bee28a01ddc2f97182
 runc version: v1.2.2-0-g7cb3632
 init version: de40ad0
 Security Options:
  apparmor
  seccomp
   Profile: builtin
  cgroupns
 Kernel Version: 6.8.0-50-generic
 Operating System: Ubuntu 24.04.1 LTS
 OSType: linux
 Architecture: aarch64
 CPUs: 4
 Total Memory: 5.773GiB
 Name: colima
 ID: 4718bd87-2f94-47d2-8454-a50981ca4f5c
 Docker Root Dir: /var/lib/docker
 Debug Mode: false
 Experimental: false
 Insecure Registries:
  127.0.0.0/8
 Live Restore Enabled: false

WARNING: bridge-nf-call-iptables is disabled
WARNING: bridge-nf-call-ip6tables is disabled
```

`docker run --rm hello-world` succeeded. The image was pulled and the container printed "Hello from Docker!" plus the standard install-check text. Exit code 0.

`docker info | grep -i "Total Memory"`

```
WARNING: bridge-nf-call-iptables is disabled
WARNING: bridge-nf-call-ip6tables is disabled
 Total Memory: 5.773GiB
```

`docker info | grep CPUs`

```
WARNING: bridge-nf-call-iptables is disabled
WARNING: bridge-nf-call-ip6tables is disabled
 CPUs: 4
```

`git init`

```
Initialized empty Git repository in /Users/shubhambaviskar/Desktop/Task Forge/.git/
```

`git check-ignore -v .env`

```
.gitignore:1:.env	.env
```

`git ls-files | grep -E "^\.env$"` printed nothing.

ruff, mypy, and pytest were not run. This stage has no Python package yet.

Bugs found and fixed:
None.

Files changed:
`.gitignore`, `.env.example`, `AGENTS.md`, `Docs/MENTOR.md`, `Docs/PROGRESS.md`, `Docs/SPEC.md`. `.env` exists on disk and is ignored.

Decisions and open questions:
Docker already worked (Colima context), so Homebrew and Docker Desktop install steps were skipped. 4 CPUs and 5.773GiB are above the 2 CPU / 4 GB floor, so resources were not raised. The one committable sample folder is `output/sample/`. The iptables warnings from `docker info` did not stop hello-world.

Next stage:
Stage 1: setup, config, allowlist with license check, GitHub client with caching and rate-limit handling, CLI skeleton. Waiting for "next".

## Stage 1: setup, config, allowlist, GitHub client, CLI (commit 3912f89d25b44b9cfaf58763e6c97d1dc2c06a9e)

What was built:
Python 3.11 package `forge` with a Typer CLI. `forge check owner/name` accepts a repository only when it is on `forge/allowlist.yaml` and the GitHub API reports SPDX `MIT`, `Apache-2.0`, `BSD-2-Clause`, or `BSD-3-Clause`. Anything else is refused with a reason code. The token is read only from `.env`. The GitHub client stores response bodies in `data/github_cache.sqlite`, sends `If-None-Match`, and uses the cached body on 304. On HTTP 403 or 429 it waits using `Retry-After`, or `X-RateLimit-Reset` when the remaining quota is 0, otherwise 1 second, then fails. The wait is capped at 60 seconds. `Docs/` was renamed to `docs/` with a two-step `git mv`. No repositories were cloned and no repository code was run.

Allowlisted repositories, confirmed live against the GitHub API:
- `pydantic/pydantic` — MIT
- `psf/requests` — Apache-2.0
- `pallets/click` — BSD-3-Clause
- `encode/httpx` — BSD-3-Clause

`BSD-2-Clause` is accepted by the checker and covered by unit tests. None of these four repositories uses it.

Reason codes: `not_on_allowlist`, `license_missing`, `license_noassertion`, `license_not_allowed`, `missing_token`, `rate_limited`, `github_error`, `invalid_repo`, `config_error`, `internal`.

Exit status: 0 accepted, 1 refused, 2 the check could not be completed. A repo that is not on the allowlist is refused before any HTTP call.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/ruff format --check forge tests` (same Python files as the commit; run before the final `.gitignore` line)

```
18 files already formatted
```

`.venv/bin/mypy`

```
Success: no issues found in 18 source files
```

`.venv/bin/pytest -v`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0 -- /Users/shubhambaviskar/Desktop/TaskForge/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collecting ... collected 49 items

tests/test_allowlist.py::test_real_allowlist_names_the_chosen_repos PASSED [  2%]
tests/test_allowlist.py::test_allowed_spdx_ids_are_only_the_permissive_set PASSED [  4%]
tests/test_allowlist.py::test_membership_is_case_insensitive PASSED      [  6%]
tests/test_allowlist.py::test_malformed_allowlist_is_rejected PASSED     [  8%]
tests/test_check.py::test_permissive_licenses_are_accepted[MIT] PASSED   [ 10%]
tests/test_check.py::test_permissive_licenses_are_accepted[Apache-2.0] PASSED [ 12%]
tests/test_check.py::test_permissive_licenses_are_accepted[BSD-2-Clause] PASSED [ 14%]
tests/test_check.py::test_permissive_licenses_are_accepted[BSD-3-Clause] PASSED [ 16%]
tests/test_check.py::test_other_spdx_ids_are_refused[NOASSERTION-license_noassertion] PASSED [ 18%]
tests/test_check.py::test_other_spdx_ids_are_refused[BSD-license_not_allowed] PASSED [ 20%]
tests/test_check.py::test_other_spdx_ids_are_refused[BSD-4-Clause-license_not_allowed] PASSED [ 22%]
tests/test_check.py::test_other_spdx_ids_are_refused[0BSD-license_not_allowed] PASSED [ 24%]
tests/test_check.py::test_other_spdx_ids_are_refused[GPL-3.0-license_not_allowed] PASSED [ 26%]
tests/test_check.py::test_other_spdx_ids_are_refused[mit-license_not_allowed] PASSED [ 28%]
tests/test_check.py::test_null_license_is_refused PASSED                 [ 30%]
tests/test_check.py::test_allowlisted_repo_with_wrong_license_is_refused PASSED [ 32%]
tests/test_check.py::test_repo_not_on_the_allowlist_does_not_call_github PASSED [ 34%]
tests/test_check.py::test_invalid_repo_names PASSED                      [ 36%]
tests/test_cli.py::test_cli_refuses_a_repo_that_is_not_allowlisted PASSED [ 38%]
tests/test_cli.py::test_cli_missing_token PASSED                         [ 40%]
tests/test_cli.py::test_cli_accepts_allowlisted_repo_and_hides_the_token PASSED [ 42%]
tests/test_cli.py::test_cli_redacts_a_token_hidden_in_the_license_payload PASSED [ 44%]
tests/test_cli.py::test_cli_error_string_hides_a_token_raised_by_the_client PASSED [ 46%]
tests/test_config.py::test_missing_env_file PASSED                       [ 48%]
tests/test_config.py::test_empty_token PASSED                            [ 51%]
tests/test_config.py::test_placeholder_token_is_refused PASSED           [ 53%]
tests/test_config.py::test_token_comes_from_dotenv_not_the_environment PASSED [ 55%]
tests/test_config.py::test_quoted_token PASSED                           [ 57%]
tests/test_config.py::test_default_cache_path_is_under_data PASSED       [ 59%]
tests/test_git_hygiene.py::test_env_file_is_not_tracked PASSED           [ 61%]
tests/test_git_hygiene.py::test_spec_path_is_lowercase_docs PASSED       [ 63%]
tests/test_git_hygiene.py::test_ds_store_is_ignored PASSED               [ 65%]
tests/test_github.py::test_conditional_get_uses_cached_body_on_304 PASSED [ 67%]
tests/test_github.py::test_missing_etag_does_not_send_if_none_match PASSED [ 69%]
tests/test_github.py::test_429_retry_after_backs_off_then_fails PASSED   [ 71%]
tests/test_github.py::test_403_uses_reset_when_quota_is_exhausted PASSED [ 73%]
tests/test_github.py::test_403_without_rate_headers_uses_default_backoff PASSED [ 75%]
tests/test_github.py::test_retry_after_http_date PASSED                  [ 77%]
tests/test_github.py::test_retry_after_is_capped PASSED                  [ 79%]
tests/test_github.py::test_response_that_echoes_the_token_is_not_cached_or_returned PASSED [ 81%]
tests/test_github.py::test_request_exception_redacts_the_token PASSED    [ 83%]
tests/test_github.py::test_http_500_does_not_include_request_headers PASSED [ 85%]
tests/test_github.py::test_invalid_json_is_a_github_error PASSED         [ 87%]
tests/test_github.py::test_304_without_a_cached_body_fails PASSED        [ 89%]
tests/test_github.py::test_poisoned_cache_row_is_removed PASSED          [ 91%]
tests/test_github.py::test_redirects_are_not_followed PASSED             [ 93%]
tests/test_github.py::test_client_sends_bearer_token_without_logging_it PASSED [ 95%]
tests/test_github.py::test_build_http_client_does_not_follow_redirects_or_trust_env PASSED [ 97%]
tests/test_github.py::test_dotdot_segment_is_rejected PASSED             [100%]

============================== 49 passed in 0.31s ==============================
```

`GITHUB_TOKEN` in `.env` was present, so the live calls ran. The token was not printed. A byte scan of the CLI output and `data/github_cache.sqlite` found no copy of the token.

`.venv/bin/forge check pydantic/pydantic` (exit 0)

```
accepted pydantic/pydantic spdx=MIT
```

`.venv/bin/forge check torvalds/linux` (exit 1)

```
refused torvalds/linux reason=not_on_allowlist
```

That refusal did not call the API. Allowlist membership is checked first.

The other allowlisted repos, same command, all exit 0:

```
accepted psf/requests spdx=Apache-2.0
accepted pallets/click spdx=BSD-3-Clause
accepted encode/httpx spdx=BSD-3-Clause
```

Python was 3.11.14, arm64. `ruff` is a Mach-O arm64 executable and `pydantic_core` is an arm64 shared library. Nothing needed `--platform linux/amd64`.

Bugs found and fixed:
- Typer 0.29 turns a one-command app into the command itself, so `forge check pydantic/pydantic` treated `check` as the repo name. A callback keeps `check` as a subcommand.
- The `GitHubClient` return annotation was evaluated while the class was still being defined and raised `NameError`. Annotations are now deferred.
- Redacting `Authorization: Bearer <token>` in two passes left a messy string. One pattern now covers the whole header value.
- A license field could carry the token only after JSON decoding, so the raw body check would miss it. Every CLI line is redacted before it is printed.
- If opening the SQLite file failed, the HTTP client created by this object was left open. It is closed on that path.

Files changed:
`.gitignore`, `docs/MENTOR.md`, `docs/PROGRESS.md`, `docs/SPEC.md` (rename from `Docs/`), `pyproject.toml`, `forge/__init__.py`, `forge/__main__.py`, `forge/allowlist.py`, `forge/allowlist.yaml`, `forge/check.py`, `forge/cli.py`, `forge/config.py`, `forge/errors.py`, `forge/github.py`, `forge/models.py`, `tests/__init__.py`, `tests/conftest.py`, `tests/fakes.py`, `tests/test_allowlist.py`, `tests/test_check.py`, `tests/test_cli.py`, `tests/test_config.py`, `tests/test_git_hygiene.py`, `tests/test_github.py`.

Decisions and open questions:
The allowlist file is a small fixed shape (`repos:` plus `- owner/name`) parsed without PyYAML, because PyYAML was not in the dependency list. Comparison is case-insensitive. SPDX ids are compared exactly, so `mit` is refused. Null and blank licenses use `license_missing`. `NOASSERTION` has its own code. Other SPDX ids, including `BSD`, `BSD-4-Clause`, and `0BSD`, use `license_not_allowed`. The HTTP client does not follow redirects and does not read proxy or netrc settings (`trust_env=False`), so the token is not sent to another host. Backoff waits once and then fails. It does not retry the request. A `Retry-After` or reset longer than 60 seconds is capped; the error text includes the uncapped request. The cache file mode is `0600`. A pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 2: PR fetcher and filters, funnel report with rejection reasons. Waiting for "next".

## Stage 2: PR fetcher, filters, and funnel report (commit 879c231127726ff891c797678e633fbe99ccf542)

What was built:
`forge funnel owner/name --limit N` reads closed pull requests from the REST pulls API, follows `Link` headers, and prints how many were considered, one count per rejection reason, and how many were accepted. `--limit` caps how many closed pull requests are read. It does not cap accepts. The search API is not used. Nothing is cloned, and repository code is not run.

The same GitHub client now has a generic GET. It sends ETag / `If-None-Match`, caches a 200 only after the body parses as a JSON object or array, retries a real rate limit, does not follow redirects, and sets `trust_env=False`. `forge check` still uses that client.

What was wrong with the stage 1 client:
- A 403 or 429 slept once and then raised, without making another request. A bare 403, with neither `Retry-After` nor an exhausted rate-limit reset, was labeled `rate_limited`.
- A 200 body was eligible to be stored before it was checked as JSON, so a bad body saved with an ETag could be replayed on the next call.
- The database file was mode `0600`, but the SQLite WAL and SHM sidecars were not.

A real rate limit is now retried up to 3 times. Each wait is capped at 60 seconds. The wait comes from `Retry-After`, or from `X-RateLimit-Reset` when `X-RateLimit-Remaining` is 0. A 403 with neither of those is `github_error`: no sleep, and it is not called `rate_limited`. The tests that required exactly one call, and the test that expected `rate_limited` on a bare 403, were replaced. A new test checks that a non-JSON 200 with an ETag is not served on the next call.

Filter order, first match only. The counts plus accepted equal the pull requests considered:
1. `not_merged` (`merged_at` is null)
2. `revert` (title starts with "revert")
3. `too_many_files` (more than 5)
4. `too_many_lines` (additions + deletions over 300). A missing additions or deletions is `unknown_size`, not 0.
5. `binary` (suffix in `BINARY_SUFFIXES` in `forge/filters.py`, or an explicit binary flag). A missing patch is not enough, because GitHub also omits the patch on large text diffs.
6. `lockfile` (`poetry.lock`, `uv.lock`, `Pipfile.lock`, `pdm.lock`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum`)
7. `docs_only`
8. `missing_source_or_test`. A test file is `test_*.py`, `*_test.py`, `conftest.py`, or any `.py` under `test/` or `tests/`. Any other `.py` file is source.
9. `no_linked_issue`. The body needs a closing keyword (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) immediately before `#n` or `owner/repo#n`.

`GET /repos/{owner}/{repo}/pulls` does not include `changed_files`, `additions`, or `deletions`. When those fields are absent, the same client GETs the pull itself. If `changed_files` is over 5, the file list is not requested. Otherwise the files are fetched and the content filters run. A list item that already has `changed_files` is not fetched again, so an explicit missing line count stays `unknown_size`.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/mypy`

```
Success: no issues found in 22 source files
```

`.venv/bin/pytest`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 90 items

tests/test_allowlist.py ....                                             [  4%]
tests/test_check.py ..............                                       [ 20%]
tests/test_cli.py .........                                              [ 30%]
tests/test_config.py ......                                              [ 36%]
tests/test_filters.py .............................                      [ 68%]
tests/test_funnel.py ....                                                [ 73%]
tests/test_git_hygiene.py ...                                            [ 76%]
tests/test_github.py .....................                               [100%]

============================== 90 passed in 0.41s ==============================
```

Live funnel. The limit was 30 before the command ran. It was not changed after the accept count came back. pydantic/pydantic has far more than 30 closed pull requests, and the run reported that older ones were not read.

`.venv/bin/forge funnel pydantic/pydantic --limit 30` (exit 0)

```
repo pydantic/pydantic
limit 30
considered 30
not_merged 12
revert 0
too_many_files 3
too_many_lines 0
unknown_size 0
binary 0
lockfile 4
docs_only 2
missing_source_or_test 3
no_linked_issue 6
accepted 0
older_prs_cut_off yes
```

12 + 3 + 4 + 2 + 3 + 6 + 0 = 30. The limit did cut off older pull requests.

`.venv/bin/forge funnel torvalds/linux --limit 30` (exit 1)

```
refused torvalds/linux reason=not_on_allowlist
```

That refusal does not call the API. A byte scan of both command outputs and of `data/github_cache.sqlite` found no copy of the token. The cache file is mode `0600`. No `--platform linux/amd64`. Python is 3.11.14 arm64.

Bugs found and fixed:
- The stage 1 client slept and failed on the first 403 or 429, and it called a bare 403 `rate_limited`. A bare 403 is now `github_error` with no sleep. A real rate limit is retried.
- A non-JSON 200 with an ETag was able to be cached and replayed. The body is parsed first, and only a JSON object or array is stored.
- WAL and SHM files were left at the process umask. They are now mode `0600` along with the database file.
- The first live funnel marked 18 merged pull requests `unknown_size` and never fetched files. The list resource omits the size fields, and missing fields were treated as unknown. The pull resource is now loaded on the same client before the size filters. The rerun is the funnel pasted above.

Files changed:
`forge/cli.py`, `forge/filters.py`, `forge/funnel.py`, `forge/github.py`, `forge/models.py`, `tests/test_cli.py`, `tests/test_filters.py`, `tests/test_funnel.py`, `tests/test_github.py`.

Decisions and open questions:
A 429 that has neither `Retry-After` nor an exhausted reset still waits 1 second and is retried, so the retry is not immediate. The user specified the two headers and the 60 second cap, not this fallback. Documentation is a `.md`, `.rst`, `.txt`, `.adoc`, or `.asciidoc` file, a basename of `LICENSE`, `COPYING`, `AUTHORS`, or `CHANGELOG`, or any file under a `doc/` or `docs/` directory. A `.py` file under `docs/` is documentation for `docs_only`; if the pull request also changes a non-doc file, that `.py` still counts as source. A full `issues/123` URL without `#n` does not count as a linked issue. The printed `older_prs_cut_off` line is there so this report can say whether the limit stopped early. The pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 3: patch splitting (source vs tests), linked issue extraction, tests. Waiting for "next".

## Stage 3: patch split and linked issue (commit e1c001ab33d69eb1477d44920b5dcbbe4802f4aa)

What was built:
`forge split owner/name NUMBER` loads one pull request through the same GitHub client. If the funnel would reject it, the command exits 1 and prints that reason. Files are not fetched when an early reason already applies. An accepted pull request is split into two unified diffs (`diff --git`, `---`, and `+++`). Source files go in the solution patch. Test files go in the test patch, using the same definitions as the funnel. A renamed file uses `status` and `previous_filename` when GitHub sends them. A file that is neither source nor test is named and left out of both patches. A missing patch on a source or test file is an error, not an empty diff. The first closing reference in the body (`#N`, `owner/repo#N`, or `https://github.com/owner/repo/issues/N`) is fetched with that same client. `#N` means the pull request's own repository. The issue number, URL, title, and body are kept.

What was wrong with the stage 2 filters:
- A closing keyword immediately followed by `https://github.com/owner/repo/issues/N` was not a linked issue. The check only allowed `#N` and `owner/repo#N`.
- A revert was only a title that starts with "revert". A body containing `This reverts commit` was missed.

No other filter changed. A keyword and a number in different sentences still do not link. `Since #13714` is not a closing link.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/mypy`

```
Success: no issues found in 24 source files
```

`.venv/bin/pytest`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 103 items

tests/test_allowlist.py ....                                             [  3%]
tests/test_check.py ..............                                       [ 17%]
tests/test_cli.py .........                                              [ 26%]
tests/test_config.py ......                                              [ 32%]
tests/test_filters.py ..................................                 [ 65%]
tests/test_funnel.py ....                                                [ 68%]
tests/test_git_hygiene.py ...                                            [ 71%]
tests/test_github.py .....................                               [ 92%]
tests/test_split.py ........                                             [100%]

============================= 103 passed in 0.41s ==============================
```

The limit stayed 30. It was not raised after the counts, and no filter was loosened to produce an accept.

`.venv/bin/forge funnel pydantic/pydantic --limit 30` (exit 0)

```
repo pydantic/pydantic
limit 30
considered 30
not_merged 12
revert 0
too_many_files 3
too_many_lines 0
unknown_size 0
binary 0
lockfile 4
docs_only 2
missing_source_or_test 3
no_linked_issue 6
accepted 0
older_prs_cut_off yes
```

12 + 3 + 4 + 2 + 3 + 6 = 30. Accepted stayed 0, the same as the stage 2 run. Neither new rule moved a pull request into accepted. None of these 30 bodies contains `This reverts commit`. `Since #13714` is still not a closing link, and that pull request stayed `no_linked_issue`. Two bodies do contain a closing keyword immediately before an issues URL, but those pull requests were already rejected earlier (`missing_source_or_test` and `too_many_files`).

The other allowlisted repository, chosen before that command ran, was `psf/requests` at the same limit of 30.

`.venv/bin/forge funnel psf/requests --limit 30` (exit 0)

```
repo psf/requests
limit 30
considered 30
not_merged 15
revert 0
too_many_files 0
too_many_lines 0
unknown_size 0
binary 0
lockfile 0
docs_only 1
missing_source_or_test 14
no_linked_issue 0
accepted 0
older_prs_cut_off yes
```

15 + 1 + 14 = 30. Accepted is 0 here too. Both limits cut off older pull requests. No live split was run. The fixture command is `forge split acme/widgets 7` against a mocked GitHub. The passing CLI test checks this stdout:

```
repo acme/widgets
pull 7
source pkg/widget.py
source pkg/renamed.py
test tests/test_widget.py
other README.md
issue https://github.com/acme/widgets/issues/12
```

`README.md` is not in either patch. `git apply --check` applied both patches in a temporary repository the test created and exited 0. Nothing was cloned, and repository code was not run. The rejected fixture exits 1 with `refused acme/widgets#7 reason=not_merged` and does not request the files URL.

`.venv/bin/forge split torvalds/linux 1` (exit 1)

```
refused torvalds/linux#1 reason=not_on_allowlist
```

That refusal does not call the API. A byte scan of the command outputs and of `data/github_cache.sqlite` found no copy of the token. No `--platform linux/amd64`. Python is 3.11.14 arm64.

Bugs found and fixed:
- The stage 2 closing check dropped a keyword that was immediately followed by an issues URL.
- The stage 2 revert check ignored `This reverts commit` in the body when the title did not start with "revert".

Files changed:
`forge/cli.py`, `forge/filters.py`, `forge/github.py`, `forge/models.py`, `forge/split.py`, `tests/test_filters.py`, `tests/test_split.py`.

Decisions and open questions:
The first closing reference in the body wins. `#N` is an issue in the pull request's repository. `owner/repo#N` and the issues URL name the repository to fetch. The phrase `This reverts commit` is matched exactly and only in the body. A title that merely contains that phrase is not a revert unless the title starts with "revert". An added file uses `--- /dev/null`. A removed file uses `+++ /dev/null`. A path with spaces is quoted. Absolute paths and `..` components are refused. A missing patch on a source or test file is `github_error` and the command exits 2. The pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 4: Docker sandbox runner (image per repo and commit, no network, limits, timeout), with tests for the isolation settings. Waiting for "next".
