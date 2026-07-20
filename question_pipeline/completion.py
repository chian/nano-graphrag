"""State helpers for the table-fill completion-scope agent."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .search import compact_search_result


_DONE_STATUSES = {"accepted", "deferred", "out_of_scope", "resolved"}
_OPEN_STATUSES = {"", "open", "unresolved", "needs_search", "underexplored"}
_BLOCKING_SEVERITIES = {"error", "high", "critical"}


def new_completion_state() -> dict[str, Any]:
    return {
        "version": 1,
        "scope_status": "missing",
        "expected_axes": [],
        "search_space_probes": [],
        "underexplored_bins": [],
        "estimate_issues": [],
        "unresolved_questions": [],
        "suggested_queries": [],
        "latest_judgment": {},
    }


def normalize_completion_state(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Coerce persisted completion state into one stable shape."""

    if not isinstance(raw, Mapping):
        raw = {}

    state = new_completion_state()
    status = _clean(raw.get("scope_status") or raw.get("status") or "missing")
    if status not in {
        "missing",
        "probing",
        "insufficient_evidence",
        "estimated",
        "inconsistent",
    }:
        status = "missing"
    state["scope_status"] = status
    state["expected_axes"] = _unique_mappings(
        _coerce_axis(axis)
        for axis in _as_list(raw.get("expected_axes") or raw.get("axes"))
    )
    state["search_space_probes"] = _unique_mappings(
        _coerce_probe(probe)
        for probe in _as_list(
            raw.get("search_space_probes")
            or raw.get("scope_probes")
            or raw.get("probes")
        )
    )
    state["underexplored_bins"] = _unique_mappings(
        _coerce_issue(issue)
        for issue in _as_list(raw.get("underexplored_bins"))
    )
    state["estimate_issues"] = _unique_mappings(
        _coerce_issue(issue)
        for issue in _as_list(raw.get("estimate_issues") or raw.get("issues"))
    )
    state["unresolved_questions"] = _unique_strings(raw.get("unresolved_questions"))
    state["suggested_queries"] = _unique_strings(raw.get("suggested_queries"))
    latest = raw.get("latest_judgment")
    state["latest_judgment"] = dict(latest) if isinstance(latest, Mapping) else {}
    if raw.get("updated_at"):
        state["updated_at"] = str(raw.get("updated_at"))
    return state


def completion_update_from_estimate(estimate: Mapping[str, Any]) -> dict[str, Any]:
    """Extract completion-scope fields that the universe estimator can refresh."""

    return {
        "scope_status": (
            "estimated"
            if str(estimate.get("status") or "") == "estimated"
            else "insufficient_evidence"
        ),
        "expected_axes": estimate.get("expected_axes") or [],
        "underexplored_bins": estimate.get("underexplored_bins") or [],
        "unresolved_questions": estimate.get("unresolved_questions") or [],
        "suggested_queries": estimate.get("suggested_queries") or [],
    }


def completion_update_from_critique(critique: Mapping[str, Any]) -> dict[str, Any]:
    """Extract state fields from a consistency critique."""

    accepted = bool(critique.get("accepted") or critique.get("accept"))
    issues = _as_list(critique.get("issues") or critique.get("estimate_issues"))
    bins = _as_list(critique.get("underexplored_bins"))
    open_issues = [
        issue
        for issue in (_coerce_issue(issue) for issue in issues)
        if _is_blocking_issue(issue)
    ]
    open_bins = [
        issue
        for issue in (_coerce_issue(issue) for issue in bins)
        if _clean(issue.get("status")) not in _DONE_STATUSES
    ]
    return {
        "scope_status": (
            "estimated"
            if accepted and not open_issues and not open_bins
            else "inconsistent"
        ),
        "latest_judgment": dict(critique),
        "estimate_issues": issues,
        "underexplored_bins": bins,
        "unresolved_questions": critique.get("unresolved_questions") or [],
        "suggested_queries": critique.get("suggested_queries") or [],
    }


