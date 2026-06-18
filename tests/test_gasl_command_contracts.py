from gasl.commands.declare import DeclareHandler
from gasl.commands.debug import DebugHandler
from gasl.commands.process import ProcessHandler
from gasl.micro_actions import MicroActionFramework
from gasl.process_runtime import CandidateSelection
from gasl.state import ContextStore, StateStore
from gasl.types import Command, ExecutionResult


class StaticLLM:
    def __init__(self, response: str):
        self.response = response

    def call(self, _prompt: str) -> str:
        return self.response


def test_debug_handler_can_handle_show_command_object():
    handler = DebugHandler(StateStore(), ContextStore(), None)
    command = Command(command_type="SHOW", args={"variable": "x"}, raw_text="SHOW x", line_number=1)
    assert handler.can_handle(command) is True


def test_declare_reuses_existing_same_type_variable_without_clearing_data():
    state = StateStore()
    handler = DeclareHandler(state, ContextStore(), None)
    state.declare_variable("reported_table", "LIST", "reported rows")
    state.get_variable("reported_table")["items"] = [{"id": "row-1"}]

    command = Command(
        command_type="DECLARE",
        args={
            "variable": "reported_table",
            "type": "LIST",
            "description": "same table",
        },
        raw_text='DECLARE reported_table AS LIST WITH_DESCRIPTION "same table"',
        line_number=1,
    )

    result = handler.execute(command)

    assert result.status == "success"
    assert result.data["reused"] is True
    assert result.provenance[0].extraction["method"] == "reuse_variable"
    assert state.get_variable("reported_table")["items"] == [{"id": "row-1"}]
    assert (
        state.get_variable("reported_table")["_meta"]["description"]
        == "same table"
    )


def test_process_normalized_items_returns_rows_for_filter_and_process():
    filter_result = {
        "filtered_items": [{"id": "n1"}],
        "excluded_items": [{"id": "n2"}],
        "processing_method": "filter",
    }
    process_result = {
        "processed_items": [{"id": "n3", "value": 1}],
        "processing_method": "process",
    }
    assert ProcessHandler._normalized_items(filter_result) == [{"id": "n1"}]
    assert ProcessHandler._normalized_items(process_result) == [{"id": "n3", "value": 1}]


def test_process_failure_envelope_flags_misaligned_probe():
    handler = ProcessHandler(StateStore(), ContextStore(), llm_func=None)

    failure = handler._build_process_failure_envelope(
        data=[{"id": "a"}],
        query="Build a table.",
        instruction="Normalize rows into table columns",
        incoming_contract={"payload_kind": "selected_rows"},
        probe_result={
            "processing_method": "filter",
            "filtered_items": [{"id": "a"}],
        },
        stage="probe",
        alignment={
            "aligned": False,
            "alignment_reason": "The probe filtered raw nodes.",
        },
    )

    assert failure is not None
    assert failure.error_type == "misaligned_output"
    assert failure.output_count == 1
    assert "raw nodes" in failure.error_message


def test_empty_single_batch_process_does_not_overwrite_existing_rows():
    state = StateStore()
    context = ContextStore()
    state.declare_variable("reported_table", "LIST", "reported rows")
    state.get_variable("reported_table")["items"] = [{"id": "existing"}]
    context.set("reported_table", [{"id": "existing"}])

    handler = ProcessHandler(
        state,
        context,
        llm_func=StaticLLM('{"processed_items": []}'),
    )
    command = Command(
        command_type="PROCESS",
        args={"variable": "reported_table", "instruction": "derive table rows"},
        raw_text="PROCESS reported_table with instruction: derive table rows",
        line_number=1,
    )

    result = handler._execute_single_batch(
        [{"id": "input"}],
        "derive table rows",
        command,
        "reported_table",
        subtype="field_derivation",
    )

    assert result.status == "empty"
    assert state.get_variable("reported_table")["items"] == [{"id": "existing"}]
    assert context.get("reported_table") == [{"id": "existing"}]


