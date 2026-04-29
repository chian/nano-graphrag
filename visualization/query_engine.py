"""
Query engines for the visualization server.

Mode 1 – RagQueryEngine : fast TF-IDF similarity search over node descriptions.
Mode 2 – GaslQueryEngine: GASL hypothesis-driven graph traversal with live
                           SocketIO streaming of every command step.
"""

import sys
import threading
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

# Ensure the project root is on sys.path so gasl/ can be imported.
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from .graph_loader import GraphLoader


# ──────────────────────────────────────────────────────────────────────────────
# Mode 1 – RAG (TF-IDF)
# ──────────────────────────────────────────────────────────────────────────────

class RagQueryEngine:
    """
    Fast, self-contained RAG over the loaded graph.

    Builds a TF-IDF index over (node_id + entity_type + description) when the
    graph is loaded, then uses cosine similarity to rank nodes against a
    free-text question.
    """

    def __init__(self, loader: GraphLoader):
        self.loader = loader
        self._node_ids: List[str] = []
        self._vectorizer = None
        self._matrix = None
        self._cosine_similarity = None
        self._build_index()

    # ------------------------------------------------------------------
    def _build_index(self):
        """Build TF-IDF index from current graph."""
        if self.loader.graph is None:
            return

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
            self._cosine_similarity = _cos_sim
        except ImportError:
            # sklearn not available – fall back to substring matching
            return

        corpus = []
        self._node_ids = []
        for node_id, data in self.loader.graph.nodes(data=True):
            entity_type = data.get('entity_type', '')
            description = data.get('description', '')
            text = f"{node_id} {entity_type} {description}".strip()
            corpus.append(text)
            self._node_ids.append(node_id)

        if corpus:
            self._vectorizer = TfidfVectorizer(
                min_df=1,
                stop_words='english',
                ngram_range=(1, 2),
                max_features=50_000,
            )
            self._matrix = self._vectorizer.fit_transform(corpus)

    # ------------------------------------------------------------------
    def query(self, question: str, top_k: int = 15) -> Dict[str, Any]:
        """
        Find the most relevant nodes for *question*.

        Returns:
            {nodes, neighbor_nodes, edges, context}
        """
        if not self._node_ids:
            return {'nodes': [], 'neighbor_nodes': [], 'edges': [], 'context': ''}

        if self._vectorizer is not None:
            q_vec = self._vectorizer.transform([question])
            scores = self._cosine_similarity(q_vec, self._matrix).flatten()
            top_indices = scores.argsort()[-top_k:][::-1]
            top_node_ids = [
                self._node_ids[i] for i in top_indices if scores[i] > 0
            ]
        else:
            # Fallback: substring match
            q_lower = question.lower()
            top_node_ids = []
            for node_id, data in self.loader.graph.nodes(data=True):
                desc = data.get('description', '').lower()
                if q_lower in node_id.lower() or q_lower in desc:
                    top_node_ids.append(node_id)
            top_node_ids = top_node_ids[:top_k]

        top_set = set(top_node_ids)
        G = self.loader.graph
        edges: List[Tuple[str, str]] = []
        neighbor_ids: set = set()

        # Edges between top nodes + collect 1-hop neighbors
        for src, tgt in G.edges():
            if src in top_set and tgt in top_set:
                edges.append((src, tgt))
            elif src in top_set:
                neighbor_ids.add(tgt)
            elif tgt in top_set:
                neighbor_ids.add(src)

        # A few edges out from the top nodes towards neighbors
        for node in list(top_set)[:5]:
            for src, tgt in list(G.edges(node))[:5]:
                pair = (src, tgt)
                if pair not in edges:
                    edges.append(pair)
                neighbor_ids.discard(src if src != node else tgt)

        # Build context string for LLM
        context_parts = []
        for node_id in top_node_ids[:10]:
            data = dict(G.nodes[node_id])
            context_parts.append(
                f"[{data.get('entity_type', '?')}] {node_id}: "
                f"{data.get('description', '')[:300]}"
            )
        context = "\n".join(context_parts)

        return {
            'nodes': top_node_ids,
            'neighbor_nodes': list(neighbor_ids)[:30],
            'edges': [list(e) for e in edges],
            'context': context,
        }

    # ------------------------------------------------------------------
    def generate_answer(self, question: str, context: str,
                        api_key: Optional[str] = None,
                        model: Optional[str] = None) -> Dict[str, Any]:
        """Generate a natural-language answer using ArgoBridgeLLM.

        Returns a dict {'text': str, 'usage': {prompt_tokens, completion_tokens,
        total_tokens, calls}} so the server can surface usage to the UI."""
        empty_usage = {"prompt_tokens": 0, "completion_tokens": 0,
                       "total_tokens": 0, "calls": 0}
        if not context:
            return {"text": "(No relevant nodes found in the graph for this question.)",
                    "usage": empty_usage}
        try:
            from gasl.llm.argo_bridge import ArgoBridgeLLM
            llm = ArgoBridgeLLM(model=model, api_key=api_key)
            prompt = (
                "You are answering questions about a biomedical knowledge graph "
                "focused on respiratory disease and cognitive function.\n\n"
                f"Relevant graph nodes:\n{context}\n\n"
                f"Question: {question}\n\n"
                "Provide a concise, evidence-based answer using only the nodes above:"
            )
            text = llm.call(prompt)
            return {"text": text, "usage": dict(llm.usage)}
        except Exception as e:
            return {
                "text": f"(LLM answer unavailable: {e} – see highlighted nodes in the graph)",
                "usage": empty_usage,
            }


