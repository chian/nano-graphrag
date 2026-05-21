import json

from gasl.parser import GASLParser
from gasl.state import ContextStore, StateStore
from gasl.step_compiler import GASLStepCompiler


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.model = "test-model"

    def call(self, prompt: str) -> str:
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
