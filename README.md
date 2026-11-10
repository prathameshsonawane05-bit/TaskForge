# TaskForge

TaskForge reads merged pull requests from allowlisted public Python repositories and turns a small one into a task: an instruction, a hidden test patch, and a reference solution. The only committed task is `output/sample/local-counter`.

## Setup

Python 3.11 is required. From a fresh clone on this machine:

```bash
uv venv --python 3.11 --seed .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`source .venv/bin/activate` works in bash and zsh. After that, `forge`, `ruff`, `mypy`, and `pytest` are on `PATH`. `--seed` installs pip into the environment. Without it, `python -m pip` is missing.

On a normal CPython, where `python3.11 -m venv` can find the standard library, use this block instead:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Token

Save the token with:

```bash
bash scripts/set_token.sh
```

The script prompts once and writes `GITHUB_TOKEN` to `.env`. The token stays in `.env`. Git ignores that file. TaskForge reads the token from `.env` only, not from the shell. Public-repository read access is enough.

A repository must be listed in `forge/allowlist.yaml`, and the GitHub API must report SPDX `MIT`, `Apache-2.0`, `BSD-2-Clause`, or `BSD-3-Clause`. Membership is not a license approval. The current names are `pydantic/pydantic`, `psf/requests`, `pallets/click`, `encode/httpx`, and `pallets/itsdangerous`.

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

`forge check` accepts or refuses one repository. `forge funnel` reads that many closed pull requests and prints one count per rejection reason. The limit caps how many pull requests are read. It does not cap how many are accepted. `forge report` runs that same funnel and writes `output/reports/<owner>-<name>-<limit>.json` and the matching Markdown file, then prints both paths. `forge split` prints the source names, the test names, the other names, and the issue URL for one pull request number. It does not write those files. `forge sandbox` runs the command after `--` in a container at that 40-character commit. `forge outcomes` classifies the local widget fixture once. `forge gates` runs the validation gates on `widget` or `counter`. `forge package` writes a local fixture task only when those gates accept. `forge package-pull` checks the allowlist and the SPDX license, then applies the current filters. A filter rejection writes nothing. An accepted pull request is packaged under `output/` only when gates V1 through V5 accept and V6 through V8 are clean.

## Checks

These three do not need a token or Docker:

```bash
ruff check forge tests
mypy
pytest
```

## Docker

`forge sandbox`, `forge outcomes`, `forge gates`, `forge package`, and `forge package-pull` need Docker. The Docker daemon must be able to mount the clone, and this Colima does not mount `/tmp`. Repository code runs only inside that sandbox. The container has no network, 512 MB of memory, one CPU, a timeout, and a read-only patch mount. The host does not run the repository's tests or setup. The eval image build may use the network. A checkout with `pyproject.toml` or `setup.py` is installed with `pip install -e .` after the files are copied. The widget and counter fixtures have no packaging metadata and keep the git and pytest image.

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
