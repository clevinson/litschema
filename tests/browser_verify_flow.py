"""Browser flow check for `litschema verify` (not part of the pytest suite).

Drives the auditing workflow against a real project and asserts BOTH halves of
every action: what lands in review.json, and what the user actually sees. The
second half matters — a stale version-1 key once left every field rendering as
unreviewed while the writes succeeded with 200 OK, so file-only assertions
passed while the app was unusable.

Needs playwright, which is not a project dependency, so it runs on demand:

    litschema verify --port 8221 &
    uv run --with playwright python tests/browser_verify_flow.py http://localhost:8221 <project-dir>
"""

from __future__ import annotations

import glob
import json
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PROJECT = sys.argv[2] if len(sys.argv) > 2 else "."
ARTICLE = "francioli-2016-mineral-vs-organic-microbial"

failures: list[str] = []
page_errors: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


def stored() -> dict:
    """What actually landed on disk for this article's active run."""
    hits = glob.glob(f"{PROJECT}/data/papers/{ARTICLE}/extraction-runs/*/review.json")
    return json.loads(open(hits[0]).read())["fields"] if hits else {}


def reset_reviews() -> None:
    """Clear this article's reviews so the run starts from a known state.

    The flow asserts exact stored contents, so leftovers from a previous run
    change what the controls even offer — an already-overridden field shows a
    revert control rather than an edit one. Scoped to the one article this
    script drives; nothing else in the project is touched.
    """
    import os

    for hit in glob.glob(f"{PROJECT}/data/papers/{ARTICLE}/extraction-runs/*/review.json"):
        os.remove(hit)


def status_class(page, path: str) -> str:
    btn = page.locator(f'button.field-status[data-path="{path}"]').first
    return btn.get_attribute("class") or ""


reset_reviews()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("console", lambda m: page_errors.append(m.text) if m.type == "error" else None)

    print("\n[overview]")
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=15000)
    rows = page.locator("#overview-rows tr[data-article]")
    check("lists every document", rows.count() == 8, f"{rows.count()} rows")

    print("\n[open a document]")
    page.locator(f'#overview-rows tr[data-article="{ARTICLE}"]').click()
    page.wait_for_selector("#panels", state="visible", timeout=15000)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)
    check("routed to document", f"#/doc/{ARTICLE}" in page.url)

    print("\n[verify a field]")
    target = "site_country"
    check("starts unreviewed", "status-empty" in status_class(page, target))
    page.locator(f'button.field-status[data-path="{target}"]').first.click()
    page.wait_for_timeout(1500)
    check("stored as an empty entry", stored().get(target) == {}, json.dumps(stored().get(target)))
    # The visible half: a write that does not change the control reads as a no-op.
    check(
        "control shows verified",
        "status-verified" in status_class(page, target),
        status_class(page, target),
    )

    print("\n[verify survives a reload]")
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#panels", state="visible", timeout=15000)
    page.wait_for_timeout(1200)
    check(
        "still verified after reload",
        "status-verified" in status_class(page, target),
        status_class(page, target),
    )

    print("\n[edit a field]")
    edit_target = "site_name"
    page.locator(f'button.row-edit-action[data-path="{edit_target}"]').first.click()
    page.wait_for_timeout(700)
    form = page.locator(f'.inline-edit-form[data-path="{edit_target}"]')
    check("inline edit opens", form.count() > 0)
    if form.count():
        form.locator("input, select, textarea").first.fill("Bad Lauchstaedt EDITED")
        page.locator(".inline-edit-save").first.click()
        page.wait_for_timeout(1500)
        entry = stored().get(edit_target, {})
        check(
            "stored as a replace override",
            entry.get("override", {}).get("op") == "replace",
            json.dumps(entry),
        )
        check(
            "control shows edited",
            "status-flagged" in status_class(page, edit_target),
            status_class(page, edit_target),
        )
        check("edited value rendered", "EDITED" in page.locator("#panel-right").inner_text())

    print("\n[numeric edit is typed, not stringified]")
    num_target = "measurements[0].standard_error"
    page.locator(f'button.row-edit-action[data-path="{num_target}"]').first.click()
    page.wait_for_timeout(700)
    numform = page.locator(f'.inline-edit-form[data-path="{num_target}"]')
    if numform.count():
        numform.locator("input, select, textarea").first.fill("23")
        page.locator(".inline-edit-save").first.click()
        page.wait_for_timeout(1500)
        value = stored().get(num_target, {}).get("override", {}).get("value")
        check(
            "float slot stores a number",
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{value!r} ({type(value).__name__})",
        )
    else:
        check("numeric field editable", False, "no inline form")

    print("\n[progress reflects the work]")
    stat = page.locator("#stat-citations").inner_text()
    check("counter names verified and edited", "verified" in stat and "edited" in stat, stat[:60])

    print("\n[reasoning inherits to nested cells]")
    got = page.evaluate(
        "() => { const e = reasoningFor('measurements[0].value');"
        " return e ? (e.source_lines + '|' + (e.inheritedFrom || 'exact')) : null; }"
    )
    check("nested cell has evidence", bool(got), str(got))

    print("\n[section-wide verify]")
    # Regression: bulk selection required an exact per-leaf reasoning entry, so
    # a section cited once at row level rendered its control disabled.
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
        check("section verify wrote several entries", len(after) > before + 1,
              f"{before} -> {len(after)}")
        check("section reads complete",
              "section-complete" in (toggles.nth(idx).get_attribute("class") or ""),
              toggles.nth(idx).get_attribute("class") or "")
        # Bulk verify adds plain verifications and must not overwrite an
        # override a human already recorded in that section.
        under = {k: v for k, v in after.items() if k.startswith(f"{section_path}.")}
        preserved = under.get(num_target, {}).get("override", {}).get("op")
        check("existing override preserved", preserved == "replace", json.dumps(under.get(num_target)))
        added = {k: v for k, v in under.items() if k != num_target}
        check("added entries are plain verifications",
              added and all(v == {} for v in added.values()), json.dumps(added)[:90])

    print("\n[attribution is optional]")
    anon = [v for v in stored().values() if "reviewer" not in v]
    check("anonymous reviews saved without a reviewer", len(anon) > 0, f"{len(anon)} entries")
    page.evaluate("() => { document.querySelector('#reviewer-id').value = '0000-0002-1825-0097'; }")
    page.locator('button.field-status[data-path="replicates"]').first.click()
    page.wait_for_timeout(1500)
    check("a connected reviewer is recorded",
          stored().get("replicates", {}).get("reviewer") == "0000-0002-1825-0097",
          json.dumps(stored().get("replicates")))

    print("\n[clear a review]")
    page.locator(f'button.field-status[data-path="{target}"]').first.click()
    page.wait_for_timeout(1500)
    check("entry removed", target not in stored(), json.dumps(sorted(stored())))
    check(
        "control back to unreviewed",
        "status-empty" in status_class(page, target),
        status_class(page, target),
    )

    print("\n[console]")
    real = [e for e in page_errors if "favicon" not in e.lower()]
    check("no page errors", not real, "; ".join(real[:3])[:200])

    browser.close()

print("\n" + ("FAILURES: " + ", ".join(failures) if failures else "ALL CHECKS PASSED"))
sys.exit(1 if failures else 0)
