from pathlib import Path

from visualization.server import create_app


VIEWER_TEMPLATE = Path(__file__).resolve().parents[1] / "visualization" / "templates" / "viewer.html"


def test_password_unlock_is_not_persisted_in_browser_storage():
    html = VIEWER_TEMPLATE.read_text(encoding="utf-8")

    assert 'id="unlockInput"' in html
    assert 'type="text"' in html
    assert 'autocomplete="off"' in html
    assert "data-1p-ignore" in html
    assert "data-lpignore" in html
    assert "readonly onfocus=\"enableUnlockInput()\"" in html
    assert 'localStorage.removeItem(\'nano_graphrag_password\')' in html
    assert 'id="passwordInput"' not in html
    assert 'type="password"' not in html
    assert "_LS_KEY_PASSWORD" not in html
    assert "localStorage.setItem(_LS_KEY_PASSWORD" not in html


def test_viewer_route_disables_browser_cache():
    client = create_app().test_client()

    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
