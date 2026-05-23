import json

from gasl.parser import GASLParser
from gasl.state import ContextStore, StateStore
from gasl.step_compiler import GASLStepCompiler


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.model = "test-model"
        self.last_prompt = None

    def call(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.responses.pop(0)


def _declare_list(state_store: StateStore, name: str, rows: list[dict]):
    state_store.declare_variable(name, "LIST")
    if rows:
        state_store.update_variable(name, rows)


def test_step_compiler_accepts_materialized_nonempty_inputs():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    compiler = GASLStepCompiler(FakeLLM([]), GASLParser())
    cmd = GASLParser().parse_command("SELECT controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "accept"
    assert result.command.raw_text == cmd.raw_text


def test_step_compiler_rewrites_unavailable_source_to_materialized_symbol():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "rewrite",
                    "typed_command": {
                        "command_type": "SELECT",
                        "args": {
                            "source": "controls",
                            "fields": "id",
                            "target": "top_controls",
                            "distinct": False,
                        },
                    },
                    "reason": "replace unavailable source with materialized rows",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    cmd = GASLParser().parse_command("SELECT future_controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "rewrite"
    assert result.command.command_type == "SELECT"
    assert result.command.args["source"] == "controls"
    assert result.rendered_command == "SELECT controls FIELDS id AS top_controls"


def test_step_compiler_blocks_current_output_as_input():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "upstream_repair_needed",
                    "typed_command": {},
                    "reason": "cannot use current output as input",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    cmd = GASLParser().parse_command("SELECT top_controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "upstream_repair_needed"


def test_step_compiler_accepts_show_for_materialized_symbol():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "top_controls", [{"id": 1}])
    compiler = GASLStepCompiler(FakeLLM([]), GASLParser())
    cmd = GASLParser().parse_command("SHOW top_controls limit 3")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "accept"


def test_step_compiler_supports_two_command_patch_with_sequential_validation():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "patch_two",
                    "commands": [
                        "SELECT controls FIELDS id AS temp_controls",
                        "SELECT temp_controls FIELDS id AS top_controls",
                    ],
                    "reason": "materialize a temp variable, then write the intended output",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    cmd = GASLParser().parse_command("SELECT future_controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "patch_two"
    assert len(result.commands) == 2
    assert result.rendered_commands == [
        "SELECT controls FIELDS id AS temp_controls",
        "SELECT temp_controls FIELDS id AS top_controls",
    ]


def test_step_compiler_prompt_includes_prev_next_and_contract_context():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    state.set_variable_contract("controls", {"row_schema": ["id"], "grain_type": "node"})
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "upstream_repair_needed",
                    "commands": [],
                    "reason": "no legal patch",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    previous_command = GASLParser().parse_command("SELECT controls FIELDS id AS seeded_controls")
    command = GASLParser().parse_command("SELECT future_controls FIELDS id AS top_controls")
    next_command = GASLParser().parse_command("PROCESS top_controls with summarize AS answer_rows")
    compiler.compile_step(
        command=command,
        query="which control ranks highest",
        state_store=state,
        context_store=ctx,
        history=[{"step_id": "p1-step-1", "status": "error", "error_message": "missing producer"}],
        previous_command=previous_command,
        next_command=next_command,
    )
    prompt = llm.last_prompt or ""
    assert "Previous command:\nSELECT controls FIELDS id AS seeded_controls" in prompt
    assert "Next command:\nPROCESS top_controls with summarize AS answer_rows" in prompt
    assert '"declared_type": "LIST"' in prompt
    assert '"grain_type": "node"' in prompt


def test_step_compiler_reject_reason_explains_unavailable_placeholder():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "rewrite",
                    "commands": ["SELECT materialized_symbol FIELDS id AS top_controls"],
                    "reason": "try a generic rewrite",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    cmd = GASLParser().parse_command("SELECT future_controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "reject"
    assert "materialized_symbol" in result.reason
    assert "no materialized variable with that name exists in local scope" in result.reason


def test_step_compiler_reject_reason_explains_current_output_reuse():
    state = StateStore()
    ctx = ContextStore()
    _declare_list(state, "controls", [{"id": 1}])
    llm = FakeLLM(
        [
            json.dumps(
                {
                    "action": "rewrite",
                    "commands": ["SELECT top_controls FIELDS id AS top_controls"],
                    "reason": "retain same symbol",
                }
            )
        ]
    )
    compiler = GASLStepCompiler(llm, GASLParser())
    cmd = GASLParser().parse_command("SELECT future_controls FIELDS id AS top_controls")
    result = compiler.compile_step(
        command=cmd,
        query="q",
        state_store=state,
        context_store=ctx,
        history=[],
    )
    assert result.action == "reject"
    assert "reads its own output symbol 'top_controls' as an input" in result.reason
