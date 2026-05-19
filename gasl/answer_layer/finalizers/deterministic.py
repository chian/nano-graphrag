from __future__ import annotations

from ..types import AnswerSelection


class DeterministicAnswerFinalizer:
    def finalize(self, query: str, selection: AnswerSelection) -> str:
        view = selection.view
        if not view or not view.sufficient:
            return ""
        if view.kind == "ranking":
            names = [row["subject"] for row in view.payload.get("ranked_subjects", [])[:3]]
            if names:
                return ", ".join(names)
        if view.kind == "comparison":
            comparands = view.payload.get("comparands", [])
            if len(comparands) == 2:
                return f"{comparands[0]} vs {comparands[1]}: delta={view.payload.get('delta')}"
        if view.kind == "frontier":
            names = [row["subject"] for row in view.payload.get("subjects", [])[:3]]
            if names:
                return ", ".join(names)
        if view.kind == "grouped_summary":
            rows = view.payload.get("rows", [])[:3]
            parts = []
            for row in rows:
                parts.append(
                    f"{row['subject']} | {row['outcome'] or 'overall'} | measure={row['measure_mean']} | support={row['support_n']}"
                )
            if parts:
                return "; ".join(parts)
        if view.kind == "distribution":
            return f"n={view.payload.get('n')}; mean={view.payload.get('mean')}; median={view.payload.get('median')}"
        if view.kind == "provenance":
            refs = view.payload.get("refs", [])[:3]
            items = [ref.get("item_id") for ref in refs if ref.get("item_id")]
            if items:
                return ", ".join(items)
        return ""
