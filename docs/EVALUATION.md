# Evaluation v1

This is version 1 of the labeled evaluation. It is not an independent evaluation. I wrote the pipeline, including the filters this note later compares against. A perfect score would not be evidence that the filters are right.

The held-out repository was not started. The local counter fixture is not a candidate.

## Repo and limit

Chosen before the funnel run: `psf/requests`, 50 closed pull requests. The funnel has not been run. Labels below, once written, are not to be changed after a funnel reason is known.

## Rubric

A merged pull request is a fair small task when every clause below holds. I read the title, the body, and the file list. I stop at the first clause that fails. That clause is the label. An unmerged pull request is not a candidate.

1. Not a revert. The title, ignoring case and leading space, does not start with "revert". The body does not contain the sentence "This reverts commit".
2. At most five files. I count the files in the file list.
3. A known size of at most 300 changed lines. I add each file's additions and deletions. If any file has no addition count or no deletion count, the size is unknown and the pull is not a fair small task. More than 300 changed lines is too big.
4. No binary file. A file is binary when the file list marks it binary, or when its suffix is one of: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.ico`, `.bmp`, `.pdf`, `.zip`, `.gz`, `.tgz`, `.bz2`, `.xz`, `.7z`, `.rar`, `.tar`, `.wasm`, `.so`, `.dylib`, `.dll`, `.exe`, `.bin`, `.class`, `.jar`, `.pyc`, `.pyo`, `.whl`, `.woff`, `.woff2`, `.ttf`, `.eot`, `.otf`, `.mp3`, `.mp4`, `.mov`, `.avi`, `.webm`, `.sqlite`, `.db`, `.pickle`, `.pkl`. A missing patch is not enough to call a file binary.
5. No lockfile. The basename is one of `poetry.lock`, `uv.lock`, `Pipfile.lock`, `pdm.lock`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum`.
6. Not documentation only. Documentation is a file whose suffix is `.md`, `.rst`, `.txt`, `.adoc`, or `.asciidoc`, whose basename is `license`, `copying`, `authors`, or `changelog`, or which sits in a `doc` or `docs` directory. If every file is documentation, this is not a code task.
7. At least one Python source file and at least one Python test file. A test file is a `.py` file named `conftest.py`, named `test_*.py` or `*_test.py`, or living in a `test` or `tests` directory. A source file is any other `.py` file.
8. The body links an issue. A closing keyword (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`, `resolved`) sits immediately before `#N`, `owner/repo#N`, or `https://github.com/owner/repo/issues/N`. A colon and extra spaces may sit between the keyword and the reference. `Since #13714` is not a link. A keyword and a number in different sentences do not link.

If every clause holds, the label is accept.

## Window

The window is the 50 most recently closed pull requests of `psf/requests`. It contains 19 merged pull requests. That count is under 20, so no further page was fetched. Every merged pull request in the window is labeled. The funnel had not been run when these labels were written.

## Labels

Each label is the first rubric clause that fails. The funnel reason column was empty when these labels were written. It was filled afterwards. No label was changed.

| Pull | Label | Rubric clause | Funnel reason |
| --- | --- | --- | --- |
| 7636 | reject | At least one Python source file and one Python test file. The file list is two workflow YAML files. | missing_source_or_test |
| 7628 | reject | At least one Python source file and one Python test file. The file list is one workflow YAML file. | missing_source_or_test |
| 7616 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7609 | reject | At least one Python source file and one Python test file. The file list is `lock-issues.yml`. The body cites `dessant/lock-threads#55` without a closing keyword, which was not reached. | missing_source_or_test |
| 7608 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7606 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7603 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7598 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7597 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7596 | reject | At least one Python source file and one Python test file. The file list is five workflow YAML files. | missing_source_or_test |
| 7591 | reject | At least one Python source file and one Python test file. The file list is one workflow YAML file. | missing_source_or_test |
| 7590 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7576 | reject | Not documentation only. The only file is `.github/CONTRIBUTING.md`. | docs_only |
| 7562 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7561 | reject | At least one Python source file and one Python test file. The file list is four workflow YAML files. | missing_source_or_test |
| 7551 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |
| 7540 | reject | At most five files. The file list has six workflow YAML files. | too_many_files |
| 7539 | reject | At least one Python source file and one Python test file. The file list is `dependabot.yml` and `lint.yml`. The body says "from #7536" without a closing keyword, which was not reached. | missing_source_or_test |
| 7536 | reject | At least one Python source file and one Python test file. The file list is `.pre-commit-config.yaml`. | missing_source_or_test |

## Same rule as the code

Every clause above is the same rule as `forge/filters.py`. I wrote that module, then wrote the rubric in the same words. That is why the labels and the funnel reasons name the same failure.

- Clause 1 is the revert check: a title matching `^\s*revert` with case ignored, or a body containing `This reverts commit`.
- Clause 2 is the five-file cap. I counted the file list. The code applies that cap to `changed_files` on the pull, then again to the length of the file list.
- Clause 3 is the 300-line cap, with a missing count counted as unknown. I summed additions and deletions from the file list. The code uses `additions` and `deletions` on the pull.
- Clause 4 is the binary check: the same suffix list, or an explicit binary flag. A missing patch is not binary.
- Clause 5 is the same lockfile basename list.
- Clause 6 is the same documentation rule: those suffixes, those basenames, or a `doc` or `docs` directory.
- Clause 7 is the same source and test rule.
- Clause 8 is the same closing-keyword rule. `Since #13714` does not match. A keyword and a number in different sentences do not match.

On this window the two size inputs agreed. For every candidate, `changed_files` equaled the file-list length, and the pull's additions plus deletions equaled the sum of the file-list counts. That agreement did not require a label change. No filter was changed.

## Confusion matrix

The funnel accepted none of these 19 candidates. I accepted none.

|  | Funnel accept | Funnel reject |
| --- | --- | --- |
| Label accept | true accept 0 | false reject 0 |
| Label reject | false accept 0 | true reject 19 |

Precision is true accepts divided by the number the funnel accepted. The funnel accepted none, so precision is undefined.

Recall is true accepts divided by the number I accepted. I accepted none, so recall is undefined.

The 31 unmerged pull requests in the window were not candidates. The funnel counted them as `not_merged`. The local counter fixture was not a candidate.

A perfect score is not evidence. This is not an independent evaluation. I wrote the pipeline, and the rubric restates its rules. Agreement here does not show that the accept decision is right. No filter was changed after these reasons were known.

## Held-out

Chosen now, before this funnel: `pallets/itsdangerous`, 40 closed pull requests. The GitHub API reported SPDX `BSD-3-Clause`, which is one of the allowed ids, and the repository was added to the allowlist only after that report. The rubric above was not changed. `forge/filters.py` was not opened while these labels were written. These labels were written before the funnel. The funnel reason column was blank in that commit. No label was changed after the funnel reason was known.

The window contains 14 merged pull requests. That count is under 20, so no further page was fetched. Every merged pull request in the window is labeled. An unmerged pull request is not a candidate. The local counter fixture is not a candidate.

| Pull | Label | Rubric clause | Funnel reason |
| --- | --- | --- | --- |
| 408 | reject | At least one Python source file and one Python test file. The only file is `.github/workflows/publish.yaml`. | missing_source_or_test |
| 407 | reject | At most five files. The file list has eight files. | too_many_files |
| 406 | reject | At least one Python source file and one Python test file. The Python file is `src/itsdangerous/__init__.py`, and the file list has no test file. | missing_source_or_test |
| 405 | reject | At most five files. The file list has six files. | too_many_files |
| 404 | reject | At most five files. The file list has twenty-two files. | too_many_files |
| 401 | reject | Not documentation only. The files are `CONTRIBUTING.rst` and `README.md`. | docs_only |
| 396 | reject | At least one Python source file and one Python test file. The only file is `.pre-commit-config.yaml`. | missing_source_or_test |
| 395 | reject | At least one Python source file and one Python test file. The files are two workflow YAML files. | missing_source_or_test |
| 393 | reject | At least one Python source file and one Python test file. The only file is `.pre-commit-config.yaml`. | missing_source_or_test |
| 392 | reject | At least one Python source file and one Python test file. The files are two workflow YAML files. | missing_source_or_test |
| 391 | reject | Not documentation only. Every file is a `.txt` requirements file. | docs_only |
| 390 | reject | At least one Python source file and one Python test file. The only file is `.pre-commit-config.yaml`. | missing_source_or_test |
| 388 | reject | At least one Python source file and one Python test file. The files are two workflow YAML files. | missing_source_or_test |
| 387 | reject | Not documentation only. Every file is a `.txt` requirements file. | docs_only |

The funnel accepted none of these 14 candidates. I accepted none. For every candidate, `changed_files` equaled the file-list length, and the pull's additions plus deletions equaled the file-list sum.

|  | Funnel accept | Funnel reject |
| --- | --- | --- |
| Label accept | true accept 0 | false reject 0 |
| Label reject | false accept 0 | true reject 14 |

Precision is true accepts divided by the number the funnel accepted. The funnel accepted none, so precision is undefined.

Recall is true accepts divided by the number I accepted. I accepted none, so recall is undefined.

The 26 unmerged pull requests in the window were not candidates. The funnel counted them as `not_merged`. No filter was changed.

This is not an independent evaluation. I wrote the pipeline, and the rubric in this file restates its rules. I did not open the filter code while labeling this window, and I did not change a label after the funnel. Agreement on an all-reject set is not evidence that an accept would be right.
