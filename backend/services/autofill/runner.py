"""
Fill a Greenhouse / Lever / Ashby application form with Playwright (optional dependency).

    pip install -r requirements-optional.txt
    python -m playwright install chromium

run_prefill() opens the application page, scans every visible field (label, name, id, placeholder,
autocomplete, required), maps it with fields.classify_field(), fills the known ones from the applicant
profile, uploads the resume, pastes (or uploads) the cover letter, detects CAPTCHAs, takes a screenshot
and returns a report. It submits only when policy.submit_decision() allows it (off by default).
Sensitive questions (EEO, visa, salary, consent, ...) and unknown custom questions are never answered.
"""
import datetime
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from services.autofill import fields, policy
from services.autofill.profile import ApplicantProfile

logger = logging.getLogger("autofill")

INSTALL_HINT = ("Playwright is not installed: run `pip install -r requirements-optional.txt` and then "
                "`python -m playwright install chromium` in the backend environment.")

SCAN_JS = r"""
() => {
  const textOf = (el) => (el ? (el.innerText || el.textContent || '') : '').replace(/\s+/g, ' ').trim();
  const out = [];
  let idx = 0;
  for (const el of Array.from(document.querySelectorAll('input, textarea, select'))) {
    const tag = el.tagName.toLowerCase();
    const type = (tag === 'textarea' ? 'textarea' : tag === 'select' ? 'select' : (el.getAttribute('type') || 'text')).toLowerCase();
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
    const style = window.getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    const visible = type === 'file' || (style.display !== 'none' && style.visibility !== 'hidden' && (rect.width > 0 || rect.height > 0));
    if (!visible || el.disabled) continue;
    let label = '';
    if (el.id) { try { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) label = textOf(l); } catch (e) {} }
    if (!label) { const l = el.closest('label'); if (l) label = textOf(l); }
    if (!label && el.getAttribute('aria-labelledby')) {
      label = el.getAttribute('aria-labelledby').split(/\s+/).map((id) => textOf(document.getElementById(id))).join(' ').trim();
    }
    if (!label && el.getAttribute('aria-label')) label = el.getAttribute('aria-label');
    if (type === 'radio' || type === 'checkbox') {
      // A choice's own label is just "Yes"/"No": prefix the question it belongs to.
      let p = el.parentElement, depth = 0, question = '';
      while (p && depth < 5 && !question) {
        const q = p.querySelector('legend, [class*="title"], [class*="label"], [class*="question"]');
        if (q && !q.contains(el)) question = textOf(q);
        p = p.parentElement; depth++;
      }
      if (question) label = (question.replace(/\s*[*✱]\s*$/, '') + ' ' + label).trim();
    }
    if (!label) {
      let p = el.parentElement, depth = 0;
      while (p && depth < 4 && !label) {
        const l = p.querySelector('label, legend, [class*="label"], [class*="Label"]');
        if (l && !l.contains(el)) label = textOf(l);
        p = p.parentElement; depth++;
      }
    }
    const required = !!(el.required || el.getAttribute('aria-required') === 'true' || /[*✱]/.test(label.slice(-4)));
    const n = idx++;
    el.setAttribute('data-autopilot-idx', String(n));
    out.push({ idx: n, tag, type, name: el.getAttribute('name') || '', id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '', autocomplete: el.getAttribute('autocomplete') || '',
      label: label.replace(/\s*[*✱]\s*$/, '').slice(0, 200), required,
      value: type === 'file' ? '' : (el.value || ''), checked: !!el.checked });
  }
  return out;
}
"""

CAPTCHA_JS = r"""
() => {
  const sel = 'iframe[src*="recaptcha"], iframe[src*="hcaptcha"], iframe[src*="turnstile"], iframe[src*="captcha"], '
    + '.g-recaptcha, .h-captcha, .cf-turnstile, [data-sitekey], script[src*="recaptcha"], script[src*="hcaptcha"], script[src*="turnstile"]';
  return !!document.querySelector(sel);
}
"""

COVER_MANUAL_JS = r"""
() => {
  for (const b of Array.from(document.querySelectorAll('button, a, [role="button"]'))) {
    if (!/enter manually|paste|type it/i.test(b.textContent || '')) continue;
    let p = b.parentElement, depth = 0;
    while (p && depth < 5) {
      const head = p.querySelector('label, legend, h3, h4, [class*="label"]');
      if (head && /cover letter/i.test(head.textContent || '')) { b.click(); return true; }
      p = p.parentElement; depth++;
    }
  }
  return false;
}
"""

