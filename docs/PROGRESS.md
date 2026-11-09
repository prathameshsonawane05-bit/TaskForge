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

## Stage 4: Docker sandbox runner (commit bf3e2d69abea1b368ad064fb258f937fe36fdd55)

What was built:
`forge sandbox owner/name SHA --patch FILE --timeout SECONDS -- COMMAND` checks the allowlist and the license before any clone or `docker build`. A repository that is not allowlisted never reaches Docker. The clone is `git clone` under `data/clones/`, which stays gitignored. The host does not run the repository's tests, setup, or any other repository code. The image tag is `taskforge/<owner>/<name>:<full sha>`. The Dockerfile copies the checkout at that commit and does not `RUN` repository code. Building may use the network. The run uses `--network none`, `--memory 512m`, and `--cpus 1`, and the runner kills the container when the timeout expires and then removes it. The default timeout is 60 seconds. The only host mount is the patch file, read-only, at `/patch`. The host checkout, `.env`, and the Docker socket are not mounted. The container filesystem is not `--read-only`, so a later stage can apply a patch inside the container. `GITHUB_TOKEN` is not passed to git, `docker build`, or `docker run`.

The live repository and commit were chosen before any container was started: `pallets/click` at `8abb77a8432e03ed14a95f972b44f905279415a7` (the default-branch HEAD at selection time). `python:3.11-slim` publishes `linux/arm64/v8`, so the build did not use `--platform linux/amd64`. The built image is `Arch=arm64`.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/mypy`

```
Success: no issues found in 26 source files
```

`.venv/bin/pytest`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 111 items

tests/test_allowlist.py ....                                             [  3%]
tests/test_check.py ..............                                       [ 16%]
tests/test_cli.py .........                                              [ 24%]
tests/test_config.py ......                                              [ 29%]
tests/test_filters.py ..................................                 [ 60%]
tests/test_funnel.py ....                                                [ 63%]
tests/test_git_hygiene.py ...                                            [ 66%]
tests/test_github.py .....................                               [ 85%]
tests/test_sandbox.py ........                                           [ 92%]
tests/test_split.py ........                                             [100%]

============================= 111 passed in 0.44s ==============================
```

`docker inspect` on the running container `taskforge-8abb77a8432e-c1ab1f5c`:

```
NetworkMode=none
Memory=536870912
NanoCpus=1000000000
[{"Type":"bind","Source":"/Users/shubhambaviskar/Desktop/TaskForge/data/sandbox/demo.patch","Destination":"/patch","Mode":"","RW":false,"Propagation":"rprivate"}]
```

Memory `536870912` is 512 MiB. `NanoCpus` `1000000000` is 1 CPU. `RW` false is the read-only patch mount. This machine has 4 CPUs and about 5.8 GiB, so both limits are small.

