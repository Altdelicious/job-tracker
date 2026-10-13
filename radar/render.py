"""Headless-browser page loading for careers pages built with JavaScript.

Enabled when the environment variable RENDER=1 and Playwright is installed
(GitHub Actions installs it). Not thread-safe: call from one thread only.
render(url) -> (final_url, html, requested_urls) or (None, None, []) on failure.
requested_urls includes every network request the page made, which reveals
hiring platforms that load jobs in the background (e.g. api.ashbyhq.com calls).
"""
import os

_state = {"pw": None, "browser": None, "ok": None}


def enabled():
    if os.environ.get("RENDER") != "1":
        return False
    if _state["ok"] is None:
        try:
            from playwright.sync_api import sync_playwright
            _state["pw"] = sync_playwright().start()
            _state["browser"] = _state["pw"].chromium.launch(args=["--no-sandbox"])
            _state["ok"] = True
        except Exception as e:  # noqa: BLE001
            print("Rendering unavailable:", e.__class__.__name__, e)
            _state["ok"] = False
    return _state["ok"]


def render(url, wait_ms=2500):
    if not enabled():
        return None, None, []
    ctx = _state["browser"].new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36 ml-job-radar",
                                        locale="en-GB")
    page = ctx.new_page()
    requests_seen = []
    page.on("request", lambda req: requests_seen.append(req.url))
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if resp is None or resp.status >= 400:
            return None, None, requests_seen
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(wait_ms)
        html = page.content()
        # include same-origin iframe content and iframe sources (job widgets often live in iframes)
        for f in page.frames[1:]:
            html += f'\n<!-- frame {f.url} -->\n'
            try:
                html += f.content()
            except Exception:  # noqa: BLE001
                pass
        return page.url, html, requests_seen
    except Exception:  # noqa: BLE001
        return None, None, requests_seen
    finally:
        ctx.close()


def close():
    """Shut the browser down; a later render() starts a fresh one."""
    try:
        if _state.get("browser"):
            _state["browser"].close()
        if _state.get("pw"):
            _state["pw"].stop()
    finally:
        _state.update(pw=None, browser=None, ok=None)
