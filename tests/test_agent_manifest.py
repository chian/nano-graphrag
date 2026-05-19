import json
from pathlib import Path

from nano_graphrag.prompt_system import QueryAwarePromptSystem
from gasl.prompt_observations import PromptObservationLogger


def test_prompt_system_loads_agent_manifest():
    ps = QueryAwarePromptSystem(prompts_dir="prompts")
    manifest = ps.get_agent_manifest()
    assert manifest["agent_name"] == "gasl"
    surface = ps.get_prompt_surface("plan_generation")
    assert surface is not None
    assert surface["surface_id"] == "planner"
    assert surface["skeleton_file"] == "prompts/plan_generation.txt"


def test_prompt_observation_logger_writes_manifest_snapshot(tmp_path: Path):
    ps = QueryAwarePromptSystem(prompts_dir="prompts")
    logger = PromptObservationLogger(tmp_path, job_id="q001")
    manifest_path = logger.write_manifest(ps.get_agent_manifest())
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_path.name == "agent_manifest.snapshot.json"
    assert data["manifest_version"] == "1"