Command inside that container (not the project's pytest):

`docker exec taskforge-8abb77a8432e-c1ab1f5c python -c 'from pathlib import Path; print(2 + 2); print(Path("/repo/pyproject.toml").is_file())'`

```
4
True
```

Exit 0. The checkout is in the image.

The same command through the CLI, after `--` so Typer does not treat `-c` as an option (exit 0):

`.venv/bin/forge sandbox pallets/click 8abb77a8432e03ed14a95f972b44f905279415a7 --patch data/sandbox/demo.patch --timeout 60 -- python -c 'print(2 + 2)'`

```
repo pallets/click
commit 8abb77a8432e03ed14a95f972b44f905279415a7
image taskforge/pallets/click:8abb77a8432e03ed14a95f972b44f905279415a7
exit 0
4
```

Outbound connection inside the container (exit 1):

`docker exec taskforge-8abb77a8432e-c1ab1f5c python -c 'import urllib.request; urllib.request.urlopen("http://example.com", timeout=5)'`

```
urllib.error.URLError: <urlopen error [Errno -3] Temporary failure in name resolution>
```

Write to the mounted patch (exit 1):

`docker exec taskforge-8abb77a8432e-c1ab1f5c python -c 'open("/patch", "a").write("x\n")'`

```
OSError: [Errno 30] Read-only file system: '/patch'
```

Timeout demo, override 3 seconds (exit 2):

`.venv/bin/forge sandbox pallets/click 8abb77a8432e03ed14a95f972b44f905279415a7 --patch data/sandbox/demo.patch --timeout 3 sleep 30`

```
error reason=sandbox_timeout Sandbox run timed out after 3 seconds. Removed container taskforge-8abb77a8432e-e1082ee5.
```

`docker ps` and `docker ps -a` filtered by that name, and by `taskforge-`, listed no containers.

`.venv/bin/forge sandbox torvalds/linux 8abb77a8432e03ed14a95f972b44f905279415a7 --patch /tmp/does-not-exist true` (exit 1)

```
refused torvalds/linux reason=not_on_allowlist
```

That refusal returned without cloning or calling Docker. A byte scan of the command outputs found no copy of the token. No `--platform linux/amd64`. Python is 3.11.14 arm64. Fail-to-pass and pass-to-pass were not started.

Bugs found and fixed:
None in the live run. The isolation flags the tests require were present on the inspected container.

Files changed:
`forge/cli.py`, `forge/models.py`, `forge/sandbox.py`, `tests/test_sandbox.py`.

Decisions and open questions:
The base image is `python:3.11-slim` because it has an arm64 build and the run only needs `python` and `sleep`. The memory limit is 512 MiB and the CPU limit is 1, both well under this machine. The default timeout is 60 seconds; the sleep demo used 3. Git is invoked with `credential.helper=` and `GIT_TERMINAL_PROMPT=0` so a credential helper cannot attach the token. The image tag uses the full SHA, and a unit test uses two SHAs that share a 12-character prefix. Typer treats a leading `-c` as an option, so a `python -c` command is passed after `--`. The pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 5: compute fail-to-pass and pass-to-pass by running tests before and after the solution. Waiting for "next".

## Stage 5: Compute fail-to-pass and pass-to-pass (commit 491b65c4391bd729e177a9dd74b1078e9d412fc5)

What was built:
`forge sandbox` used to store the container status, print `exit N`, and then return, so the process status was 0. The container's stderr was not printed. A finished run now exits with the container status, and stderr is printed as well as stdout. A timeout is still process exit 2, and that path prints `reason=sandbox_timeout` rather than `exit 2`. `tests/test_sandbox.py::test_cli_process_status_is_the_container_status` fails if a container exit of 1 becomes a process exit of 0.

`forge outcomes` classifies one pair of pytest runs. It is not a validation gate, and stage 6 was not started. The stage 4 Dockerfile still has no `RUN`. A separate eval Dockerfile installs git and pytest while the image is built. The build may use the network. The run does not. The only host mount is one read-only directory of patches at `/patches`. The checkout, `.env`, and the Docker socket are not mounted. Network stays `none`, memory stays `512m`, and CPUs stay 1. No token is passed to git or Docker. Patches are applied only inside the container, on the parent commit, where the solution is not in the tree. `git apply --check` of the solution has to succeed before the first pytest. The same container then runs pytest with the test patch only, applies the solution, and runs pytest again. Only `PASSED` and `XPASS` count as a pass. `SKIPPED` is not a pass. Each id is fail-to-pass, pass-to-pass, still failing, or a regression, and those four buckets sum to the tests that ran. A unit test feeds known before and after statuses, including a skip that stays a skip, and fails if that skip is counted as a pass.

The live fixture is a small project written for this stage (`local/widget`). It is not someone else's benchmark task. The allowlisted funnel was chosen before it ran: `encode/httpx` at limit 30. It accepted nothing, so no filter was changed and no pull request was run.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/mypy`

```
Success: no issues found in 29 source files
```

`.venv/bin/pytest`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 117 items

tests/test_allowlist.py ....                                             [  3%]
tests/test_check.py ..............                                       [ 15%]
tests/test_cli.py .........                                              [ 23%]
tests/test_config.py ......                                              [ 28%]
tests/test_filters.py ..................................                 [ 57%]
tests/test_funnel.py ....                                                [ 60%]
tests/test_git_hygiene.py ...                                            [ 63%]
tests/test_github.py .....................                               [ 81%]
tests/test_outcomes.py ....                                              [ 84%]
tests/test_sandbox.py ..........                                         [ 93%]
tests/test_split.py ........                                             [100%]

============================= 117 passed in 0.57s ==============================
```

`.venv/bin/forge funnel encode/httpx --limit 30` (process status 0)

```
repo encode/httpx
limit 30
considered 30
not_merged 24
revert 0
too_many_files 0
too_many_lines 0
unknown_size 0
binary 0
lockfile 0
docs_only 2
missing_source_or_test 4
no_linked_issue 0
accepted 0
older_prs_cut_off yes
```

Accepted was 0. The filters were left as they were.

`.venv/bin/forge sandbox pallets/click 8abb77a8432e03ed14a95f972b44f905279415a7 --patch data/sandbox/demo.patch -- python -c 'import sys; print("stdout-line"); print("stderr-line", file=sys.stderr); raise SystemExit(1)'`

Process status 1. Stdout:

```
repo pallets/click
commit 8abb77a8432e03ed14a95f972b44f905279415a7
image taskforge/pallets/click:8abb77a8432e03ed14a95f972b44f905279415a7
exit 1
stdout-line
```

Stderr:

```
stderr-line
```

That command went through the CLI, not `docker exec`.

`.venv/bin/forge outcomes` (process status 0). The process status is 0 because the wrapper finished and printed the classification. It is not a gate. Both pytest runs exited 1. The run used 512m and was not killed, so the limit was not raised. `docker image inspect` reported `Arch=arm64 Os=linux`. No `--platform linux/amd64`. `docker ps -a` filtered by `taskforge-` listed no containers.

```
repo local/widget
commit 225c00ed99d58023d3c97ec380d87547ab353bd4
image taskforge/local/widget:225c00ed99d58023d3c97ec380d87547ab353bd4
memory 512m
container_exit 0
before_pytest 1
after_pytest 1
solution_absent yes
note A single run is not a validation gate.
fail_to_pass 1
  tests/test_new.py::test_add
pass_to_pass 1
  tests/test_keep.py::test_truth
still_failing 2
  tests/test_new.py::test_skipped
  tests/test_still.py::test_still_broken
regression 1
  tests/test_answer.py::test_answer
total 5
--- before ---
============================= test session starts ==============================
platform linux -- Python 3.11.18, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
rootdir: /repo
collecting ... collected 5 items

tests/test_answer.py::test_answer PASSED                                 [ 20%]
tests/test_keep.py::test_truth PASSED                                    [ 40%]
tests/test_new.py::test_add FAILED                                       [ 60%]
tests/test_new.py::test_skipped SKIPPED (not a pass)                     [ 80%]
tests/test_still.py::test_still_broken FAILED                            [100%]

=================================== FAILURES ===================================
E   assert 0 == 2
     +  where 0 = add(1, 1)
/repo/tests/test_new.py:7: assert 0 == 2
E   RuntimeError: still broken
/repo/widget.py:10: RuntimeError: still broken
=========================== short test summary info ============================
FAILED tests/test_new.py::test_add - assert 0 == 2
FAILED tests/test_still.py::test_still_broken - RuntimeError: still broken
==================== 2 failed, 2 passed, 1 skipped in 0.01s ====================
--- before stderr ---

--- after ---
============================= test session starts ==============================
platform linux -- Python 3.11.18, pytest-9.2.0, pluggy-1.7.0 -- /usr/local/bin/python
rootdir: /repo
collecting ... collected 5 items

tests/test_answer.py::test_answer FAILED                                 [ 20%]
tests/test_keep.py::test_truth PASSED                                    [ 40%]
tests/test_new.py::test_add PASSED                                       [ 60%]
tests/test_new.py::test_skipped SKIPPED (not a pass)                     [ 80%]
tests/test_still.py::test_still_broken FAILED                            [100%]

=================================== FAILURES ===================================
E   assert 2 == 1
     +  where 2 = answer()
/repo/tests/test_answer.py:5: assert 2 == 1
E   RuntimeError: still broken
/repo/widget.py:10: RuntimeError: still broken
=========================== short test summary info ============================
FAILED tests/test_answer.py::test_answer - assert 2 == 1
FAILED tests/test_still.py::test_still_broken - RuntimeError: still broken
==================== 2 failed, 2 passed, 1 skipped in 0.01s ====================
--- after stderr ---
```

`test_add` fails and then passes. `test_truth` passes both times. `test_skipped` is skipped both times and is still failing, not pass-to-pass. `test_still_broken` fails both times. `test_answer` passes and then fails. 1 + 1 + 2 + 1 = 5. The first run shows `add(1, 1)` returning 0, so the solution was not already in the tree. A byte scan of these outputs found no copy of the token. Python on the host is 3.11.14 arm64.

Bugs found and fixed:
- `forge sandbox` printed the container status and then returned success. The process status is now that container status, and stderr is printed. A timeout is still process exit 2.

Files changed:
`forge/cli.py`, `forge/sandbox.py`, `forge/outcomes.py`, `forge/widget_fixture.py`, `tests/test_sandbox.py`, `tests/test_outcomes.py`.

Decisions and open questions:
The funnel repo and limit were `encode/httpx` and 30, chosen before the run. Accepted was 0, so the filters were not changed and no allowlisted pull request was executed. The memory limit stayed 512m because the run was not OOM-killed. The eval image is separate from the stage 4 image so that Dockerfile still has no `RUN`. `forge outcomes` exits 0 when the classification has been printed; `before_pytest` and `after_pytest` are the pytest statuses. One pair of runs is not a validation gate. The pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 6: validation gates V1 to V5 with reject reasons. Waiting for "next".

## Stage 6: Validation gates V1 to V5 (commit 6168e94f64254fef939534836f42364dee8524b8)

What was built:
The classifier treated every status other than pass as a failure. A skip therefore landed in still failing, and a skip that later passed landed in fail-to-pass. A skip in either run is now its own bucket. Fail-to-pass, pass-to-pass, still failing, regression, and skipped sum to the tests that ran.

`forge gates widget` and `forge gates counter` run the gates in order and stop at the first failure. The reasons are `build_failed`, `no_failure_before`, `no_fail_to_pass`, `regression`, `flaky`, and `too_slow`. The spec's check that every fail-to-pass test passed was not implemented, because those ids would be taken from the same run and the check could not fail. `no_fail_to_pass` rejects a run where nothing went from fail to pass. `regression` rejects a test that passed before and did not pass after. A skip is not a failure, so it does not satisfy `no_failure_before`. V6, V7, and V8 were not started.

The widget fixture was not edited. It still has the regression, and the gates reject it for that reason after one container. The counter fixture is a second small project written for this stage: one fail-to-pass test, one pass-to-pass test, no skip, no regression, and no test that fails both times. Its image is built once at the parent commit. Three fresh containers then each apply the patches from that parent. The runtime limit was written down before those runs: the sum of the three container times is too slow when it is over 30 seconds. Local fixtures are not allowlisted. A GitHub repository was not cloned.

Commands run and their real output:

`.venv/bin/ruff check forge tests`

```
All checks passed!
```

`.venv/bin/mypy`

```
Success: no issues found in 31 source files
```

`.venv/bin/pytest`

```
============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-9.2.0, pluggy-1.7.0
rootdir: /Users/shubhambaviskar/Desktop/TaskForge
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.16.0
collected 131 items

tests/test_allowlist.py ....                                             [  3%]
tests/test_check.py ..............                                       [ 13%]
tests/test_cli.py .........                                              [ 20%]
tests/test_config.py ......                                              [ 25%]
tests/test_filters.py ..................................                 [ 51%]
tests/test_funnel.py ....                                                [ 54%]
tests/test_gates.py .............                                        [ 64%]
tests/test_git_hygiene.py ...                                            [ 66%]
tests/test_github.py .....................                               [ 82%]
tests/test_outcomes.py .....                                             [ 86%]
tests/test_sandbox.py ..........                                         [ 93%]
tests/test_split.py ........                                             [100%]

============================= 131 passed in 0.97s ==============================
```

`.venv/bin/forge funnel pallets/click --limit 30` (process status 0). The repo and the limit were chosen before this run.

```
repo pallets/click
limit 30
considered 30
not_merged 10
revert 0
too_many_files 5
too_many_lines 0
unknown_size 0
binary 0
lockfile 1
docs_only 4
missing_source_or_test 4
no_linked_issue 6
accepted 0
older_prs_cut_off yes
```

Accepted was 0. The filters were left as they were, and no pull request was run.

`.venv/bin/forge gates widget` (process status 1)

```
repo local/widget
commit 0542acce42f31b5867250f801a3411f25467cfe0
image taskforge/local/widget:0542acce42f31b5867250f801a3411f25467cfe0
memory 512m
limit_seconds 30
runs 1
rejected regression
run 1 elapsed 2.446
run 1 before_pytest 1
run 1 after_pytest 1
run 1 fail_to_pass 1
  tests/test_new.py::test_add
run 1 pass_to_pass 1
  tests/test_keep.py::test_truth
run 1 still_failing 1
  tests/test_still.py::test_still_broken
run 1 regression 1
  tests/test_answer.py::test_answer
run 1 skipped 1
  tests/test_new.py::test_skipped
total_elapsed 2.446
```

The skipped test is in `skipped`, not in still failing. The gates stopped at `regression`, so the three-container check did not run.

`.venv/bin/forge gates counter` (process status 0)

```
repo local/counter
commit 52f7ff58eb4a705e09c0edfcd87f82c4612508ae
image taskforge/local/counter:52f7ff58eb4a705e09c0edfcd87f82c4612508ae
memory 512m
limit_seconds 30
runs 3
rejected none
run 1 elapsed 1.154
run 1 before_pytest 1
run 1 after_pytest 0
run 1 fail_to_pass 1
  tests/test_value.py::test_value
run 1 pass_to_pass 1
  tests/test_keep.py::test_truth
run 1 still_failing 0
run 1 regression 0
run 1 skipped 0
run 2 elapsed 0.827
run 2 before_pytest 1
run 2 after_pytest 0
run 2 fail_to_pass 1
  tests/test_value.py::test_value
run 2 pass_to_pass 1
  tests/test_keep.py::test_truth
run 2 still_failing 0
run 2 regression 0
run 2 skipped 0
run 3 elapsed 1.302
run 3 before_pytest 1
run 3 after_pytest 0
run 3 fail_to_pass 1
  tests/test_value.py::test_value
run 3 pass_to_pass 1
  tests/test_keep.py::test_truth
run 3 still_failing 0
run 3 regression 0
run 3 skipped 0
total_elapsed 3.283
note This project was written to pass, so three matching runs are weak evidence about real flakes.
```

The three classifications and pytest statuses match. The total time is 3.283 seconds, under the 30 second limit that was chosen before the run. This project was written to pass, so three matching runs are weak evidence about real flakes. `docker image inspect` reported `Arch=arm64 Os=linux`. No `--platform linux/amd64`. The runs stayed at 512m and 1 CPU, with the network off and one read-only patch directory. No run was OOM-killed, so the memory limit was not raised. `docker ps -a` filtered by `taskforge-` listed no containers. A byte scan of these outputs found no copy of the token. Python on the host is 3.11.14 arm64.

Bugs found and fixed:
- A skip was classified as still failing, and a skip that later passed was classified as fail-to-pass. Skips now have their own bucket.

Files changed:
`forge/cli.py`, `forge/gates.py`, `forge/outcomes.py`, `forge/widget_fixture.py`, `tests/test_gates.py`, `tests/test_outcomes.py`.

Decisions and open questions:
The funnel repo and limit were `pallets/click` and 30, chosen before the run. Accepted was 0, so the filters were not changed and no allowlisted pull request was executed. The three-run limit is 30 seconds and was written down before `forge gates counter`. The widget regression was left in place so the fixture is rejected. The counter fixture was written to pass the gates. One pair of pytest runs is still not a validation gate. The pre-existing uncommitted edit to `AGENTS.md` was left unstaged.

Next stage:
Stage 7: quality checks V6 to V8, instruction builder, and task packager. Waiting for "next".
