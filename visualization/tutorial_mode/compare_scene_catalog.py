from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List


def _frame(duration_ms: int, title: str, body: str, focus: str, gasl_chips: List[str] | None = None) -> Dict[str, Any]:
    return {
        "duration_ms": duration_ms,
        "title": title,
        "body": body,
        "focus": focus,
        "gasl_chips": gasl_chips or [],
    }


@lru_cache(maxsize=1)
def get_compare_scenes() -> List[Dict[str, Any]]:
    scenes: List[Dict[str, Any]] = [
        {
            "order": 1,
            "id": "01_opening_tharp_wegener",
            "stage_type": "bridge",
            "title": "Opening: Claim vs Compilation",
            "subtitle": "Wegener can assert; Tharp can compile and reveal.",
            "frames": [
                _frame(5200, "A bold idea is not yet a legible structure.", "Wegener had the idea. The evidence did not yet compile into something the whole field could see.", "classic"),
                _frame(5600, "Compilation changes what a claim feels like.", "Tharp's maps did not merely add more facts. They compiled scattered signals into a structure that became hard to ignore.", "gasl"),
                _frame(5600, "This tutorial uses that same distinction.", "GASL matters when the task is not just to retrieve a fact, but to compile evidence into an answer-bearing structure.", "gasl"),
            ],
        },
        {
            "order": 2,
            "id": "02_design_space_axes",
            "stage_type": "axes",
            "title": "The Design Space",
            "subtitle": "Precision, flexibility, and feasible access compete with each other.",
            "frames": [
                _frame(4800, "Classic systems: precise and controllable.", "Databases and retrieval systems are strong when the schema and access path are already known.", "classic"),
                _frame(4800, "LLM-only: flexible but too expensive at graph scale.", "You could try to pass everything into a giant context, but practical context and cost limits dominate.", "llm"),
                _frame(4800, "RAG: practical but retrieval-limited.", "RAG narrows the evidence, yet the slice can still be plausible and incomplete.", "rag"),
                _frame(5400, "GASL: explicit evidence assembly between those extremes.", "GASL adds a planning-and-repair layer so retrieval, graph access, compilation, and answering become inspectable steps.", "gasl"),
            ],
        },
        {
            "order": 3,
            "id": "03_classic_system_limits",
            "stage_type": "classic_machine",
            "title": "Classic Systems",
            "subtitle": "Great at exact operations; brittle when the evidence shape is not known upfront.",
            "frames": [
                _frame(5000, "What classic systems do well.", "Exact filters, exact joins, exact aggregations. When the evidence shape matches the schema, they are ideal.", "classic"),
                _frame(5600, "Where they break.", "When the question crosses many relation types or needs emergent working memory, the rigid plan starts to dead-end.", "classic"),
                _frame(5200, "What GASL keeps from them.", "GASL keeps explicit operators and typed intermediates, but loosens the path so the plan can be repaired instead of abandoned.", "gasl", ["DECLARE", "SELECT", "AGGREGATE"]),
            ],
        },
        {
            "order": 4,
            "id": "04_llm_only_limits",
            "stage_type": "llm_flood",
            "title": "LLM-Only Reasoning",
            "subtitle": "Broad access is attractive; full ingestion is not usually feasible.",
            "frames": [
                _frame(4800, "What the LLM-only ideal promises.", "If the model could ingest everything cheaply, it could flexibly reason across uncontrolled evidence.", "llm"),
                _frame(5600, "What reality imposes.", "At graph scale, context and cost become practical constraints. The issue is not only capability; it is feasible access.", "llm"),
                _frame(5200, "What GASL keeps from them.", "GASL keeps flexible synthesis at the end, but constrains what gets assembled and how it is checked first.", "gasl", ["answer views", "final synthesis"]),
            ],
        },
        {
            "order": 5,
            "id": "05_rag_limits",
            "stage_type": "rag_beam",
            "title": "RAG",
            "subtitle": "A practical compromise that still depends heavily on retrieval quality.",
            "frames": [
                _frame(5000, "Why RAG is valuable.", "It narrows the evidence so the model can work on a tractable slice instead of a giant corpus or graph.", "rag"),
                _frame(5600, "Why RAG still fails.", "The slice can be sensible but wrong for the question. Needed evidence may remain outside the retrieval beam.", "rag"),
                _frame(5200, "Why GASL adds more than retrieval.", "GASL does not just retrieve. It assembles, validates, repairs, and compiles evidence structures oriented to the answer.", "gasl", ["FIND", "GRAPHWALK", "PROCESS"]),
            ],
        },
        {
            "order": 6,
            "id": "06_gasl_overview",
            "stage_type": "gasl_workbench",
            "title": "GASL as a Response Architecture",
            "subtitle": "Not a single pipeline. A set of command families for different information problems.",
            "frames": [
                _frame(4600, "GASL is not one fixed path.", "Different questions exercise different mechanisms. The system is built to respond to multiple evidence geometries, not to force one pipeline on all questions.", "gasl"),
                _frame(5200, "The command set is not arbitrary.", "Different commands exist because different information must be gathered, assembled, compiled, validated, and verbalized differently.", "gasl", ["DECLARE", "FIND", "GRAPHWALK", "PROCESS", "AGGREGATE", "RANK"]),
                _frame(5000, "The rest of the tutorial groups commands by what they are for.", "We now move from systems design to command families and the weaknesses they address.", "gasl"),
            ],
        },
        {
            "order": 7,
            "id": "07_command_families_intro",
            "stage_type": "command_constellation",
            "title": "Command Families",
            "subtitle": "Each family exists to address a different kind of information-compilation need.",
            "frames": [
                _frame(4200, "Working memory / scoping", "DECLARE gives the plan typed bins to fill. Without them, the question stays underspecified and later evidence has nowhere stable to accumulate.", "gasl", ["DECLARE"]),
                _frame(4200, "Access / retrieval", "FIND, GRAPHWALK, SELECT, and COUNT access different parts of the evidence geometry.", "gasl", ["FIND", "GRAPHWALK", "SELECT", "COUNT"]),
                _frame(4200, "Assembly / reshaping", "PROCESS, PROJECT, JOIN, MERGE, and UPDATE reshape heterogeneous evidence into answer-bearing intermediates.", "gasl", ["PROCESS", "PROJECT", "JOIN", "MERGE", "UPDATE"]),
                _frame(4200, "Compilation / comparison", "AGGREGATE, COLLAPSE, COMPARE, and RANK turn many fragments into distributions, frontiers, and contrasts.", "gasl", ["AGGREGATE", "COLLAPSE", "COMPARE", "RANK"]),
                _frame(4200, "Validation / answer production", "SHOW, INSPECT, the compiler, answer views, and final synthesis stop the system from collapsing too early into raw rows or overconfident answers.", "gasl", ["SHOW", "INSPECT", "answer views"]),
            ],
        },
        {
            "order": 8,
            "id": "08_access_commands",
            "stage_type": "access_map",
            "title": "Access Commands",
            "subtitle": "Why FIND and GRAPHWALK coexist.",
            "frames": [
                _frame(5200, "A question can require many access geometries.", "Sometimes you need node search. Sometimes relation traversal. Sometimes a count. Sometimes a filtered projection.", "gasl", ["FIND", "GRAPHWALK", "SELECT", "COUNT"]),
                _frame(5600, "RAG's weakness here is coverage and relation shape.", "The retrieval beam can fetch useful chunks while still missing the edges and paths that connect them into the right evidence structure.", "rag"),
                _frame(5200, "GASL's answer is explicit access mode switching.", "The system can change from search to traversal to counting without pretending that all evidence lives in one retrieval mode.", "gasl", ["FIND", "GRAPHWALK"]),
            ],
        },
        {
            "order": 9,
            "id": "09_assembly_commands",
            "stage_type": "assembly_pipeline",
            "title": "Assembly Commands",
            "subtitle": "Why PROCESS, JOIN, PROJECT, MERGE, and UPDATE exist.",
            "frames": [
                _frame(5200, "Retrieved evidence is rarely already in answer shape.", "Different rows, relations, and evidence fragments must be normalized and combined before they become comparable.", "gasl", ["PROCESS", "PROJECT", "JOIN", "MERGE", "UPDATE"]),
                _frame(5400, "Classic systems are strongest when the reshape is known upfront.", "But many graph questions discover the needed structure during the run rather than before it.", "classic"),
                _frame(5200, "GASL's answer is to assemble explicit intermediate evidence tables.", "That makes later compilation and answering inspectable instead of hidden inside one giant prompt.", "gasl"),
            ],
        },
        {
            "order": 10,
            "id": "10_compilation_commands",
            "stage_type": "compilation_atlas",
            "title": "Compilation Commands",
            "subtitle": "Why AGGREGATE, COLLAPSE, COMPARE, and RANK matter.",
            "frames": [
                _frame(5600, "Many scientific questions are not lookup questions.", "They ask for frontiers, distributions, contrasts, support counts, and best tradeoffs. Those are compiled structures, not single facts.", "gasl", ["AGGREGATE", "COLLAPSE", "COMPARE", "RANK"]),
                _frame(5200, "This is the Marie Tharp lesson inside GASL.", "Compilation does not merely add facts; it reveals structure. The command family exists because some questions only become answerable after that compilation work.", "gasl"),
                _frame(5200, "RAG often sees too narrow a slice to compile stable patterns.", "Even articulate answers become weaker when the evidence base is not explicitly compiled first.", "rag"),
            ],
        },
        {
            "order": 11,
            "id": "11_validation_repair_commands",
            "stage_type": "validation_gate",
            "title": "Validation and Repair",
            "subtitle": "Why GASL does not trust the first plan or the first local step.",
            "frames": [
                _frame(5200, "First plans fail.", "That is not a flaw of one model; it is a structural fact about underspecified questions over messy evidence.", "gasl"),
                _frame(5400, "Classic systems often fail hard; RAG misses remain silent; LLM-only systems can drift.", "GASL instead surfaces local defects, checks them against scope and shape, and uses failures as informative signals.", "gasl", ["SHOW", "INSPECT", "validator"]),
                _frame(5200, "Repair is not decoration.", "It exists to stop one bad step from poisoning later evidence while keeping the run moving toward a better structured answer.", "gasl"),
            ],
        },
        {
            "order": 12,
            "id": "12_answer_views_and_synthesis",
            "stage_type": "answer_board",
            "title": "Answer Views and Final Synthesis",
            "subtitle": "Why evidence organization and answering are separate phases.",
            "frames": [
                _frame(5200, "Raw rows are not answers.", "A correct evidence table is still not the same thing as a user-facing answer.", "gasl"),
                _frame(5400, "Answer views preserve structure before language.", "Ranking, grouping, frontiers, and distributions keep the evidence legible so final synthesis does not have to rediscover the structure from scratch.", "gasl", ["answer views"]),
                _frame(5200, "Final synthesis is where flexibility returns.", "After the evidence has been organized and checked, the LLM can answer in natural language without throwing away the evidence base that made the answer reliable.", "gasl", ["final synthesis"]),
            ],
        },
        {
            "order": 13,
            "id": "13_closing_tharp_wegener",
            "stage_type": "bridge",
            "title": "Closing: From Claim to Compiled Evidence",
            "subtitle": "The point is not only to answer. It is to answer from compiled structure.",
            "frames": [
                _frame(5200, "Wegener's position reminds us that being right is not always enough.", "A system can have a strong intuition and still fail to persuade because the evidence has not been compiled into legible form.", "llm"),
                _frame(5600, "Tharp's position reminds us what compilation does.", "Compilation makes patterns visible, comparable, and difficult to ignore. GASL's command families exist to make that kind of answer-building possible across graph questions.", "gasl"),
                _frame(5200, "That is the whole tutorial thesis.", "GASL is not one fixed pipeline. It is a repairable architecture for gathering, assembling, compiling, validating, and finally answering from structured evidence.", "gasl"),
            ],
        },
    ]
    return scenes


def get_scene(scene_id: str) -> Dict[str, Any] | None:
    for scene in get_compare_scenes():
        if scene["id"] == scene_id:
            return scene
    return None
