"""Browser flow check for `litschema verify` (not part of the pytest suite).

Drives the auditing workflow and asserts BOTH halves of every action: what
lands in review.json, and what the user actually sees. The second half matters
— a stale version-1 key once left every field rendering as unreviewed while the
writes succeeded with 200 OK, so file-only assertions passed while the app was
unusable.

It runs against a *copy* of a fixture project in a temp directory, and starts
its own server against that copy. Nothing outside the temp directory is read or
written. An earlier version deleted `review.json` across every run of a
hard-coded article in whatever project it was pointed at, while documenting
itself as safe to run against a real one; review work is not reproducible and
deleting it is not recoverable.

Needs playwright, which is not a project dependency, so it runs on demand:

    uv run --with playwright python tests/browser_verify_flow.py
    uv run --with playwright python tests/browser_verify_flow.py --project <dir>
    uv run --with playwright python tests/browser_verify_flow.py --keep  # leave the copy

Targets are derived from whatever the project contains rather than hard-coded,
so pointing it at another project exercises that project's documents.

This file is where the verifier's *behavioural* claims are pinned.
`tests/test_verifier_static.py` asserts that certain strings appear in
index.html, which cannot detect any of the defects it nominally guards — it
passed through a v1 status key that made every field render unreviewed, a
temporal dead zone that killed the settings button, and a routing bug that sent
`?view=review` to the data view. Claims about what the app *does* belong here;
claims about what it *contains* (a removed surface staying removed) can stay
there.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = REPO_ROOT / "tests" / "fixtures" / "projects" / "verifier_flow"

failures: list[str] = []
page_errors: list[str] = []
# Set while the flow is deliberately aborting requests to prove that failures
# get reported. Errors recorded inside that window are ours, not the page's.
injecting_failures = False


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


# ── isolated project + server ────────────────────────────────────────────────


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_until_up(base: str, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{base}/api/articles", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


class Harness:
    """A throwaway copy of a project, served by its own `litschema verify`."""

    def __init__(self, source: Path, keep: bool) -> None:
        self.source = source
        self.keep = keep
        self.tmp = Path(tempfile.mkdtemp(prefix="litschema-flow-"))
        self.project = self.tmp / source.name
        shutil.copytree(source, self.project)
        is_default = source.resolve() == DEFAULT_PROJECT.resolve()
        self.render_article = self._add_render_article() if is_default else None
        self.graded_article = self._add_grade() if is_default else None
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.server: subprocess.Popen | None = None
        self.cfg = self._isolated_config()

    def _isolated_config(self):
        """The copy's config, once it is proven to stay inside the copy.

        Copying a directory does not isolate a project whose `litschema.yaml`
        names absolute paths: the copied config still points the verifier at
        the original article store, and this flow would write reviews there.
        Refuse rather than damage — the whole reason this runs against a copy
        is that review work cannot be recovered.
        """
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from litschema.config import load_config

        cfg = load_config(self.project / "litschema.yaml", reload=True)
        root = self.project.resolve()
        escaping = {
            name: path
            for name, path in (
                ("project_root", cfg.project_root),
                ("data_dir", cfg.data_dir),
                ("article_store_dir", cfg.article_store_dir),
                ("schema_dir", cfg.schema_dir),
            )
            if not path.resolve().is_relative_to(root)
        }
        if escaping:
            listed = "\n  ".join(f"{name}: {path}" for name, path in sorted(escaping.items()))
            # Constructed before the caller's try/finally, so clean up here.
            shutil.rmtree(self.tmp, ignore_errors=True)
            raise SystemExit(
                "refusing to run: this project's config names paths outside the "
                f"temporary copy, so the flow would write to the real project.\n  {listed}\n"
                "Use relative paths in litschema.yaml, or run against a copy you made."
            )
        return cfg

    def _add_render_article(self) -> str:
        """An article whose prepared text is a converter table, cited by row.

        Built from the okafor fixture's run so it matches the fixture schema.
        A `<br>` line is appended after the table for the escaping check.
        """
        papers = self.project / "data" / "papers"
        src = papers / "okafor-2023-biochar-trial"
        article_id = "malecka-2014-tillage-ph"
        dest = papers / article_id
        shutil.copytree(src, dest)
        text = (REPO_ROOT / "tests" / "fixtures" / "render" / "malecka-p4l128.md").read_text()
        (dest / "article.md").write_text(text.rstrip("\n") + "\n\nMeans of four<br>replicates.\n")
        run = dest / "extraction-runs" / "01FLOWRUN0000000000000000"
        meta = json.loads((dest / "article-metadata.json").read_text())
        meta["id"] = article_id
        meta["bib_metadata"]["title"] = "Tillage effects on soil pH"
        (dest / "article-metadata.json").write_text(json.dumps(meta, indent=2))
        extraction = json.loads((run / "agent-extraction.json").read_text())
        extraction.update(article_id=article_id, site_name="Nonexistent Farm Station",
                          mean_annual_temperature_c=7.56)
        (run / "agent-extraction.json").write_text(json.dumps(extraction, indent=2))
        mp_line = next(i for i, line in enumerate(text.splitlines(), 1) if line.startswith("|MP|"))
        reasoning = {
            "confidence": 0.5,
            "confidence_reasoning": "flow fixture",
            "fields": [
                {"path": ".mean_annual_temperature_c", "source_lines": f"L{mp_line}", "value": "7.56"},
                {"path": ".site_name", "source_lines": "L9", "value": "Nonexistent Farm Station"},
            ],
        }
        (run / "agent-reasoning.json").write_text(json.dumps(reasoning, indent=2))
        run_meta = json.loads((run / "run.json").read_text())
        run_meta["article_id"] = article_id
        (run / "run.json").write_text(json.dumps(run_meta, indent=2))
        return article_id

    def _add_grade(self) -> str:
        """A current grade for the okafor run: one unsupported, one partial row, one can't verify."""
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from litschema.articles import article_files
        from litschema.config import load_config
        from litschema.grading import input_hashes, write_grade
        from litschema.runs import active_run

        article_id = "okafor-2023-biochar-trial"
        cfg = load_config(self.project / "litschema.yaml", reload=True)
        run = active_run(article_files(cfg, article_id))
        notes = {
            ".site_name": "Site named in the methods section.",
            ".measurements[0]": "Depth and unit read from Table 2.",
        }
        reasoning = json.loads(run.reasoning.read_text())
        for entry in reasoning["fields"]:
            if entry["path"] in notes:
                entry["reasoning"] = notes[entry["path"]]
        run.reasoning.write_text(json.dumps(reasoning, indent=2))
        verdicts = {
            "site_name": ("supported", "L5 names the Nsukka Research Farm."),
            "replicates": ("unsupported", "L9 gives four replicates, not three."),
            "tillage": ("cannot_verify", "The tillage system is only shown in a figure."),
            "measurements[0]": ("partial", "The depth range is inferred from the table caption."),
        }
        write_grade(run, {
            "version": 1,
            "grade_id": "01FLOWGRADE00000000000000",
            "article_id": article_id,
            "run_id": run.run_id,
            "created_at": "2026-09-28T00:00:00+00:00",
            "grader": {"harness": "claude-code", "model": "claude-flow-1",
                       "requested_model": "claude-flow-1", "rubric_sha256": "sha256:flow"},
            "inputs": input_hashes(run),
            "fields": [
                {"path": path, "verdict": verdict, "confidence": 0.8, "reasoning": reason}
                for path, (verdict, reason) in verdicts.items()
            ],
            "ungraded": [],
            "usage": {},
        })
        return article_id

    def start(self) -> None:
        self.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "litschema.cli",
                "--config",
                str(self.project / "litschema.yaml"),
                "verify",
                "--port",
                str(self.port),
                # Headless: this flow drives its own Chromium. Without it,
                # every run popped a real browser window on the user's desktop.
                "--no-browser",
            ],
            cwd=REPO_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        if not wait_until_up(self.base):
            raise SystemExit(f"verify did not come up on {self.base}")

    def stop(self) -> None:
        if self.server is not None:
            self.server.terminate()
            try:
                self.server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server.kill()
        if self.keep:
            print(f"\n[kept] {self.project}")
        else:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def stored(self, article: str) -> dict:
        """What landed on disk for this article's *active* run.

        Resolved through active-run.json rather than by globbing and taking the
        first hit, which is unordered and can name an inactive run.
        """
        # Through the project's configured store, not a hard-coded `data/papers`
        # — a project may put its articles somewhere else, and this would then
        # silently report "no reviews" for every assertion.
        pointer = self.cfg.article_store_dir / article / "active-run.json"
        if not pointer.is_file():
            return {}
        run_id = json.loads(pointer.read_text())["run_id"]
        review = pointer.parent / "extraction-runs" / run_id / "review.json"
        return json.loads(review.read_text())["fields"] if review.is_file() else {}


