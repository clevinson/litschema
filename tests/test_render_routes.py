from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import litschema.webapp.app as webapp
from tests.test_webapp_app import _project_cfg, _write_manifest


def _client(cfg) -> TestClient:
    webapp.app.dependency_overrides[webapp.get_config] = lambda: cfg
    return TestClient(webapp.app)


def teardown_function() -> None:
    webapp.app.dependency_overrides.clear()


def _article(tmp_path, text: str | None = "# T\n\nBody.\n"):
    cfg = _project_cfg(tmp_path)
    _write_manifest(cfg, "a", {"id": "a"})
    if text is not None:
        (cfg.article_store_dir / "a" / "article.md").write_text(text)
    return cfg


def test_rendered_returns_blocks(tmp_path) -> None:
    response = _client(_article(tmp_path)).get("/api/rendered/a")

    assert response.status_code == 200
    assert [b["kind"] for b in response.json()["blocks"]] == ["heading", "paragraph"]


def test_rendered_strips_references_like_markdown_route(tmp_path) -> None:
    cfg = _article(tmp_path, "# T\n\nBody.\n\n## References\n\nSmith 2020.\n")

    blocks = _client(cfg).get("/api/rendered/a").json()["blocks"]

    assert "Smith" not in "".join(b.get("html", "") for b in blocks)


def test_rendered_404_without_markdown(tmp_path) -> None:
    assert _client(_article(tmp_path, None)).get("/api/rendered/a").status_code == 404


def test_rendered_422_when_rendering_fails(tmp_path, monkeypatch) -> None:
    def boom(text):
        raise ValueError("bad markdown")

    monkeypatch.setattr(webapp, "render_blocks", boom)

    response = _client(_article(tmp_path)).get("/api/rendered/a")

    assert response.status_code == 422
    assert "bad markdown" in response.json()["detail"]


def test_figure_is_served(tmp_path) -> None:
    cfg = _article(tmp_path)
    figures = cfg.article_store_dir / "a" / "figures"
    figures.mkdir()
    (figures / "f1.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")

    response = _client(cfg).get("/api/figure/a/f1.png")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


@pytest.mark.parametrize("name", ["..%2Farticle.md", "f1.txt", "%2Fetc%2Fpasswd", "missing.png"])
def test_figure_rejects_anything_but_a_plain_image_name(tmp_path, name) -> None:
    cfg = _article(tmp_path)
    figures = cfg.article_store_dir / "a" / "figures"
    figures.mkdir()
    (figures / "f1.txt").write_text("x")

    assert _client(cfg).get(f"/api/figure/a/{name}").status_code == 404


def test_settings_name_the_project(tmp_path) -> None:
    body = _client(_article(tmp_path)).get("/api/settings").json()

    assert body["project_name"] == tmp_path.name
