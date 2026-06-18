from gasl.answer_layer.utils import candidate_group_fields, distinct_dimension_fields
from gasl.commands.data_transform import DataTransformHandler
from gasl.commands.multi_var import MultiVarHandler
from gasl.commands.select import SelectHandler
from gasl.parser import GASLParser
from gasl.state import ContextStore, StateStore
from gasl.state_manager import StateManager


def _setup_manager():
    state = StateStore()
    ctx = ContextStore()
    manager = StateManager(state, ctx)
    return state, ctx, manager


def test_select_preserves_row_id_when_projection_drops_source_keys():
    state, ctx, manager = _setup_manager()
    rows = [
        {"id": "n1", "entity_name": "Alpha"},
        {"id": "n2", "entity_name": "Beta"},
    ]
    manager.store_variable_data(
        "controls",
        rows,
        contract={
            "payload_kind": "nodes",
            "label_field": "entity_name",
            "grain_type": "node",
            "grain_keys": ["id"],
            "multiplicity_preserved": True,
        },
    )
    handler = SelectHandler(state, ctx, manager)
    command = GASLParser().parse_command("SELECT controls FIELDS src_id AS selected_controls")
    result = handler.execute(command)

    assert result.status == "success"
    assert result.contract["grain_type"] == "row"
    assert result.contract["grain_keys"] == ["row_id"]
    assert "src_id" in result.contract["row_schema"]
    assert "row_id" in result.contract["row_schema"]
    assert len({row["row_id"] for row in result.data}) == 2


def test_aggregate_emits_group_identity_and_keeps_context_synced():
    state, ctx, manager = _setup_manager()
    handler = DataTransformHandler(state, ctx, llm_func=None, state_manager=manager)
    rows = [
        {"source_id": "c1", "value": 1},
        {"source_id": "c1", "value": 2},
        {"source_id": "c2", "value": 3},
    ]
    manager.store_variable_data(
        "validation_evidence",
        rows,
        contract={
            "payload_kind": "selected_rows",
            "label_field": "source_id",
            "grain_type": "row",
            "grain_keys": ["row_id"],
            "multiplicity_preserved": True,
        },
    )
    state.declare_variable("validation_groups", "LIST", "grouped validation rows")

    command = GASLParser().parse_command(
        "AGGREGATE validation_evidence by source_id with count AS validation_groups"
    )
    result = handler.execute(command)

    assert result.status == "success"
    assert ctx.has("validation_groups") is True
    assert result.contract["grain_type"] == "group"
    assert result.contract["grain_keys"] == ["group_key"]
    assert all("row_id" in row for row in result.data)


def test_collapse_keeps_missing_group_keys_separate():
    state, ctx, manager = _setup_manager()
    handler = DataTransformHandler(state, ctx, llm_func=None, state_manager=manager)
    rows = [
        {"label": "A", "value": 1},
        {"label": "B", "value": 2},
    ]
    manager.store_variable_data(
        "candidate_rows",
        rows,
        contract={
            "payload_kind": "selected_rows",
            "grain_type": "row",
            "grain_keys": ["row_id"],
            "multiplicity_preserved": True,
        },
    )
    state.declare_variable("collapsed_rows", "LIST", "collapsed rows")

    command = GASLParser().parse_command(
        "COLLAPSE candidate_rows BY deduplication_key COUNT AS weight AS collapsed_rows"
    )
    result = handler.execute(command)

    assert result.status == "success"
    assert result.count == 2
    assert {row["weight"] for row in result.data} == {1}
    assert len({row["deduplication_key"] for row in result.data}) == 2
    assert all(
        str(row["deduplication_key"]).startswith("__missing_key__")
        for row in result.data
    )


def test_join_emits_join_identity_and_stores_context():
    state, ctx, manager = _setup_manager()
    handler = MultiVarHandler(state, ctx, manager)
    left_rows = [{"source_id": "c1", "label": "A"}, {"source_id": "c2", "label": "B"}]
    right_rows = [{"source_id": "c1", "score": 2}, {"source_id": "c3", "score": 5}]
    manager.store_variable_data(
        "left_rows",
        left_rows,
        contract={
            "payload_kind": "selected_rows",
            "grain_type": "row",
            "grain_keys": ["row_id"],
            "multiplicity_preserved": True,
        },
    )
    manager.store_variable_data(
        "right_rows",
        right_rows,
        contract={
            "payload_kind": "selected_rows",
            "grain_type": "row",
            "grain_keys": ["row_id"],
            "multiplicity_preserved": True,
        },
    )
    state.declare_variable("joined_rows", "LIST", "joined rows")

    command = GASLParser().parse_command("JOIN left_rows with right_rows on source_id AS joined_rows")
    result = handler.execute(command)

    assert result.status == "success"
    assert ctx.has("joined_rows") is True
    assert result.contract["grain_type"] == "join"
    assert result.contract["grain_keys"] == ["left_row_id", "right_row_id", "source_id"]
    assert all("row_id" in row for row in result.data)


def test_answer_layer_field_pickers_ignore_identity_bookkeeping_fields():
    rows = [
        {"row_id": "r1", "group_name": "Alpha", "measure": "m1"},
        {"row_id": "r2", "group_name": "Beta", "measure": "m1"},
        {"row_id": "r3", "group_name": "Gamma", "measure": "m2"},
    ]
    groups = candidate_group_fields(rows, meta={"label_field": "group_name"})
    dims = distinct_dimension_fields(rows)

    assert "row_id" not in groups
    assert "row_id" not in dims