def api(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as response:
        return json.loads(response.read())


# ── the flow ─────────────────────────────────────────────────────────────────


def await_document(page) -> None:
    """Wait for the document to be loaded, not merely for its panels to exist.

    Fixed sleeps went marginal as soon as document load grew another request,
    which showed up as an intermittent section-verify failure rather than as
    anything to do with the fetch that caused it.
    """
    page.wait_for_selector("#panels", state="visible", timeout=20000)
    page.wait_for_function(
        "() => state.extraction !== null && state.currentRunId !== null"
        " && Object.keys(state.schemaFields || {}).length > 0",
        timeout=20000,
    )
    page.wait_for_load_state("networkidle")


def status_class(page, path: str) -> str:
    btn = page.locator(f'button.field-status[data-path="{path}"]').first
    return btn.get_attribute("class") or ""


def run_flow(harness: Harness) -> None:
    base = harness.base
    articles = api(base, "/api/articles")["articles"]
    extracted = [a for a in articles if a.get("has_extraction") is not False]
    if not extracted:
        raise SystemExit("the project has no extracted articles to drive")
    article = extracted[0]["article_id"]
    extraction = api(base, f"/api/article/{article}")
    print(f"project: {harness.project.name}   article: {article}")

    def stored() -> dict:
        return harness.stored(article)

    # Pick targets out of the document instead of naming them: the same flow
    # then works against any project, and nothing silently no-ops when a field
    # is renamed.
    def leaves(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from leaves(value, f"{prefix}.{key}" if prefix else key)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                yield from leaves(item, f"{prefix}[{index}]")
        elif prefix:
            yield prefix, node

    all_leaves = list(leaves(extraction))
    # Exclude enum-ranged slots from the "string" pool: their editor is a
    # <select>, which `fill()` cannot drive. Schema metadata is the only place
    # that distinction exists — the raw value is a plain string either way.
    schema_fields = api(base, "/api/schema/fields").get("fields", {})

    def kind_of(path):
        generic = re.sub(r"\[\d+\]", "[]", path)
        entry = schema_fields.get(path) or schema_fields.get(generic) or {}
        return entry.get("kind")

    strings = [
        p for p, v in all_leaves
        if isinstance(v, str) and p != "article_id" and kind_of(p) != "enum"
    ]
    numbers = [p for p, v in all_leaves if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not strings or not numbers:
        raise SystemExit("need at least one string and one numeric leaf to drive the flow")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        def record(message: str) -> None:
            if not injecting_failures:
                page_errors.append(message)

        page.on("response", lambda r: record(f"HTTP {r.status} {r.url}") if r.status >= 400 else None)
        page.on("pageerror", lambda e: record(str(e)))
        page.on("console", lambda m: record(m.text) if m.type == "error" else None)

        print("\n[overview]")
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        rows = page.locator("#overview-rows tr[data-article]")
        check("lists every document", rows.count() == len(articles),
              f"{rows.count()} rows, {len(articles)} articles")

        unextracted = [a for a in articles if a.get("has_extraction") is False]
        if unextracted:
            row = page.locator(
                f'#overview-rows tr[data-article="{unextracted[0]["article_id"]}"]'
            )
            check("an unextracted document is listed, not hidden", row.count() == 1)
            check("and reads as not extracted", "not extracted" in row.inner_text().lower(),
                  row.inner_text().replace("\n", " ")[:70])

        print("\n[a filter from a URL does not run until confirmed]")
        # A filter is JavaScript this app evaluates. One that arrived in a link
        # is not the user's, so a crafted verifier URL must not execute code
        # against the local project the moment the page opens. The live preview
        # counts as execution too.
        payload = "(window.__FLOW_RAN__ = true) || true"
        page.goto(f"{base}/?filter={urllib.parse.quote(payload)}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        check("not evaluated on load", page.evaluate("() => !window.__FLOW_RAN__"))
        check("but shown to the user", page.locator("#filter-input").input_value() == payload)
        check("in Expression mode", page.locator("#filter-input").is_visible()
              and page.locator("#ov-filterbar").get_attribute("data-mode") == "expression")
        check("with a prompt to apply it", "Apply" in page.locator("#filter-msg").inner_text(),
              page.locator("#filter-msg").inner_text())
        page.locator("#btn-filter-apply").click()
        page.wait_for_timeout(1000)
        check("and runs once confirmed", page.evaluate("() => !!window.__FLOW_RAN__"))
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        page.wait_for_timeout(700)

        print("\n[one filter bar: search and expression]")
        before = rows.count()
        page.locator("#ov-mode-search").click()
        check("Search mode shows the text input", page.locator("#ov-search").is_visible()
              and not page.locator("#filter-input").is_visible())
        page.locator("#ov-mode-expression").click()
        check("Expression mode shows the expression input", page.locator("#filter-input").is_visible()
              and not page.locator("#ov-search").is_visible())
        page.locator("#filter-input").fill(f"article_id === {json.dumps(article)}")
        page.wait_for_timeout(500)
        count_text = page.locator("#filter-count").inner_text()
        check("typing previews the match count", count_text == f"1/{len(articles)}", count_text)
        check("preview alone does not filter the rows", rows.count() == before, str(rows.count()))
        page.locator("#filter-input").press("Enter")
        page.wait_for_timeout(500)
        check("Enter narrows the rows immediately", rows.count() == 1, f"{before} -> {rows.count()}")
        check("and the applied expression shows as a chip", page.locator("#ov-filter-active").is_visible())
        page.locator("#ov-mode-search").click()
        check("the chip stays in Search mode", page.locator("#ov-filter-active").is_visible())
        page.locator("#ov-search").fill("zzzz-no-such-document")
        page.wait_for_timeout(300)
        check("text search and expression combine", rows.count() == 0, str(rows.count()))
        page.locator("#ov-search").fill("")
        page.wait_for_timeout(300)
        check("clearing the text leaves the expression", rows.count() == 1, str(rows.count()))
        page.locator("#ov-filter-clear").click()
        page.wait_for_timeout(300)
        check("x clears and restores every row", rows.count() == before, str(rows.count()))
        check("and removes the chip", not page.locator("#ov-filter-active").is_visible())
        page.locator("#ov-mode-expression").click()
        page.locator("#filter-input").fill("year >= (")
        page.wait_for_timeout(400)
        check("an invalid expression shows its error under the bar",
              page.locator("#filter-msg").is_visible() and page.locator("#filter-msg").inner_text() != "",
              page.locator("#filter-msg").inner_text())
        page.locator("#filter-input").fill("")
        page.reload(wait_until="networkidle")
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        check("the mode survives a reload",
              page.locator("#ov-filterbar").get_attribute("data-mode") == "expression")
        page.locator("#btn-filter-help").click()
        page.wait_for_timeout(300)
        on_top = page.evaluate("""() => {
          const box = document.querySelector('#filter-help-modal .filter-help-modal');
          const r = box.getBoundingClientRect();
          return box.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
        }""")
        check("filter help opens on top of everything", on_top)
        page.keyboard.press("Escape")
        page.locator("#ov-mode-search").click()

        print("\n[document-scoped controls belong to the document]")
        hidden_on_overview = [
            sel for sel in ("#app-nav", "#btn-overview", "#switcher-btn", "#view-mode-review", "#stat-citations")
            if page.locator(sel).count() and page.locator(sel).first.is_visible()
        ]
        check("document controls are hidden on the overview", not hidden_on_overview,
              ", ".join(hidden_on_overview))

        print("\n[open a document]")
        page.locator(f'#overview-rows tr[data-article="{article}"]').click()
        await_document(page)
        check("routed to document", f"#/doc/{article}" in page.url)
        check("document is pinned to one run",
              bool(page.evaluate("() => state.currentRunId")),
              str(page.evaluate("() => state.currentRunId")))
        check("document controls appear with the document",
              page.locator("#switcher-btn").is_visible() and page.locator("#btn-overview").is_visible())

        print("\n[the document says what produced it]")
        run_meta = next(a for a in articles if a["article_id"] == article).get("active_run") or {}
        chip = page.locator("#run-chip").first
        if chip.count():
            # The chip reads as the model; the opaque run id and the rest of the
            # provenance are on demand, in its tooltip.
            text = chip.inner_text()
            tooltip = chip.get_attribute("title") or ""
            if run_meta.get("model"):
                check("chip names the model", run_meta["model"] in text, f"{text!r}")
            check("run id is available but not shouted",
                  run_meta.get("run_id", "") in tooltip and run_meta.get("run_id", "") not in text,
                  tooltip.replace("\n", " | ")[:90])
            for label in ("effort", "provider", "created_at"):
                if run_meta.get(label):
                    check(f"tooltip carries {label}", str(run_meta[label]) in tooltip,
                          tooltip.replace("\n", " | ")[:90])
        else:
            check("provenance chip present", False, "no run chip rendered")

        print("\n[there is a way back]")
        # The overview's own view (sort, text, status) lives in its hash; leaving
        # a document through the app bar or Esc returns to that view.
        overview_hash = "#/?sort=fields&dir=desc"
        page.goto(f"{base}/{overview_hash}", wait_until="networkidle")
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        page.locator(f'#overview-rows tr[data-article="{article}"]').click()
        await_document(page)
        page.locator("#btn-overview").click()
        page.wait_for_timeout(700)
        check("Overview returns to the overview", page.locator("#overview-route").is_visible())
        check("and keeps the overview's hash query", page.url.endswith(overview_hash), page.url)
        page.go_back()
        await_document(page)
        check("browser back reopens the document", f"#/doc/{article}" in page.url, page.url)
        page.locator("body").click(position={"x": 5, "y": 300})
        page.keyboard.press("Escape")
        page.wait_for_timeout(700)
        check("Esc on a document returns to the overview",
              page.locator("#overview-route").is_visible() and page.url.endswith(overview_hash), page.url)
        page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
        await_document(page)
        page.locator("#search-box").click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        check("Esc inside an input stays on the document", f"#/doc/{article}" in page.url, page.url)

        print("\n[document switcher]")
        other = next(a["article_id"] for a in articles if a["article_id"] != article)
        switcher = page.locator("#switcher-btn")
        check("switcher names the open document",
              switcher.get_attribute("title", timeout=2000) not in (None, "", "Jump to a document"),
              str(switcher.get_attribute("title")))
        switcher.click()
        check("click opens the list", page.locator("#switcher-pop").is_visible()
              and switcher.get_attribute("aria-expanded") == "true")
        check("focus moves to the search input",
              page.evaluate("() => document.activeElement.id") == "switcher-input")
        options = page.locator("#switcher-list li[role=option]")
        check("lists the queue", options.count() == len(articles), f"{options.count()} of {len(articles)}")
        check("marks the open document", page.locator("#switcher-list li.current").get_attribute("data-article") == article)
        page.keyboard.type(other)
        page.wait_for_timeout(200)
        check("typing filters the list", 0 < options.count() < len(articles), str(options.count()))
        check("the hint counts matches", page.locator("#switcher-hint").inner_text().startswith(f"{options.count()} of {len(articles)}"),
              page.locator("#switcher-hint").inner_text())
        page.keyboard.press("Enter")
        page.wait_for_function(f"() => location.hash.startsWith('#/doc/{other}')", timeout=10000)
        check("Enter opens the match", f"#/doc/{other}" in page.url, page.url)
        check("and closes the list", page.locator("#switcher-pop").is_hidden())
        switcher.click()
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        check("Esc closes the list", page.locator("#switcher-pop").is_hidden())
        check("focus returns to the switcher", page.evaluate("() => document.activeElement.id") == "switcher-btn")
        check("and the document stays open", f"#/doc/{other}" in page.url, page.url)
        switcher.click()
        page.locator("#panel-right").click(position={"x": 20, "y": 20})
        check("a click outside closes the list", page.locator("#switcher-pop").is_hidden())

        print("\n[previous/next follow the filtered queue]")
        pair = [a["article_id"] for a in articles][:2]
        page.locator("#btn-overview").click()
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        page.locator("#ov-mode-expression").click()
        page.locator("#filter-input").fill(f"{json.dumps(pair)}.includes(article_id)")
        page.locator("#filter-input").press("Enter")
        page.wait_for_timeout(500)
        page.locator(f'#overview-rows tr[data-article="{pair[0]}"]').click()
        page.wait_for_function(f"() => location.hash.startsWith('#/doc/{pair[0]}')", timeout=10000)
        page.wait_for_timeout(500)
        check("counter counts the filtered queue", page.locator("#nav-counter").inner_text() == "1/2",
              page.locator("#nav-counter").inner_text())
        page.locator("#btn-next").click()
        page.wait_for_function(f"() => location.hash.startsWith('#/doc/{pair[1]}')", timeout=10000)
        page.wait_for_timeout(300)
        check("next steps to the second match", page.locator("#nav-counter").inner_text() == "2/2",
              page.locator("#nav-counter").inner_text())
        check("and stops at the end", page.locator("#btn-next").is_disabled())
        page.locator("#btn-prev").click()
        page.wait_for_function(f"() => location.hash.startsWith('#/doc/{pair[0]}')", timeout=10000)
        check("previous steps back", f"#/doc/{pair[0]}" in page.url, page.url)
        switcher.click()
        check("the switcher lists the same queue", options.count() == 2, str(options.count()))
        page.keyboard.press("Escape")
        page.locator("#btn-overview").click()
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        check("Overview keeps ?filter=", "filter=" in page.url, page.url)
        page.locator("#ov-filter-clear").click()
        page.locator("#ov-mode-search").click()

        print("\n[Audit/Data lives in the review pane]")
        page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
        await_document(page)
        toggle = page.locator("#extraction-panel-header #view-mode-data")
        check("the toggle sits in the review header", toggle.is_visible())
        toggle.click()
        page.wait_for_timeout(300)
        check("Data switches the pane", page.evaluate("() => state.viewMode") == "data"
              and page.locator("#extraction-panel-title").inner_text() == "Extraction Data")
        page.locator("#view-mode-review").click()
        page.wait_for_timeout(300)
        check("Audit switches back", page.evaluate("() => state.viewMode") == "review")

        print("\n[deep links honour the view they name]")
        for view, expected in (("review", "review"), ("data", "data")):
            page.goto(f"{base}/?view={view}#/doc/{article}", wait_until="networkidle")
            page.wait_for_timeout(700)
            check(f"?view={view} opens the {expected} view",
                  page.evaluate("() => state.viewMode") == expected,
                  str(page.evaluate("() => state.viewMode")))
        page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
        await_document(page)

        print("\n[verify a field]")
        target = strings[0]
        check("starts unreviewed", "status-empty" in status_class(page, target))
        page.locator(f'button.field-status[data-path="{target}"]').first.click()
        page.wait_for_timeout(1200)
        check("stored as an empty entry", stored().get(target) == {},
              json.dumps(stored().get(target)))
        # The visible half: a write that does not change the control reads as a no-op.
        check("control shows verified", "status-verified" in status_class(page, target),
              status_class(page, target))

        print("\n[verify survives a reload]")
        page.reload(wait_until="networkidle")
        await_document(page)
        check("still verified after reload", "status-verified" in status_class(page, target),
              status_class(page, target))

        print("\n[edit a field]")
        edit_target = strings[1] if len(strings) > 1 else strings[0]
        page.locator(f'button.row-edit-action[data-path="{edit_target}"]').first.click()
        page.wait_for_timeout(700)
        form = page.locator(f'.inline-edit-form[data-path="{edit_target}"]')
        check("inline edit opens", form.count() > 0)
        if form.count():
            form.locator("input, select, textarea").first.fill("EDITED BY THE FLOW")
            page.locator(".inline-edit-save").first.click()
            page.wait_for_timeout(1200)
            entry = stored().get(edit_target, {})
            check("stored as a replace override",
                  entry.get("override", {}).get("op") == "replace", json.dumps(entry))
            check("control shows edited", "status-flagged" in status_class(page, edit_target),
                  status_class(page, edit_target))
            check("edited value rendered",
                  "EDITED BY THE FLOW" in page.locator("#panel-right").inner_text())

        print("\n[numeric edit is typed, not stringified]")
        num_target = numbers[0]
        page.locator(f'button.row-edit-action[data-path="{num_target}"]').first.click()
        page.wait_for_timeout(700)
        numform = page.locator(f'.inline-edit-form[data-path="{num_target}"]')
        if numform.count():
            numform.locator("input, select, textarea").first.fill("23")
            page.locator(".inline-edit-save").first.click()
            page.wait_for_timeout(1200)
            value = stored().get(num_target, {}).get("override", {}).get("value")
            check("numeric slot stores a number",
                  isinstance(value, (int, float)) and not isinstance(value, bool),
                  f"{value!r} ({type(value).__name__})")
        else:
            check("numeric field editable", False, "no inline form")

        print("\n[progress reflects the work]")
        stat = page.locator("#stat-citations").inner_text()
        check("counter names verified and edited", "verified" in stat and "edited" in stat,
              stat[:60])

        print("\n[reasoning inherits to nested cells]")
        nested = next((p for p, _ in all_leaves if "[" in p), None)
        if nested:
            got = page.evaluate(
                "(path) => { const e = reasoningFor(path);"
                " return e ? (e.source_lines + '|' + (e.inheritedFrom || 'exact')) : null; }",
                nested,
            )
            check("nested cell has evidence", bool(got), f"{nested} -> {got}")

        print("\n[removing an array element tombstones, matching the export]")
        # Splicing renumbered every later element, so the reviewer's next click
        # landed on a different element than the one on screen, and the export
        # disagreed with what they approved.
        array_elem = next(
            (p for p in page.eval_on_selector_all(
                "button.row-edit-action[data-path]", "els => els.map(e => e.dataset.path)")
             if p.endswith("]")),
            None,
        )
        if array_elem:
            base_array = array_elem.split("[")[0]
            before = len(extraction.get(base_array, []))
            page.locator(f'button.row-edit-action[data-path="{array_elem}"]').first.click()
            page.wait_for_timeout(700)
            remove = page.locator(".inline-edit-remove")
            if remove.count():
                remove.first.click()
                page.wait_for_timeout(1200)
                after = page.evaluate(
                    "(k) => (effectiveExtraction() || {})[k]", base_array
                )
                check("array keeps its length", len(after or []) == before,
                      f"{before} -> {len(after or [])}")
                index = int(array_elem.split("[")[1].rstrip("]"))
                check("removed element is a null tombstone", (after or [None])[index] is None,
                      json.dumps(after)[:80])
            else:
                check("array element removable", False, "no remove control")

        print("\n[section-wide verify]")
        # Regression: bulk selection required an exact per-leaf reasoning entry,
        # so a section cited once at row level rendered its control disabled.
        toggles = page.locator("button.section-review-toggle")
        check("section controls present", toggles.count() > 0, f"{toggles.count()}")
        idx = next((i for i in range(toggles.count()) if not toggles.nth(i).is_disabled()), None)
        check("a section control is enabled", idx is not None)
        if idx is not None:
            section_path = toggles.nth(idx).get_attribute("data-path")
            before = len(stored())
            toggles.nth(idx).click()
            page.wait_for_timeout(2500)
            after = stored()
            check("section verify wrote several entries", len(after) > before,
                  f"{before} -> {len(after)}")
            # Read the status slot here, while the bulk action is the last thing
            # that touched it — a later single-field clear resets it, and this
            # check would then pass no matter what the bulk action said.
            chatter = page.locator("#save-status").inner_text().strip()
            check("a bulk action that succeeds says nothing", chatter == "", chatter[:60])
            check("section reads complete",
                  "section-complete" in (toggles.nth(idx).get_attribute("class") or ""),
                  toggles.nth(idx).get_attribute("class") or "")
            # A section scope covers both `section.leaf` and `section[0].leaf`,
            # depending on whether the section path names an array.
            under = {
                k: v for k, v in after.items()
                if k.startswith(f"{section_path}.") or k.startswith(f"{section_path}[")
            }
            added = {k: v for k, v in under.items() if not v.get("override")}
            check("added entries are plain verifications",
                  bool(added) and all(v == {} for v in added.values()),
                  json.dumps(added)[:90])

            # A field the bulk action verified must accept its next click. The
            # pointer never touched these controls — it was on the section header
            # — so nothing about them should need a warm-up hover first.
            if added:
                first_leaf = sorted(added)[0]
                page.locator(f'button.field-status[data-path="{first_leaf}"]').first.click()
                page.wait_for_timeout(1400)
                check("one click clears a bulk-verified field", first_leaf not in stored(),
                      f"{first_leaf} still stored")
                page.mouse.move(5, 5)
                page.wait_for_timeout(300)

        print("\n[a bulk action that fails says so]")
        global injecting_failures
        injecting_failures = True
        # Break the write path, then bulk-verify a section. Silence here is the
        # failure mode that matters: the section looks done and is not.
        page.route("**/api/annotations/**", lambda route: route.abort()
                   if route.request.method == "PUT" else route.continue_())
        broken = next((i for i in range(toggles.count()) if not toggles.nth(i).is_disabled()), None)
        if broken is not None:
            toggles.nth(broken).click()
            page.wait_for_timeout(2500)
            failed_text = page.locator("#save-status").inner_text()
            check("failure is reported", "fail" in failed_text.lower(), failed_text[:70])
            check("and marked as an error, not neutral chatter",
                  page.locator("#save-status").get_attribute("data-status") == "error",
                  str(page.locator("#save-status").get_attribute("data-status")))
        page.unroute("**/api/annotations/**")
        page.wait_for_timeout(300)
        injecting_failures = False

        print("\n[clear-arming follows the pointer, not the write]")
        # The control the pointer is on when it becomes verified must not clear
        # on the very next click; one it never touched must.
        fresh = next((p for p in strings if p not in stored()), None)
        if fresh:
            btn = page.locator(f'button.field-status[data-path="{fresh}"]').first
            btn.click()
            page.wait_for_timeout(1200)
            btn.click()  # pointer never left: this click must not undo it
            page.wait_for_timeout(1200)
            check("the click that verified a field cannot immediately undo it",
                  fresh in stored(), json.dumps(sorted(stored()))[:80])
            page.mouse.move(5, 5)
            page.wait_for_timeout(400)
            btn.click()  # pointer left and came back: now it clears
            page.wait_for_timeout(1200)
            check("it clears once the pointer has left and returned",
                  fresh not in stored(), json.dumps(sorted(stored()))[:80])

        print("\n[attribution is optional]")
        anon = [v for v in stored().values() if "reviewer" not in v]
        check("anonymous reviews saved without a reviewer", len(anon) > 0, f"{len(anon)} entries")
        attributable = next((p for p in strings if p not in stored()), None)
        if attributable:
            page.evaluate(
                "() => { document.querySelector('#reviewer-id').value = '0000-0002-1825-0097'; }"
            )
            page.locator(f'button.field-status[data-path="{attributable}"]').first.click()
            page.wait_for_timeout(1200)
            check("a connected reviewer is recorded",
                  stored().get(attributable, {}).get("reviewer") == "0000-0002-1825-0097",
                  json.dumps(stored().get(attributable)))

        print("\n[clear a review]")
        page.locator(f'button.field-status[data-path="{target}"]').first.click()
        page.wait_for_timeout(1200)
        check("entry removed", target not in stored(), json.dumps(sorted(stored())))
        check("control back to unreviewed", "status-empty" in status_class(page, target),
              status_class(page, target))

        if harness.render_article:
            rendered_flow(page, base, harness.render_article)
        if harness.graded_article:
            grade_flow(page, base, harness.graded_article)

        print("\n[console]")
        real = [e for e in page_errors if "favicon" not in e.lower()]
        check("no page errors", not real, "; ".join(real[:3])[:200])

        browser.close()


def rendered_flow(page, base: str, article: str) -> None:
    table_field = "mean_annual_temperature_c"
    paraphrase_field = "site_name"

    print("\n[rendered document]")
    page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
    await_document(page)
    check("Rendered is the default pane",
          page.locator('#pane-tabs [data-pane="rendered"]').get_attribute("aria-selected") == "true")
    left = page.locator("#panel-left")
    with contextlib.suppress(PlaywrightTimeout):
        page.wait_for_selector("#panel-left .rendered .blk", timeout=10000)
    check("prepared text renders as blocks", left.locator(".rendered .blk").count() > 0)
    check("HTML in prepared text is not shown as text", "<br>" not in left.inner_text())

    page.locator(f'tr.clickable[data-path="{table_field}"]').first.click()
    page.wait_for_timeout(600)
    row = left.locator(".rendered tr.reasoned-highlight")
    check("a cited table row is highlighted alone", row.count() == 1, f"{row.count()} rows")
    if row.count() == 1:
        check("its value cell is filled", row.locator("td.val-cell").count() == 1
              and row.locator("td.val-cell").inner_text().strip() == "7.56",
              row.inner_text().replace("\n", " ")[:60])

    page.locator(f'tr.clickable[data-path="{paraphrase_field}"]').first.click()
    page.wait_for_timeout(600)
    check("a paraphrased value tints its paragraph",
          left.locator(".rendered .blk.reasoned-highlight").count() == 1)
    marks = left.locator(".val-mark, td.val-cell").count()
    check("and marks nothing", marks == 0, f"{marks} marks")

    page.locator('#pane-tabs [data-pane="raw"]').click()
    page.wait_for_timeout(600)
    check("Raw lines shows HTML escaped", "<br>" in left.inner_text())
    check("Raw lines shows line numbers", left.locator(".md-line[data-line]").count() > 0)
    page.locator('#pane-tabs [data-pane="rendered"]').click()
    page.wait_for_timeout(400)

    print("\n[overview table]")
    page.goto(f"{base}/#/", wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=20000)
    page.locator("#overview-rows tr[data-article]").first.hover()
    page.mouse.wheel(0, 2000)
    page.wait_for_timeout(300)
    box = page.locator("#overview-table thead").bounding_box()
    check("header stays visible after scrolling", bool(box) and box["y"] >= 0, str(box))
    total = page.locator("#overview-rows tr[data-article]").count()
    page.locator('#ov-chips [data-status="not-started"]').click()
    page.wait_for_timeout(300)
    check("a status chip writes the URL", "status=not-started" in page.url, page.url)
    shown = page.locator("#overview-rows tr[data-article]").count()
    check("and narrows the rows", shown < total, f"{shown} of {total}")
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=20000)
    check("the chip survives a reload",
          page.locator('#ov-chips [data-status="not-started"]').get_attribute("aria-pressed") == "true")

    print("\n[icons]")
    check("icons come from the bundled sprite",
          page.locator('use[href="/static/icons.svg#settings"]').count() >= 1)


def grade_flow(page, base: str, article: str) -> None:
    print("\n[grader verdicts]")
    page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
    await_document(page)
    toggle = page.locator("#btn-review-order")
    check("the review-order toggle shows when a grade exists", toggle.is_visible())
    check("and defaults to flagged first", toggle.get_attribute("aria-pressed") == "true")
    groups = page.locator("#panel-right [data-review-group]")
    check("unsupported comes first", groups.count() > 0
          and groups.first.get_attribute("data-review-group") == "unsupported",
          str(groups.count() and groups.first.get_attribute("data-review-group")))
    order = page.locator("#panel-right tr.clickable[data-path]")
    check("its row leads the table", order.first.get_attribute("data-path") == "replicates",
          str(order.first.get_attribute("data-path")))
    marks = {
        v: page.locator(f'#panel-right .grade-mark[data-verdict="{v}"]').count()
        for v in ("supported", "partial", "unsupported", "cannot_verify")
    }
    check("verdict markers render, none for supported",
          marks["unsupported"] == 1 and marks["cannot_verify"] == 1
          and marks["partial"] >= 1 and marks["supported"] == 0, json.dumps(marks))
    partial_cell = "measurements[0].unit"
    check("a row's grade covers its cells",
          page.locator(f'#panel-right tr[data-path="{partial_cell}"] .grade-mark').count() == 1)

    chip_title = page.locator("#run-chip").get_attribute("title") or ""
    check("the run chip names the grader model", "checked by claude-flow-1" in chip_title,
          chip_title.replace("\n", " | ")[:90])

    box = page.locator("#source-evidence-reasoning")
    evidence = page.locator("#source-evidence-overlay")

    page.locator('#panel-right tr[data-path="site_name"] td.value-cell').first.click()
    page.wait_for_timeout(600)
    text = box.inner_text()
    check("a supported field shows the extractor's note",
          "Site named in the methods section." in text, text[:90])
    check("and no verdict text",
          box.locator(".evidence-verdict").count() == 0 and "Nsukka Research Farm" not in text, text[:90])
    check("and no confidence score",
          not page.locator("#source-evidence-confidence").is_visible())

    page.locator(f'#panel-right tr[data-path="{partial_cell}"] td.value-cell').first.click()
    page.wait_for_timeout(600)
    text = box.inner_text()
    check("a partial field leads with the verdict and the check's reason",
          "Partially supported" in text and "inferred from the table caption" in text, text[:90])
    details = box.locator("details.evidence-extraction")
    check("the extractor's note sits in a closed disclosure",
          details.count() == 1 and details.get_attribute("open") is None
          and "How it was extracted" in details.locator("summary").inner_text()
          and "Depth and unit read from Table 2." not in text,
          str(details.count()))
    details.locator("summary").click()
    check("and opens to show it", "Depth and unit read from Table 2." in box.inner_text())
    check("no confidence score for a graded field",
          not page.locator("#source-evidence-confidence").is_visible())
    all_text = evidence.inner_text()
    check("the evidence box never names the grader model",
          "claude-flow-1" not in all_text and "Grader" not in all_text, all_text[:90])

    toggle.click()
    page.wait_for_timeout(600)
    check("the toggle switches to document order", toggle.get_attribute("aria-pressed") == "false")
    check("rows follow the document again",
          page.locator("#panel-right [data-review-group]").count() == 0
          and order.first.get_attribute("data-path") == "site_name",
          str(order.first.get_attribute("data-path")))
    check("markers stay in document order",
          page.locator('#panel-right .grade-mark[data-verdict="unsupported"]').count() == 1)
    toggle.click()
    page.wait_for_timeout(400)

    print("\n[flags on the overview]")
    page.goto(f"{base}/#/", wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=20000)
    row = page.locator(f'#overview-rows tr[data-article="{article}"] .ov-flags')
    check("the graded document shows its flag count", row.count() == 1
          and row.inner_text().strip() == "2", row.inner_text() if row.count() else "none")
    page.locator('#overview-table th[data-sort="flags"]').click()
    page.locator('#overview-table th[data-sort="flags"]').click()
    page.wait_for_timeout(300)
    check("Flags sorts, most flagged first",
          page.locator("#overview-rows tr[data-article]").first.get_attribute("data-article") == article
          and "sort=flags" in page.url, page.url)
    page.locator('#ov-chips [data-status="flagged"]').click()
    page.wait_for_timeout(300)
    shown = page.locator("#overview-rows tr[data-article]")
    check("the Flagged chip keeps only flagged documents",
          shown.count() == 1 and shown.first.get_attribute("data-article") == article,
          f"{shown.count()} rows")
    page.locator('#ov-chips [data-status="all"]').click()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project", type=Path, default=DEFAULT_PROJECT,
        help="project to copy and drive (default: the verifier_flow fixture)",
    )
    parser.add_argument(
        "--keep", action="store_true", help="leave the temp copy in place for inspection"
    )
    args = parser.parse_args()

    harness = Harness(args.project, args.keep)
    try:
        harness.start()
        run_flow(harness)
    finally:
        harness.stop()

    print("\n" + ("FAILURES: " + ", ".join(failures) if failures else "ALL CHECKS PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
