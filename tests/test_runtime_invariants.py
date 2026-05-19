from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_invariants_doc_states_general_system_identity():
    text = (ROOT / "docs" / "RUNTIME_INVARIANTS.md").read_text(encoding="utf-8").lower()
    assert "general question-answering system over knowledge graphs" in text
    assert "canonical graph abstraction keys" in text
    assert "state-driven" in text


def test_runtime_invariant_checker_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_runtime_invariants.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_repo_local_skill_exists_and_is_specific():
    skill = ROOT / ".claude" / "skills" / "gasl-general-qa" / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "GASL is a general QA system over knowledge graphs" in text
    assert "canonical engine slots" in text
    assert "Do not hard-code domain fields" in text
