# TaskForge

TaskForge reads merged pull requests from allowlisted public Python repositories and turns a small one into a task: an instruction, a hidden test patch, and a reference solution. The only committed task is `output/sample/local-counter`.

## Setup

Python 3.11 or newer. CI runs 3.11 and 3.12. From a fresh clone:

```bash
uv venv --python 3.11 --seed .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
```

`source .venv/bin/activate` works in bash and zsh. After that, `forge`, `ruff`, `mypy`, and `pytest` are on `PATH`. `--seed` installs pip into the environment. Without it, `python -m pip` is missing. `requirements-dev.txt` is the locked development set. The second command installs this project without resolving the lower bounds in `pyproject.toml`.

On a normal CPython, where `python3.11 -m venv` can find the standard library, use this block instead:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-deps -e .
```

To refresh the lock after a bound changes:

```bash
uv lock --upgrade
uv export --extra dev --no-emit-project --frozen --output-file requirements-dev.txt
```

A refresh is its own commit. Do not edit a pin in `uv.lock` or `requirements-dev.txt` by hand.

## Token

Save the token with:

```bash
bash scripts/set_token.sh
```

The script prompts once and writes `GITHUB_TOKEN` to `.env`. The token stays in `.env`. Git ignores that file. TaskForge reads the token from `.env` only, not from the shell. Public-repository read access is enough.

A repository must be listed in `forge/allowlist.yaml`, and the GitHub API must report SPDX `MIT`, `Apache-2.0`, `BSD-2-Clause`, or `BSD-3-Clause`. Membership is not a license approval. The current names are `pydantic/pydantic`, `psf/requests`, `pallets/click`, `encode/httpx`, and `pallets/itsdangerous`. This repository has no chosen license. An upstream task keeps the SPDX id of its repository.

## Commands

```bash
forge check owner/name
forge funnel owner/name --limit 30
forge report owner/name --limit 30
forge split owner/name NUMBER
forge sandbox owner/name FULL_SHA --patch path/to.patch -- python -c 'print(1)'
forge outcomes
forge gates counter
forge package counter
forge package-pull owner/name NUMBER
```

`forge check` accepts or refuses one repository. `forge funnel` reads that many closed pull requests and prints one count per rejection reason. The limit caps how many pull requests are read. It does not cap how many are accepted. `forge report` runs that same funnel and writes `output/reports/<owner>-<name>-<limit>.json` and the matching Markdown file, then prints both paths. `forge split` prints the source names, the test names, the supporting names, the unsupported names, and the issue URL for one pull request number. It does not write those files. `forge sandbox` runs the command after `--` in a container at that 40-character commit. `forge outcomes` classifies the local widget fixture once. `forge gates` runs the validation gates on `widget` or `counter`. `forge package` writes a local fixture task only when those gates accept. `forge package-pull` checks the allowlist and the SPDX license, then applies the current filters. A filter rejection writes nothing. A file with no patch, a binary file, or a lockfile writes nothing and exits 1 with `unsupported_file`. That reason is not a funnel filter. An accepted pull request is packaged under `output/` only when gates V1 through V5 accept and V6 through V8 are clean.

`forge check`, `forge funnel`, `forge report`, `forge split`, and `forge package-pull` need a token. `forge sandbox`, `forge outcomes`, `forge gates`, `forge package`, and `forge package-pull` need Docker.

## Path

A packaged pull request follows this path. The allowlist and the SPDX check accept the repository. Closed pull requests are then read, newest created first. The filters keep or reject each one. The split puts Python tests in the test patch, and other Python files and riding text files in the solution patch. The Docker trial runs the tests in a baseline container and again in a solved container. Gates V1 through V5 accept the build, a failure before the solution, a fail-to-pass result, three agreeing repeats, and the 30 second limit. Quality checks V6 through V8 then accept the failure kind, the instruction, and the hidden tests. Publish writes the package only after that new tree is complete.

## Walkthrough

These two commands use the local counter. They need Docker. They do not need a token.

```bash
forge gates counter
forge package counter
```

## Committed task

`output/sample/local-counter` contains `instruction.md`, `solution/solution.patch`, `tests/test.patch`, `tests/config.json`, `task.json`, and `ATTRIBUTION.md`. `task.json` names the repository `local/counter`. Its license, pull-request URL, and issue URL are `no upstream`. The short funnel report beside these docs, `docs/funnel-report.md`, uses those `no upstream` values. It is not a GitHub window.

## Checks

These three do not need a token or Docker:

```bash
ruff check forge tests
mypy
pytest
```

## Docker

`forge sandbox`, `forge outcomes`, `forge gates`, `forge package`, and `forge package-pull` need Docker. The Docker daemon must be able to mount the clone. A Docker daemon which cannot mount `/tmp` cannot use a clone under `/tmp`. Repository code runs only inside that sandbox. The container has no network, 512 MB of memory, one CPU, a timeout, and a read-only patch mount. The host does not run the repository's tests or setup. The eval image may use the network to install the static `project.dependencies` and `build-system.requires` from `pyproject.toml`. Version specifiers, extras, and environment markers are kept, and each requirement is quoted in that `RUN`. A direct URL, a VCS requirement, or a requirement containing a newline is a sandbox error. After the checkout is copied, `pip install -e .` has no network. A checkout with no `pyproject.toml` and no `setup.py`, including the widget and counter fixtures, keeps the git and pytest image. The checkout installer still runs as root during the build.

## Limitations

- Python and pytest only.
- Task quality depends on the pull request and the issue text.
- Public repositories may already be in model training data.
- This is not a security audit.
- Difficulty is only an estimate. Tasks are not validated against real agents.
- Three windows accepted none, so precision and recall are undefined: `psf/requests`, `pallets/itsdangerous`, and `encode/httpx`.
- The click window was 4/4 and was labeled by the filter author.
- This stage committed `pallets/click` 3781 and 3769. 3858 was not packaged because the gate rejected it as too slow. 3739 was not packaged because V7 leaked one solution line. Nine tests still failed and twenty were skipped. V6 recorded `other` on the pulls that reached quality. An agent command ran once. It was not logged in, it produced no edit, and it did not solve `pallets/click` 3781.
- The committed tasks are `output/pallets-click-3781`, `output/pallets-click-3769`, and `output/sample/local-counter`. The sample has no upstream repository, and it was written to pass the gates.
