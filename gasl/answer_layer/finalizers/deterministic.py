from __future__ import annotations

from ..types import AnswerSelection


class DeterministicAnswerFinalizer:
    def finalize(self, query: str, selection: AnswerSelection) -> str:
        view = selection.view
        if not view or not view.sufficient:
            return ""
        if view.kind == "ranked_subjects":
            names = [row["item"] for row in view.payload.get("ranked_items", [])[:3]]
            if names:
                return ", ".join(names)
        if view.kind == "comparison":
            comparands = view.payload.get("comparands", [])
            if len(comparands) == 2:
                return f"{comparands[0]} vs {comparands[1]}: delta={view.payload.get('delta')}"
        if view.kind == "distribution":
            return f"n={view.payload.get('n')}; mean={view.payload.get('mean')}; median={view.payload.get('median')}"
        if view.kind == "evidence_lookup":
            refs = view.payload.get("refs", [])[:3]
            items = [ref.get("item_id") for ref in refs if ref.get("item_id")]
            if items:
                return ", ".join(items)
        return ""
