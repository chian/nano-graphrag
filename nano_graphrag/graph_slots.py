from __future__ import annotations

from typing import Any, Iterable


CANONICAL_SOURCE_REFS = "source_refs"
CANONICAL_ALIASES = "aliases"
CANONICAL_SALIENCE = "salience_score"
CANONICAL_CLUSTER_MEMBERSHIPS = "cluster_memberships"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [value]


def get_source_refs(data: dict[str, Any]) -> list[str]:
    refs = _as_list(data.get(CANONICAL_SOURCE_REFS))
    if refs:
        return [str(r) for r in refs]
    legacy = _as_list(data.get("source_papers"))
    return [str(r) for r in legacy]


def add_source_ref(data: dict[str, Any], ref: str) -> None:
    refs = get_source_refs(data)
    if ref and ref not in refs:
        refs.append(ref)
    data[CANONICAL_SOURCE_REFS] = refs


def get_aliases(data: dict[str, Any]) -> list[str]:
    aliases = _as_list(data.get(CANONICAL_ALIASES))
    if aliases:
        return [str(a) for a in aliases]
    legacy = _as_list(data.get("alternative_names"))
    return [str(a) for a in legacy]


def add_alias(data: dict[str, Any], alias: str) -> None:
    aliases = get_aliases(data)
    if alias and alias not in aliases:
        aliases.append(alias)
    data[CANONICAL_ALIASES] = aliases


def get_salience_score(data: dict[str, Any], default: float = 0.5) -> float:
    value = data.get(CANONICAL_SALIENCE, data.get("importance_score", default))
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def set_salience_score(data: dict[str, Any], value: float) -> None:
    try:
        data[CANONICAL_SALIENCE] = float(value)
    except (TypeError, ValueError):
        data[CANONICAL_SALIENCE] = 0.0


def get_cluster_memberships(data: dict[str, Any]) -> list[Any]:
    memberships = _as_list(data.get(CANONICAL_CLUSTER_MEMBERSHIPS))
    if memberships:
        return memberships
    return _as_list(data.get("communityIds"))


def set_cluster_memberships(data: dict[str, Any], memberships: Iterable[Any]) -> None:
    data[CANONICAL_CLUSTER_MEMBERSHIPS] = list(memberships)
