"""Read closed pull requests from the REST API and count filter reasons.

The limit is how many closed pull requests are read. It is not a cap on how
many of those are accepted. The first list request asks for ``sort=created``
and ``direction=desc``. Later pages use the Link ``rel=next`` URL. Pulls stay
in the order the list response returns them. They are not sorted by
``closed_at``, ``updated_at``, or number. Pagination follows Link headers.
The search API is not used.
"""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from pydantic import ValidationError

from forge.check import check_repository
from forge.config import default_cache_path, load_github_token
from forge.errors import ForgeError, GitHubError
from forge.filters import classify_pull, decision_evidence, early_reason
from forge.github import API_ROOT, GitHubClient, next_link
from forge.models import (
    CheckResult,
    FilterReason,
    FunnelCounts,
    FunnelReport,
    PullFilePayload,
    PullPayload,
    ReasonCode,
)

PULLS_PER_PAGE = 100


@dataclass(frozen=True)
class FunnelRun:
    refusal: CheckResult | None = None
    report: FunnelReport | None = None


def run_funnel(
    repo: str,
    *,
    root: Path,
    limit: int,
    client: GitHubClient | None = None,
) -> FunnelRun:
    if limit < 1:
        raise ForgeError(
            "limit must be a positive integer. It caps how many closed PRs are read.",
            reason=ReasonCode.CONFIG_ERROR,
        )
    if client is not None:
        gate = check_repository(repo, root=root, client=client)
        if not gate.accepted:
            return FunnelRun(refusal=gate)
        return _collect(gate.full_name, limit=limit, client=client)
    gate = check_repository(repo, root=root)
    if not gate.accepted:
        return FunnelRun(refusal=gate)
    token = load_github_token(root / ".env")
    with GitHubClient(token=token, cache_path=default_cache_path(root)) as owned:
        return _collect(gate.full_name, limit=limit, client=owned)


def format_report(report: FunnelReport) -> str:
    lines = [
        f"repo {report.full_name}",
        f"limit {report.limit}",
        "order created desc",
        f"considered {report.considered}",
    ]
    for name, value in report.counts.model_dump().items():
        lines.append(f"{name} {value}")
    lines.append(f"accepted {report.accepted}")
    cut_off = "yes" if report.older_prs_cut_off else "no"
    lines.append(f"older_prs_cut_off {cut_off}")
    lines.extend(report.evidence)
    return "\n".join(lines)


def _collect(full_name: str, *, limit: int, client: GitHubClient) -> FunnelRun:
    owner, name = full_name.split("/", maxsplit=1)
    pulls, cut_off = collect_closed_pulls(client, owner, name, limit)
    counts_map = {reason: 0 for reason in FilterReason}
    accepted = 0
    evidence: list[str] = []
    for pull in pulls:
        pull = _with_size(client, owner, name, pull)
        files: list[PullFilePayload] | None
        if early_reason(pull) is not None:
            files = None
        else:
            files = fetch_pull_files(client, owner, name, pull.number)
        reason = classify_pull(pull, files)
        evidence.append(decision_evidence(pull, files))
        if reason is None:
            accepted += 1
        else:
            counts_map[reason] += 1
    counts = FunnelCounts(**{reason.value: counts_map[reason] for reason in FilterReason})
    considered = len(pulls)
    if considered != accepted + counts.total():
        raise ForgeError(
            "Funnel counts do not add up to the pull requests that were read.",
            reason=ReasonCode.INTERNAL,
        )
    report = FunnelReport(
        full_name=full_name,
        limit=limit,
        considered=considered,
        counts=counts,
        accepted=accepted,
        older_prs_cut_off=cut_off,
        evidence=evidence,
    )
    return FunnelRun(report=report)


def collect_closed_pulls(
    client: GitHubClient,
    owner: str,
    name: str,
    limit: int,
) -> tuple[list[PullPayload], bool]:
    """Return up to `limit` closed pulls and whether older pulls were not read.

    The list order is the response order. This does not sort by ``closed_at``,
    ``updated_at``, or pull number.
    """
    url: str | None = closed_pulls_url(owner, name, page=1)
    pulls: list[PullPayload] = []
    cut_off = False
    while url is not None and len(pulls) < limit:
        document = client.get(url)
        if not isinstance(document.data, list):
            raise GitHubError(
                "Closed pull list was not a JSON array.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        following = next_link(document.link)
        stopped_early = False
        for item in document.data:
            if len(pulls) >= limit:
                stopped_early = True
                break
            pulls.append(_pull_from_item(item))
        if len(pulls) >= limit and (stopped_early or following is not None):
            cut_off = True
            break
        if not document.data or following is None:
            break
        url = following
    return pulls, cut_off


def _with_size(
    client: GitHubClient,
    owner: str,
    name: str,
    pull: PullPayload,
) -> PullPayload:
    """Fill in size fields when the list resource left them out.

    ``GET /repos/{owner}/{repo}/pulls`` does not include ``changed_files``,
    ``additions``, or ``deletions``. Those counts live on the pull itself.
    A list item that already has ``changed_files`` is left alone, so an
    explicit missing additions or deletions stays ``unknown_size``.
    """
    if pull.merged_at is None or pull.changed_files is not None:
        return pull
    if early_reason(pull) == FilterReason.REVERT:
        return pull
    return fetch_pull(client, owner, name, pull.number)


def fetch_pull(
    client: GitHubClient,
    owner: str,
    name: str,
    number: int,
) -> PullPayload:
    document = client.get(f"{API_ROOT}/repos/{owner}/{name}/pulls/{number}")
    if not isinstance(document.data, dict):
        raise GitHubError(
            "Pull payload was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    return _pull_from_item(document.data)


def fetch_pull_files(
    client: GitHubClient,
    owner: str,
    name: str,
    number: int,
) -> list[PullFilePayload]:
    url: str | None = pull_files_url(owner, name, number)
    files: list[PullFilePayload] = []
    while url is not None:
        document = client.get(url)
        if not isinstance(document.data, list):
            raise GitHubError(
                "Pull file list was not a JSON array.",
                reason=ReasonCode.GITHUB_ERROR,
            )
        for item in document.data:
            files.append(_file_from_item(item))
        url = next_link(document.link)
    return files


def closed_pulls_url(owner: str, name: str, *, page: int) -> str:
    query = urlencode(
        {
            "state": "closed",
            "sort": "created",
            "direction": "desc",
            "per_page": str(PULLS_PER_PAGE),
            "page": str(page),
        }
    )
    return f"{API_ROOT}/repos/{owner}/{name}/pulls?{query}"


def pull_files_url(owner: str, name: str, number: int) -> str:
    return f"{API_ROOT}/repos/{owner}/{name}/pulls/{number}/files?per_page=100"


def _pull_from_item(item: object) -> PullPayload:
    if not isinstance(item, dict):
        raise GitHubError(
            "Pull entry was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    try:
        return PullPayload.model_validate(item)
    except ValidationError:
        raise GitHubError(
            "Pull entry was missing the fields needed to filter it.",
            reason=ReasonCode.GITHUB_ERROR,
        ) from None


def _file_from_item(item: object) -> PullFilePayload:
    if not isinstance(item, dict):
        raise GitHubError(
            "Pull file entry was not a JSON object.",
            reason=ReasonCode.GITHUB_ERROR,
        )
    try:
        return PullFilePayload.model_validate(item)
    except ValidationError:
        raise GitHubError(
            "Pull file entry was missing a filename.",
            reason=ReasonCode.GITHUB_ERROR,
        ) from None
