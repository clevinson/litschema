from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from litschema.config import LitSchemaConfig
from litschema.ingest import pdf_to_markdown
from litschema.version import installed_version

from .helpers import make_pdf


def _cfg(project: Path) -> LitSchemaConfig:
    return LitSchemaConfig(
        config_path=project / "litschema.yaml",
        project_root=project,
        data_dir=project / "data",
        schema_dir=project / "schema",
        references_dir=project / "references",
        tracking_xlsx=project / "paper_download_tracking.xlsx",
        paper_inbox_dir=project / "papers-inbox",
        static_site_dir=project / "static-site",
        article_store_dir=project / "data" / "papers",
        raw={},
    )


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _assembled(cfg: LitSchemaConfig, article_id: str = "smith-2024") -> Path:
    article_dir = cfg.article_store_dir / article_id
    make_pdf(article_dir / f"{article_id}.pdf")
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": article_id, "filename": f"{article_id}.pdf"})
    )
    return article_dir


@pytest.fixture(scope="module")
def prepared(tmp_path_factory) -> Path:
    """One real conversion shared by the read-only assertions below."""
    project = tmp_path_factory.mktemp("project")
    cfg = _cfg(project)
    article_dir = _assembled(cfg)
    stats = pdf_to_markdown.run(cfg, article_ids=["smith-2024"])
    assert stats["converted"] == 1, stats
    return article_dir


def test_prepare_text_keeps_only_real_figures(prepared: Path) -> None:
    figures = sorted(p.name for p in (prepared / "figures").iterdir())
    # The repeated logo (3 pages) and the 42 px icon are dropped; the
    # 625x417 figure stays.
    assert len(figures) == 1
    import pymupdf

    pix = pymupdf.Pixmap(str(prepared / "figures" / figures[0]))
    assert (pix.width, pix.height) == (625, 417)
    assert not list(prepared.glob(".figures.*"))


def test_prepare_text_rewrites_refs_and_blanks_dropped_images(prepared: Path) -> None:
    md = (prepared / "article.md").read_text()
    refs = re.findall(r"!\[[^\]]*\]\(([^)]*)\)", md)
    figures = sorted(p.name for p in (prepared / "figures").iterdir())
    assert refs == [f"figures/{name}" for name in figures]
    assert str(prepared) not in md


def test_prepare_text_strips_mark_and_drops_page_furniture(prepared: Path) -> None:
    md = (prepared / "article.md").read_text()
    assert "Shaded field value 42" in md
    assert "<mark>" not in md and "</mark>" not in md
    assert "Running footer" not in md
    assert "|A|7.1|0.4|" in md


def test_prepare_text_writes_conversion_record(prepared: Path) -> None:
    import pymupdf
    import pymupdf4llm

    record = json.loads((prepared / "prepared-text.json").read_text())
    assert set(record) == {
        "version", "tool", "tool_version", "pymupdf_version", "options", "pdf_sha256",
        "text_sha256", "figures", "litschema_version", "created_at",
    }
    assert record["version"] == 1
    assert record["tool"] == "pymupdf4llm"
    assert record["tool_version"] == pymupdf4llm.__version__
    assert record["pymupdf_version"] == pymupdf.VersionBind
    assert record["options"] == {
        "use_ocr": False,
        "header": False,
        "footer": False,
        "write_images": True,
        "image_format": "png",
        "dpi": 150,
        "drop_figure_repeats_at": 3,
        "min_figure_width_px": 150,
        "min_figure_height_px": 100,
    }
    assert record["pdf_sha256"] == _sha(prepared / "smith-2024.pdf")
    assert record["text_sha256"] == _sha(prepared / "article.md")
    assert record["figures"] == [
        {"name": p.name, "sha256": _sha(p)} for p in sorted((prepared / "figures").iterdir())
    ]
    assert record["litschema_version"] == installed_version()
    assert record["created_at"].endswith("+00:00")


def test_prepare_text_force_replaces_the_figures_dir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    article_dir = _assembled(cfg)
    stale = article_dir / "figures" / "stale.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")

    stats = pdf_to_markdown.run(cfg, article_ids=["smith-2024"], force=True)

    assert stats["converted"] == 1
    assert not stale.exists()
    assert len(list((article_dir / "figures").iterdir())) == 1


def test_prepare_text_flat_output_writes_sibling_figures_and_record(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    article_dir = _assembled(cfg)
    out = tmp_path / "flat"

    stats = pdf_to_markdown.run(cfg, article_ids=["smith-2024"], output_dir=out)

    assert stats["converted"] == 1
    figures = sorted(p.name for p in (out / "smith-2024-figures").iterdir())
    assert len(figures) == 1
    md = (out / "smith-2024.md").read_text()
    assert f"![](smith-2024-figures/{figures[0]})" in md
    record = json.loads((out / "smith-2024.prepared-text.json").read_text())
    assert record["text_sha256"] == _sha(out / "smith-2024.md")
    assert not (article_dir / "article.md").exists()
    assert not (article_dir / "figures").exists()
    assert not (article_dir / "prepared-text.json").exists()


def test_prepare_text_falls_back_to_canonical_pdf_for_a_stale_filename(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.paper_inbox_dir.mkdir(parents=True)
    article_dir = _assembled(cfg)
    (article_dir / "article-metadata.json").write_text(
        json.dumps({"id": "smith-2024", "filename": "old-archive-name.pdf"})
    )

    stats = pdf_to_markdown.run(cfg, article_ids=["smith-2024"])

    assert stats["converted"] == 1, stats
    record = json.loads((article_dir / "prepared-text.json").read_text())
    assert record["pdf_sha256"] == _sha(article_dir / "smith-2024.pdf")


def test_postprocess_markdown_rewrites_blanks_and_strips() -> None:
    md = "\n".join(
        [
            "Intro <mark>shaded</mark> text",
            "![](/abs/dir with (parens)/x.pdf-0001-02.png)",
            "![alt](rel/x.pdf-0002-03.png)",
            "![](elsewhere/unknown.png)",
            "end",
        ]
    )

    out = pdf_to_markdown.postprocess_markdown(
        md,
        kept={"x.pdf-0002-03.png"},
        dropped={"x.pdf-0001-02.png"},
        figures_ref="figures",
    )

    assert out.split("\n") == [
        "Intro shaded text",
        "",
        "![](figures/x.pdf-0002-03.png)",
        "![](elsewhere/unknown.png)",
        "end",
    ]


def test_figures_sha256_is_order_independent() -> None:
    a = {"name": "a.png", "sha256": "sha256:01"}
    b = {"name": "b.png", "sha256": "sha256:02"}
    expected = "sha256:" + hashlib.sha256(b"a.png:sha256:01\nb.png:sha256:02\n").hexdigest()

    assert pdf_to_markdown.figures_sha256([b, a]) == expected
    assert pdf_to_markdown.figures_sha256([a, b]) == expected