def merge_completion_state(
    previous: Mapping[str, Any] | None,
    update: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Merge a fresh completion-agent observation into durable state."""

    base = normalize_completion_state(previous)
    fresh = normalize_completion_state(update)
    out = new_completion_state()
    out["scope_status"] = (
        fresh["scope_status"]
        if fresh["scope_status"] != "missing"
        else base["scope_status"]
    )
    out["expected_axes"] = _unique_mappings(
        [*base["expected_axes"], *fresh["expected_axes"]]
    )
    out["search_space_probes"] = _unique_mappings(
        [*base["search_space_probes"], *fresh["search_space_probes"]]
    )
    out["underexplored_bins"] = (
        fresh["underexplored_bins"]
        if "underexplored_bins" in (update or {})
        else base["underexplored_bins"]
    )
    out["estimate_issues"] = (
        fresh["estimate_issues"]
        if (
            isinstance(update, Mapping)
            and ("estimate_issues" in update or "issues" in update)
        )
        else base["estimate_issues"]
    )
    out["unresolved_questions"] = _unique_strings(
        [*fresh["unresolved_questions"], *base["unresolved_questions"]]
    )
    out["suggested_queries"] = _unique_strings(
        [*fresh["suggested_queries"], *base["suggested_queries"]]
    )
    out["latest_judgment"] = fresh["latest_judgment"] or base["latest_judgment"]
    if isinstance(update, Mapping) and update.get("updated_at"):
        out["updated_at"] = str(update.get("updated_at"))
    elif base.get("updated_at"):
        out["updated_at"] = base["updated_at"]
    return out


def completion_probe_summary(
    *,
    query: str,
    results: Iterable[Mapping[str, Any]],
    artifact_label: int | str,
    purpose: str = "",
    axis_bindings: Mapping[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    """Summarize a cheap breadth probe without retaining scraped page bodies."""

    compact_results = [
        compact_search_result(dict(result))
        for result in results
        if isinstance(result, Mapping)
    ]
    urls = _unique_strings(result.get("url") for result in compact_results)
    domains = _unique_strings(_domain(url) for url in urls)
    titles = _unique_strings(
        result.get("title") or _nested_metadata_value(result, "title")
        for result in compact_results
    )
    payload = {
        "id": _stable_id(
            {
                "query": _normalize_text(query),
                "artifact_label": str(artifact_label),
                "purpose": purpose,
            }
        ),
        "artifact_label": artifact_label,
        "pipeline_round": artifact_label if isinstance(artifact_label, int) else None,
        "query": str(query or "").strip(),
        "purpose": str(purpose or "").strip(),
        "axis_bindings": dict(axis_bindings or {}),
        "result_count": len(compact_results),
        "unique_url_count": len(urls),
        "unique_domain_count": len(domains),
        "result_count_bucket": result_count_bucket(len(compact_results)),
        "domains": domains[:12],
        "titles": titles[:12],
        "results": compact_results[:10],
    }
    if error:
        payload["error"] = str(error)
    return payload


def result_count_bucket(count: int) -> str:
    if count <= 0:
        return "none"
    if count == 1:
        return "one"
    if count <= 3:
        return "few"
    if count <= 9:
        return "several"
    return "many"


def scope_probe_context(
    state: Mapping[str, Any],
    *,
    limit: int = 16,
) -> dict[str, Any]:
    """Return a compact state excerpt for prompts and gates."""

    normalized = normalize_completion_state(state)
    probes = normalized["search_space_probes"][-limit:]
    return {
        "scope_status": normalized["scope_status"],
        "expected_axes": normalized["expected_axes"],
        "search_space_probe_count": len(normalized["search_space_probes"]),
        "recent_search_space_probes": probes,
        "underexplored_bins": open_completion_bins(normalized),
        "estimate_issues": open_completion_issues(normalized),
        "unresolved_questions": normalized["unresolved_questions"][:20],
        "suggested_queries": normalized["suggested_queries"][:20],
        "latest_judgment": normalized.get("latest_judgment") or {},
    }


def completion_scope_actionable(
    state: Mapping[str, Any] | None,
    universe_estimate: Mapping[str, Any] | None,
) -> bool:
    """Return True only when the universe estimate has survived scoping."""

    normalized = normalize_completion_state(state)
    if str((universe_estimate or {}).get("status") or "") != "estimated":
        return False
    if not (universe_estimate or {}).get("count_targets"):
        return False
    if not normalized["search_space_probes"]:
        return False
    if normalized["scope_status"] not in {"estimated"}:
        return False
    if open_completion_issues(normalized):
        return False
    if open_completion_bins(normalized):
        return False
    return True


def completion_needs_scope_search(
    state: Mapping[str, Any] | None,
    universe_estimate: Mapping[str, Any] | None,
) -> bool:
    """Return True when broad scoping still needs search attention."""

    estimate = universe_estimate or {}
    normalized = normalize_completion_state(state)
    return (
        str(estimate.get("status") or "") != "estimated"
        or not estimate.get("count_targets")
        or bool(estimate.get("unestimated_count_targets"))
        or not normalized["search_space_probes"]
        or normalized["scope_status"] in {"missing", "probing", "inconsistent"}
        or bool(open_completion_issues(normalized))
        or bool(open_completion_bins(normalized))
    )


def open_completion_issues(
    state: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_completion_state(state)
    return [
        issue
        for issue in normalized["estimate_issues"]
        if _is_blocking_issue(issue)
    ]


def open_completion_bins(
    state: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    normalized = normalize_completion_state(state)
    return [
        issue
        for issue in normalized["underexplored_bins"]
        if _clean(issue.get("status")) not in _DONE_STATUSES
    ]


def load_seed_completion_state(path: str | Path | None) -> dict[str, Any]:
    """Load the latest persisted completion state adjacent to seed tables."""

    if not path:
        return new_completion_state()

    roots: list[Path] = []
    for raw in str(path).split(os.pathsep):
        if not raw.strip():
            continue
        seed_path = Path(raw)
        roots.extend(
            candidate
            for candidate in (
                seed_path,
                seed_path.parent,
                seed_path / "goals",
                seed_path.parent / "goals",
                seed_path.parent.parent / "goals",
            )
            if candidate.exists()
        )

    candidates = sorted(
        {
            file_path
            for root in roots
            if root.is_dir()
            for file_path in [
                *(root.glob("completion_state.json")),
                *(root.glob("*_completion_state.json")),
            ]
        },
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping):
            return normalize_completion_state(payload)
    return new_completion_state()


def _coerce_axis(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"name": raw}
    if not isinstance(raw, Mapping):
        return {}
    name = _clean_display(raw.get("name") or raw.get("axis") or raw.get("field"))
    if not name:
        return {}
    return {
        "id": str(raw.get("id") or _stable_id({"axis": name}))[:24],
        "name": name,
        "description": _clean_display(raw.get("description")),
        "status": _clean(raw.get("status") or "open") or "open",
        "supporting_queries": _unique_strings(raw.get("supporting_queries")),
    }


def _coerce_issue(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = {"description": raw}
    if not isinstance(raw, Mapping):
        return {}
    description = _clean_display(
        raw.get("description")
        or raw.get("issue")
        or raw.get("bin")
        or raw.get("reason")
    )
    axis = _clean_display(raw.get("axis") or raw.get("table") or raw.get("slot"))
    if not description and not axis:
        return {}
    payload = {
        "axis": axis,
        "description": description,
        "status": _clean(raw.get("status") or "open") or "open",
        "severity": _clean(raw.get("severity") or "error") or "error",
        "suggested_queries": _unique_strings(raw.get("suggested_queries")),
    }
    payload["id"] = str(raw.get("id") or _stable_id(payload))[:24]
    return payload


def _coerce_probe(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    query = _clean_display(raw.get("query"))
    if not query:
        return {}
    results = [
        compact_search_result(dict(result))
        for result in _as_list(raw.get("results"))
        if isinstance(result, Mapping)
    ]
    urls = _unique_strings(
        [*_as_list(raw.get("urls")), *(result.get("url") for result in results)]
    )
    domains = _unique_strings(
        [
            *_as_list(raw.get("domains")),
            *(_domain(url) for url in urls),
        ]
    )
    result_count = _as_int(raw.get("result_count"))
    if result_count <= 0 and results:
        result_count = len(results)
    artifact_label = raw.get("artifact_label", raw.get("round"))
    raw_pipeline_round = raw.get("pipeline_round")
    if not isinstance(raw_pipeline_round, int):
        raw_pipeline_round = (
            raw.get("round") if isinstance(raw.get("round"), int) else None
        )
    payload = {
        "id": str(raw.get("id") or _stable_id({"query": _normalize_text(query)}))[
            :24
        ],
        "artifact_label": artifact_label,
        "pipeline_round": raw_pipeline_round,
        "query": query,
        "purpose": _clean_display(raw.get("purpose")),
        "axis_bindings": (
            dict(raw.get("axis_bindings"))
            if isinstance(raw.get("axis_bindings"), Mapping)
            else {}
        ),
        "result_count": max(0, result_count),
        "unique_url_count": _as_int(raw.get("unique_url_count")) or len(urls),
        "unique_domain_count": (
            _as_int(raw.get("unique_domain_count")) or len(domains)
        ),
        "result_count_bucket": (
            _clean(raw.get("result_count_bucket"))
            or result_count_bucket(result_count)
        ),
        "domains": domains[:12],
        "titles": _unique_strings(raw.get("titles"))[:12],
        "results": results[:10],
    }
    if raw.get("error"):
        payload["error"] = str(raw.get("error"))
    return payload


def _is_blocking_issue(issue: Mapping[str, Any]) -> bool:
    status = _clean(issue.get("status"))
    severity = _clean(issue.get("severity") or "error")
    return status in _OPEN_STATUSES and severity in _BLOCKING_SEVERITIES


def _unique_mappings(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for value in values:
        if not value:
            continue
        key = str(value.get("id") or "") or _stable_id(value)
        out[key] = dict(value)
    return list(out.values())


def _unique_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable) or isinstance(values, (bytes, Mapping)):
        values = [values]

    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_display(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _nested_metadata_value(result: Mapping[str, Any], key: str) -> Any:
    metadata = result.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    return metadata.get(key)


def _domain(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return parsed.netloc.lower().lstrip("www.")


def _stable_id(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _clean(value: Any) -> str:
    return _normalize_text(value).replace("-", "_")


def _clean_display(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())