# ──────────────────────────────────────────────────────────────────────────────
# Mode 2 – GASL (graph walk with live SocketIO streaming)
# ──────────────────────────────────────────────────────────────────────────────

class _VisualizingPatch:
    """
    Monkeypatches GASLExecutor._execute_command to emit SocketIO events
    before and after every GASL command without touching the executor source.
    """

    def __init__(self, executor, socketio, job_id: str):
        self._executor = executor
        self._socketio = socketio
        self._job_id = job_id
        self._touched_nodes: set = set()
        self._touched_edges: List[Tuple] = []

        # Patch
        self._original = executor._execute_command
        executor._execute_command = self._hooked

    # ------------------------------------------------------------------
    def _hooked(self, command, step_id):
        """Drop-in replacement for GASLExecutor._execute_command."""
        # Announce command start
        self._emit('gasl_step', {
            'job_id': self._job_id,
            'command': command.raw_text,
            'command_type': command.command_type,
            'status': 'running',
        })

        result = self._original(command, step_id)

        # Extract node IDs that were touched
        nodes = self._extract_nodes(result)

        # Also scan context store (FIND stores results there)
        try:
            ctx = self._executor.context_store
            for key in list(ctx._data.keys()):
                val = ctx.get(key)
                if isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            nid = (item.get('id')
                                   or item.get('entity_name')
                                   or item.get('name'))
                            if nid:
                                nodes.append(str(nid))
        except Exception:
            pass

        # Deduplicate
        new_nodes = [n for n in nodes if n not in self._touched_nodes]
        self._touched_nodes.update(new_nodes)

        # Emit highlight update
        self._emit('gasl_highlight', {
            'job_id': self._job_id,
            'nodes': new_nodes,
            'edges': [],
            'command': command.raw_text,
            'command_type': command.command_type,
            'status': result.status,
        })

        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_nodes(result) -> List[str]:
        nodes = []
        if not result.data:
            return nodes
        data = result.data
        items = data if isinstance(data, list) else [data]
        for item in items:
            if isinstance(item, dict):
                nid = (item.get('id')
                       or item.get('entity_name')
                       or item.get('name'))
                if nid:
                    nodes.append(str(nid))
        return nodes

    # ------------------------------------------------------------------
    def _emit(self, event: str, payload: dict):
        try:
            self._socketio.emit(event, payload)
        except Exception:
            pass

    # ------------------------------------------------------------------
    @property
    def all_touched_nodes(self) -> List[str]:
        return list(self._touched_nodes)


class GaslQueryEngine:
    """
    Runs a GASL hypothesis-driven traversal for a question and streams
    command-level progress to connected browsers via SocketIO.

    Usage (called from a background thread):
        engine.run(question, job_id)
    """

    def __init__(self, loader: GraphLoader, socketio):
        self.loader = loader
        self.socketio = socketio

    # ------------------------------------------------------------------
    def run(self, question: str, job_id: str,
            api_key: Optional[str] = None,
            model: Optional[str] = None):
        """Execute GASL traversal in a background thread."""
        patch = None
        try:
            from gasl import GASLExecutor
            from gasl.adapters import NetworkXAdapter
            from gasl.llm.argo_bridge import ArgoBridgeLLM

            adapter = NetworkXAdapter(self.loader.graph)
            llm = ArgoBridgeLLM(model=model, api_key=api_key)
            executor = GASLExecutor(adapter, llm)

            # Attach visualization patch
            patch = _VisualizingPatch(executor, self.socketio, job_id)

            # Signal start
            self.socketio.emit('gasl_step', {
                'job_id': job_id,
                'command': 'Starting GASL traversal…',
                'command_type': 'INIT',
                'status': 'running',
            })

            result = executor.run_hypothesis_driven_traversal(
                question, max_iterations=8
            )

            self.socketio.emit('query_complete', {
                'job_id': job_id,
                'answer': result.get('final_answer', '(No answer generated)'),
                'nodes': patch.all_touched_nodes,
                'edges': [],
                'iterations': result.get('iterations', 0),
                'query_answered': result.get('query_answered', False),
                'usage': dict(llm.usage),
            })

        except Exception as e:
            usage = dict(llm.usage) if 'llm' in locals() else {
                "prompt_tokens": 0, "completion_tokens": 0,
                "total_tokens": 0, "calls": 0,
            }
            self.socketio.emit('query_complete', {
                'job_id': job_id,
                'answer': f"GASL error: {e}",
                'nodes': patch.all_touched_nodes if patch else [],
                'edges': [],
                'iterations': 0,
                'query_answered': False,
                'usage': usage,
            })