def test_empty_microaction_process_does_not_overwrite_existing_rows():
    class EmptyMicroActions:
        llm_func = None

        def execute_command_with_batching(self, **_kwargs):
            return ExecutionResult(
                command="",
                status="empty",
                data={"processed_items": []},
                count=0,
            )

    rows = [{"id": f"row-{i}"} for i in range(25)]
    state = StateStore()
    context = ContextStore()
    state.declare_variable("reported_table", "LIST", "reported rows")
    state.get_variable("reported_table")["items"] = rows
    context.set("reported_table", rows)

    handler = ProcessHandler(
        state,
        context,
        llm_func=StaticLLM("{}"),
        micro_framework=EmptyMicroActions(),
    )
    handler.PROBE_THRESHOLD = 100
    handler._interpret_process_context = lambda *args, **kwargs: None
    handler.selector.select = lambda data, **_kwargs: CandidateSelection(
        probe_items=list(data[:20]),
        final_items=list(data),
        diagnostics={"strategy": "test"},
    )
    command = Command(
        command_type="PROCESS",
        args={"variable": "reported_table", "instruction": "derive table rows"},
        raw_text="PROCESS reported_table with instruction: derive table rows",
        line_number=1,
    )

    result = handler.execute(command)

    assert result.status == "empty"
    assert state.get_variable("reported_table")["items"] == rows
    assert context.get("reported_table") == rows


def test_microaction_process_preserves_synthetic_rows_without_original_id_match():
    framework = MicroActionFramework(
        StaticLLM(
            """
            {
              "processed_items": [
                {
                  "id": "row_1",
                  "disease": "Influenza",
                  "pathogen": "Influenza A virus",
                  "r0_value": "1.3"
                }
              ]
            }
            """
        )
    )

    result = framework._execute_single_batch(
        [{"id": "input_1", "name": "raw path"}],
        "PROCESS",
        "normalize into disease_id50_r0_table rows",
    )

    assert result.status == "success"
    assert result.data["processed_items"] == [
        {
            "id": "row_1",
            "disease": "Influenza",
            "pathogen": "Influenza A virus",
            "r0_value": "1.3",
        }
    ]


def test_microaction_process_drops_rows_for_sibling_table():
    framework = MicroActionFramework(
        StaticLLM(
            """
            {
              "processed_items": [
                {
                  "id": "row_1",
                  "table_name": "country_r0_table",
                  "country": "Sri Lanka"
                },
                {
                  "id": "row_2",
                  "table_name": "disease_id50_r0_table",
                  "disease": "COVID-19"
                }
              ]
            }
            """
        )
    )

    result = framework._execute_single_batch(
        [{"id": "input_1", "name": "raw path"}],
        "PROCESS",
        "normalize into disease_id50_r0_table rows",
        target_variable="disease_id50_r0_table",
    )

    assert result.status == "success"
    assert result.data["processed_items"] == [
        {
            "id": "row_2",
            "table_name": "disease_id50_r0_table",
            "disease": "COVID-19",
        }
    ]


