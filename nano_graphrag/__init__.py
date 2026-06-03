from __future__ import annotations

__version__ = "0.0.8.2"
__author__ = "Jianbai Ye"
__url__ = "https://github.com/gusye1234/nano-graphrag"

__all__ = ["GraphRAG", "QueryParam"]


def __getattr__(name: str):
    if name in {"GraphRAG", "QueryParam"}:
        from .graphrag import GraphRAG, QueryParam

        return {"GraphRAG": GraphRAG, "QueryParam": QueryParam}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