CONFIRM_RE = re.compile(r"thank you|thanks for applying|application (has been |was )?(received|submitted)|we.ve received", re.I)


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def application_url(url: str, ats: Optional[str]) -> str:
    """The page that holds the form: Lever '/apply', Ashby '/application'; Greenhouse shows it on the job page."""
    if not url:
        return url
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if ats == "lever" and not path.endswith("/apply"):
        path += "/apply"
    elif ats == "ashby" and not path.endswith("/application"):
        path += "/application"
    else:
        return url
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def _write_letter_file(letter: str, directory: Path) -> Path:
    path = directory / "cover_letter.txt"
    path.write_text(letter, encoding="utf-8")
    return path


def _radio_groups(scanned: list[dict]) -> list[dict]:
    """One entry per radio/checkbox group (by name), others unchanged."""
    out, seen = [], set()
    for f in scanned:
        if f["type"] in ("radio", "checkbox") and f["name"]:
            if f["name"] in seen:
                continue
            seen.add(f["name"])
        out.append(f)
    return out


def run_prefill(url: str, ats: Optional[str], profile: ApplicantProfile, resume_path: Optional[Path],
                cover_letter: Optional[str], approval_status: Optional[str], screenshot_dir: Path,
                on_step: Callable[[str], None] = lambda s: None) -> dict:
    """Fill the form at `url`. Returns a report dict; never raises for expected problems."""
    report = {
        "status": "failed", "url": url, "ats": ats, "form_url": None, "filled": [], "unfilled_required": [],
        "needs_your_answer": [], "unknown_optional": 0, "captcha": False, "resume_uploaded": False,
        "resume_file": resume_path.name if resume_path else None, "cover_letter": "not provided",
        "screenshot": None, "submitted": False, "submit_reason": None, "page_title": None, "error": None,
        "browser_left_open": False, "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    if not playwright_available():
        report["error"] = INSTALL_HINT
        return report
    from playwright.sync_api import Error as PWError, TimeoutError as PWTimeout, sync_playwright

    timeout_ms = int(policy.timeout_seconds() * 1000)
    headless = policy.headless()
    form_url = application_url(url, ats)
    report["form_url"] = form_url
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = Path(tempfile.mkdtemp(prefix="autofill_"))

    try:
        with sync_playwright() as pw:
            on_step("Starting the browser...")
            try:
                browser = pw.chromium.launch(headless=headless)
            except PWError as exc:
                msg = str(exc)
                report["error"] = ("The Chromium browser for Playwright is missing: run `python -m playwright install "
                                   "chromium`." if "Executable doesn't exist" in msg or "install" in msg.lower()
                                   else f"Could not start the browser: {msg.splitlines()[0][:200]}")
                return report
            context = browser.new_context(viewport={"width": 1280, "height": 1600})
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            try:
                on_step("Opening the application page...")
                page.goto(form_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_selector("input, textarea", timeout=min(timeout_ms, 20000))
                except PWTimeout:
                    report["error"] = ("No form fields appeared on the page. The posting may be closed, or the page "
                                       "layout changed: open the link and apply by hand.")
                    page.screenshot(path=str(screenshot_dir / f"autofill_{stamp}_noform.png"), full_page=True)
                    report["screenshot"] = str(screenshot_dir / f"autofill_{stamp}_noform.png")
                    return report
                report["page_title"] = page.title()[:200]
                page.evaluate(COVER_MANUAL_JS)

                on_step("Detecting form fields...")
                scanned = _radio_groups(page.evaluate(SCAN_JS))
                report["captcha"] = bool(page.evaluate(CAPTCHA_JS))

                on_step("Filling fields from your profile...")
                cover_done = False
                for f in scanned:
                    f["key"] = fields.classify_field(f["label"], f["name"], f["id"], f["type"], f["placeholder"],
                                                     f["autocomplete"], f["tag"])
                # Prefer pasting the letter into a text box over uploading it as a file.
                has_cover_box = any(f["key"] == "cover_letter" and f["type"] != "file" for f in scanned)
                for f in scanned:
                    key = f["key"]
                    if key == "cover_letter" and f["type"] == "file" and has_cover_box and cover_letter:
                        continue
                    label = fields.describe(f)
                    selector = f'[data-autopilot-idx="{f["idx"]}"]'
                    if key == "sensitive":
                        report["needs_your_answer"].append({"field": label, "required": f["required"],
                                                            "reason": "personal/legal question: never answered automatically"})
                        if f["required"]:
                            report["unfilled_required"].append({"field": label, "reason": "needs your answer"})
                        continue
                    if key == "resume":
                        if resume_path and resume_path.is_file():
                            page.set_input_files(selector, str(resume_path))
                            report["resume_uploaded"] = True
                            report["filled"].append({"field": label, "value": resume_path.name})
                        elif f["required"]:
                            report["unfilled_required"].append({"field": label, "reason": "no resume file found"})
                        continue
                    if key == "cover_letter":
                        if not cover_letter or cover_done:
                            if f["required"] and not cover_done:
                                report["unfilled_required"].append({"field": label, "reason": "no cover letter yet"})
                            continue
                        if f["type"] == "file":
                            page.set_input_files(selector, str(_write_letter_file(cover_letter, tmp)))
                            report["cover_letter"] = "uploaded as a file"
                        else:
                            page.fill(selector, cover_letter)
                            report["cover_letter"] = "pasted"
                        cover_done = True
                        report["filled"].append({"field": label, "value": f"cover letter ({len(cover_letter)} chars)"})
                        continue
                    value = profile.value_for(key) if key else ""
                    if key and value:
                        if f["value"]:
                            continue  # never overwrite something already there
                        page.fill(selector, value)
                        report["filled"].append({"field": label, "value": value if key != "phone" else value[:3] + "..."})
                    elif f["required"] and not (f["value"] or f["checked"]):
                        reason = (f"your profile has no {key.replace('_', ' ')}" if key
                                  else "custom question: needs your answer")
                        report["unfilled_required"].append({"field": label, "reason": reason})
                    elif not key:
                        report["unknown_optional"] += 1

                on_step("Taking a screenshot of the filled form...")
                shot = screenshot_dir / f"autofill_{stamp}.png"
                page.screenshot(path=str(shot), full_page=True)
                report["screenshot"] = str(shot)

                allowed, reason = policy.submit_decision(approval_status, report["unfilled_required"], report["captcha"])
                report["submit_reason"] = reason
                if allowed:
                    on_step("Submitting the application...")
                    report["submitted"] = _submit(page, timeout_ms)
                    after = screenshot_dir / f"autofill_{stamp}_after_submit.png"
                    page.screenshot(path=str(after), full_page=True)
                    report["screenshot_after_submit"] = str(after)
                    confirmed = bool(CONFIRM_RE.search(page.inner_text("body")[:20000]))
                    report["submit_confirmed"] = confirmed
                    report["status"] = "submitted" if report["submitted"] else "failed"
                    if not report["submitted"]:
                        report["error"] = "Could not find or click the submit button. Submit it yourself."
                else:
                    report["status"] = "needs_input" if (report["unfilled_required"] or report["captcha"]) else "prefilled"
                    on_step("Stopped before submitting (as configured).")
                    if not headless and policy.keep_open_minutes() > 0:
                        report["browser_left_open"] = True
                        on_step("Browser window left open: review the form and click Submit yourself.")
                        _wait_for_close(page, browser, policy.keep_open_minutes())
            except PWTimeout:
                report["error"] = (f"The page did not respond within {policy.timeout_seconds():g} seconds. "
                                   "Open the link and apply by hand.")
            except PWError as exc:
                report["error"] = f"The page could not be filled ({exc.__class__.__name__}): {str(exc).splitlines()[0][:200]}"
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
    except Exception as exc:  # anything else: report, never crash the API
        logger.exception("Autofill failed")
        report["error"] = f"Form filling failed: {type(exc).__name__}: {str(exc)[:200]}"
    finally:
        for p in tmp.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
    if report["error"] and report["status"] not in ("submitted",):
        report["status"] = "failed"
    return report


def _submit(page, timeout_ms: int) -> bool:
    for selector in ('button[type="submit"]', 'input[type="submit"]', 'button:has-text("Submit application")',
                     'button:has-text("Submit")'):
        loc = page.locator(selector)
        if loc.count():
            loc.first.click()
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
            except Exception:
                pass
            return True
    return False


def _wait_for_close(page, browser, minutes: float) -> None:
    """Keep the visible window open until the user closes it (or the time limit passes)."""
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        if page.is_closed() or not browser.is_connected():
            return
        try:
            page.wait_for_timeout(1000)
        except Exception:
            return
