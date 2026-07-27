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
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROJECT = REPO_ROOT / "tests" / "fixtures" / "projects" / "verifier_flow"

failures: list[str] = []
page_errors: list[str] = []


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
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.server: subprocess.Popen | None = None

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
        pointer = self.project / "data" / "papers" / article / "active-run.json"
        if not pointer.is_file():
            return {}
        run_id = json.loads(pointer.read_text())["run_id"]
        review = pointer.parent / "extraction-runs" / run_id / "review.json"
        return json.loads(review.read_text())["fields"] if review.is_file() else {}


def api(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=10) as response:
        return json.loads(response.read())


# ── the flow ─────────────────────────────────────────────────────────────────


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
    strings = [p for p, v in all_leaves if isinstance(v, str) and p != "article_id"]
    numbers = [p for p, v in all_leaves if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if not strings or not numbers:
        raise SystemExit("need at least one string and one numeric leaf to drive the flow")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 950})
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on("console", lambda m: page_errors.append(m.text) if m.type == "error" else None)

        print("\n[overview]")
        page.goto(base, wait_until="networkidle")
        page.wait_for_selector("#overview-route", state="visible", timeout=20000)
        rows = page.locator("#overview-rows tr[data-article]")
        check("lists every document", rows.count() == len(articles),
              f"{rows.count()} rows, {len(articles)} articles")

        print("\n[open a document]")
        page.locator(f'#overview-rows tr[data-article="{article}"]').click()
        page.wait_for_selector("#panels", state="visible", timeout=20000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        check("routed to document", f"#/doc/{article}" in page.url)
        check("document is pinned to one run",
              bool(page.evaluate("() => state.currentRunId")),
              str(page.evaluate("() => state.currentRunId")))

        print("\n[deep links honour the view they name]")
        for view, expected in (("review", "review"), ("data", "data")):
            page.goto(f"{base}/?view={view}#/doc/{article}", wait_until="networkidle")
            page.wait_for_timeout(700)
            check(f"?view={view} opens the {expected} view",
                  page.evaluate("() => state.viewMode") == expected,
                  str(page.evaluate("() => state.viewMode")))
        page.goto(f"{base}/#/doc/{article}", wait_until="networkidle")
        page.wait_for_selector("#panels", state="visible", timeout=20000)
        page.wait_for_timeout(900)

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
        page.wait_for_selector("#panels", state="visible", timeout=20000)
        page.wait_for_timeout(1200)
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
            check("section reads complete",
                  "section-complete" in (toggles.nth(idx).get_attribute("class") or ""),
                  toggles.nth(idx).get_attribute("class") or "")
            under = {k: v for k, v in after.items() if k.startswith(f"{section_path}.")}
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

        print("\n[console]")
        real = [e for e in page_errors if "favicon" not in e.lower()]
        check("no page errors", not real, "; ".join(real[:3])[:200])

        browser.close()


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
