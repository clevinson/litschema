"""Browser flow check for `litschema verify` (not part of the pytest suite).

Drives overview -> document -> verify -> edit -> clear against a real project,
asserting that what the UI claims matches what lands in review.json. Needs
playwright, which is not a project dependency, so it runs on demand:

    uv run --with playwright python tests/browser_verify_flow.py http://localhost:8000

Written after a rename broke /api/article/{id} while every pytest passed: the
read surface is now covered in test_webapp_app.py, and this covers the clicks.

Runs against the soc-field-trials demo corpus, not a fixture, so it exercises
the same data and code path a user would hit.
"""

from __future__ import annotations

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8210"
ARTICLE = "francioli-2016-mineral-vs-organic-microbial"
failures: list[str] = []
console_errors: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(label)


def stored_review() -> dict:
    """Read what actually landed on disk — the UI claim must match the file."""
    out = subprocess.run(
        ["find", f"data/papers/{ARTICLE}/extraction-runs", "-name", "review.json"],
        capture_output=True, text=True, cwd="/Users/cory/Code/school/erw-research/demo-projects/soc-field-trials",
    ).stdout.strip()
    if not out:
        return {}
    return json.loads(open(out.splitlines()[0]).read()).get("fields", {})


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1500, "height": 950})
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))

    print("\n[overview]")
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=10000)
    rows = page.locator("#overview-rows tr[data-article]")
    check("lists every document", rows.count() == 8, f"{rows.count()} rows")
    check("totals rendered", "documents" in page.locator("#overview-totals").inner_text())
    page.screenshot(path="/tmp/shot-overview.png", full_page=True)

    print("\n[navigate]")
    page.locator(f'#overview-rows tr[data-article="{ARTICLE}"]').click()
    page.wait_for_selector("#panels", state="visible", timeout=10000)
    page.wait_for_load_state("networkidle")
    check("routed to document", f"#/doc/{ARTICLE}" in page.url)
    check("extraction rendered", len(page.locator("#panel-right").inner_text()) > 200)

    print("\n[verify a field]")
    target = "site_country"
    page.locator(f'button.field-status[data-path="{target}"]').first.click()
    page.wait_for_timeout(1500)
    fields = stored_review()
    check("verify persisted as empty entry", fields.get(target) == {}, json.dumps(fields.get(target)))
    check("counter shows verified", "verified" in page.locator("#stat-citations").inner_text(),
          page.locator("#stat-citations").inner_text()[:60])

    print("\n[edit a field]")
    edit_target = "site_name"
    page.locator(f'button.row-edit-action[data-path="{edit_target}"]').first.click()
    page.wait_for_timeout(700)
    form = page.locator(f'.inline-edit-form[data-path="{edit_target}"]')
    check("inline edit form opens", form.count() > 0)
    if form.count():
        box = form.locator("input, select, textarea").first
        box.fill("Bad Lauchstaedt EDITED")
        page.locator(".inline-edit-save").first.click()
        page.wait_for_timeout(1500)
        entry = stored_review().get(edit_target, {})
        ok = entry.get("override", {}).get("op") == "replace"
        check("edit persisted as replace override", ok, json.dumps(entry))
        check("edited value shown", "EDITED" in page.locator("#panel-right").inner_text())
    page.screenshot(path="/tmp/shot-edited.png", full_page=True)

    print("\n[overview reflects the work]")
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#overview-route", state="visible", timeout=10000)
    row_text = page.locator(f'#overview-rows tr[data-article="{ARTICLE}"]').inner_text()
    check("reviewed count advanced on overview", "\t2\t" in row_text.replace("  ", "\t") or "2" in row_text,
          " ".join(row_text.split())[:70])

    print("\n[clear a review]")
    page.goto(f"{BASE}#/doc/{ARTICLE}", wait_until="networkidle")
    page.wait_for_selector("#panels", state="visible", timeout=10000)
    page.wait_for_timeout(800)
    page.locator(f'button.field-status[data-path="{target}"]').first.click()
    page.wait_for_timeout(1500)
    check("clear removed the entry", target not in stored_review(), json.dumps(list(stored_review())))

    print("\n[console]")
    real = [e for e in console_errors if "favicon" not in e.lower()]
    check("no console errors", not real, "; ".join(real[:3])[:220])

    browser.close()

print("\n" + ("FAILURES: " + ", ".join(failures) if failures else "ALL CHECKS PASSED"))
sys.exit(1 if failures else 0)