def test_process_single_batch_drops_rows_for_sibling_table():
    state = StateStore()
    context = ContextStore()
    state.declare_variable("source_rows", "LIST", "source rows")
    state.get_variable("source_rows")["items"] = [{"id": "source"}]
    context.set("source_rows", [{"id": "source"}])

    handler = ProcessHandler(
        state,
        context,
        llm_func=StaticLLM(
            """
            {
              "processed_items": [
                {
                  "id": "row_1",
                  "table_name": "country_r0_table",
                  "country": "Sri Lanka"
                },
                {
                  "id": "row_2",
                  "table_name": "disease_id50_r0_table",
                  "disease": "COVID-19"
                }
              ]
            }
            """
        ),
    )
    command = Command(
        command_type="PROCESS",
        args={
            "variable": "source_rows",
            "instruction": "normalize rows",
            "target_variable": "disease_id50_r0_table",
        },
        raw_text="PROCESS source_rows with instruction: normalize rows AS disease_id50_r0_table",
        line_number=1,
    )

    result = handler._execute_single_batch(
        [{"id": "source"}],
        "normalize rows",
        command,
        "disease_id50_r0_table",
        subtype="field_derivation",
    )

    assert result.status == "success"
    rows = state.get_variable("disease_id50_r0_table")["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == "row_2"
    assert rows[0]["table_name"] == "disease_id50_r0_table"
    assert rows[0]["disease"] == "COVID-19"


def test_microaction_process_prompt_allows_synthetic_table_rows():
    framework = MicroActionFramework(StaticLLM("{}"))

    prompt = framework._create_process_prompt(
        [{"id": "input_1", "name": "raw path"}],
        "normalize rows with exact columns disease, r0_value",
    )

    assert "synthetic stable row IDs" in prompt
    assert "exact requested table columns" in prompt
    assert "it must be the target table" in prompt


def test_microaction_batch_failure_does_not_commit_stale_or_partial_rows(tmp_path):
    class SequenceLLM:
        def __init__(self):
            self.responses = [
                "not json",
                '{"processed_items": [{"id": "synthetic", "disease": "MERS"}]}',
            ]

        def call(self, _prompt: str) -> str:
            return self.responses.pop(0)

    state = StateStore()
    context = ContextStore()
    state.declare_variable("reported_table", "LIST", "reported rows")
    state.get_variable("reported_table")["items"] = [{"id": "existing"}]
    context.set("reported_table", [{"id": "existing"}])

    framework = MicroActionFramework(
        SequenceLLM(),
        state,
        context,
        job_id="test-job",
        checkpoint_dir=str(tmp_path),
    )
    framework._save_batch_result(
        "reported_table",
        0,
        [{"id": "stale", "category": "old"}],
    )

    result = framework.execute_command_with_batching(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "PROCESS",
        "normalize exact columns disease",
        batch_size=2,
        target_variable="reported_table",
    )

    assert result.status == "error"
    assert result.error_message == "PROCESS completed 1/2 batches"
    assert state.get_variable("reported_table")["items"] == [{"id": "existing"}]
    assert context.get("reported_table") == [{"id": "existing"}]


def test_microaction_process_uses_small_default_batches():
    framework = MicroActionFramework(StaticLLM("{}"))
    rows = [{"id": f"row_{i}", "description": "compact row"} for i in range(80)]

    table_batch_size = framework._calculate_optimal_batch_size(
        rows,
        "normalize each input into country_r0_table rows with deduplication_key",
        target_variable="country_r0_table",
    )

    assert table_batch_size <= 15
    assert framework._calculate_optimal_batch_size(
        rows,
        "classify compact rows",
        target_variable="scratch_rows",
    ) <= 15


def test_process_requested_top_k_parses_words_and_numbers():
    assert ProcessHandler._requested_top_k("select the top three entity_name values") == 3
    assert ProcessHandler._requested_top_k("return the top 5 items as csv") == 5
    assert ProcessHandler._requested_top_k("select leading values") is None


def test_process_stops_after_probe_for_ranked_top_k_materialization():
    ranked_rows = [
        {"group_id": "group_1", "group_name": "SYSTEMATIC REVIEW", "count": 18, "rank": 1},
        {"group_id": "group_2", "group_name": "TRACER GAS RELEASE EXPERIMENTS", "count": 16, "rank": 2},
        {"group_id": "group_3", "group_name": "TABLE 2", "count": 10, "rank": 3},
        {"group_id": "group_4", "group_name": "CASE REPORT", "count": 7, "rank": 4},
    ]
    probe_result = {
        "filtered_items": [
            {"id": "group_1", "name": "SYSTEMATIC REVIEW"},
            {"id": "group_2", "name": "TRACER GAS RELEASE EXPERIMENTS"},
            {"id": "group_3", "name": "TABLE 2"},
        ],
        "processing_method": "filter",
    }
    interpretation = {
        "label_field": "group_name",
        "metric_field": "count",
        "ordered": True,
        "order_basis": "rows already sorted by count descending",
        "order_field": "count",
        "order_direction": "desc",
        "scope": "current_rows_only",
        "output_contract": "Materialize exactly the top 3 rows in current order.",
        "confidence": 0.9,
    }
    assert ProcessHandler._should_stop_after_probe(
        ranked_rows,
        "select the top three entity_name values and format as a comma-separated list",
        probe_result,
        interpretation,
    ) is True


def test_parse_interpretation_response_returns_structured_contract():
    raw = """
    {
      "label_field": "data.entity_name",
      "metric_field": "count",
      "ordered": true,
      "order_basis": "rows are already sorted by descending count",
      "order_field": "count",
      "order_direction": "desc",
      "scope": "current_rows_only",
      "output_contract": "Use the current rows only and preserve order.",
      "confidence": 0.82
    }
    """
    parsed = ProcessHandler._parse_interpretation_response(raw)
    assert parsed["label_field"] == "data.entity_name"
    assert parsed["order_field"] == "count"
    assert parsed["ordered"] is True
    assert parsed["confidence"] == 0.82
