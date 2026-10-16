"""Fetch every enabled board and academic source, keep UK ML/research roles,
score them, and write data/jobs.json and data/status.json.
Run: python -m radar.fetch
"""
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import boards as B
from .common import (CONFIG, DATA, HTTP_LOG, academic_ok, city_tags, is_uk, level, load_json, save_json,
                     score, tags, wanted_title)

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")
TODAY = date.today()
KEEP_CLOSED_DAYS = 7
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_close(text):
    if not text:
        return None
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3})[a-z]*(?:\s+(\d{4}))?", text)
    if not m:
        return None
    d, mon, y = int(m.group(1)), MONTHS.get(m.group(2).lower()), m.group(3)
    if not mon:
        return None
    year = int(y) if y else TODAY.year
    try:
        dt = date(year, mon, d)
    except ValueError:
        return None
    if not y and dt < TODAY - timedelta(days=60):
        dt = date(year + 1, mon, d)
    return dt.isoformat()


PREFIX = {"greenhouse": "gh", "lever": "lv", "ashby": "ashby", "workable": "wk", "smartrecruiters": "sr", "recruitee": "rc",
          "teamtailor": "tt", "personio": "ps", "pinpoint": "pp", "bamboohr": "bh", "breezy": "bz", "workday": "wd", "page": "pg", "gem": "gem"}
LEGACY_IDS = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"}  # keep IDs stable for existing jobs
COMPANY_CITY = {c["name"]: c.get("city", "") for c in load_json(CONFIG / "companies.json", {"companies": []})["companies"]}


def from_board(b):
    reader = B.READERS[b["ats"]]
    try:
        raw = reader(b["slug"])
    except Exception as e:  # noqa: BLE001
        return b, None, f"error: {e.__class__.__name__}"
    if raw is None:
        codes = {u: c for u, c in HTTP_LOG.items() if b["slug"] in u}
        return b, None, "board not reachable " + json.dumps(codes)
    out = []
    fallback_city = b.get("city") or COMPANY_CITY.get(b["company"], "")
    for j in raw:
        loc = (j.get("location") or "").strip()
        # Feeds without a location (watched pages, some platforms): assume the company's UK base.
        eff_loc = loc or fallback_city
        if not is_uk(eff_loc) or not wanted_title(j.get("title")):
            continue
        if b["ats"] == "page" and not B.ROLE_NOUN.search(j.get("title", "")):
            continue
        s, why = score(j["title"], b["type"], b.get("fit", "M"))
        slug_key = re.sub(r"[^A-Za-z0-9]+", "", b["slug"].split("://")[-1])[:24]
        out.append(dict(
            id=(f'{PREFIX[b["ats"]]}-{b["slug"]}-{str(j["id"])[:12]}'.replace(" ", "") if b["ats"] in LEGACY_IDS
                else f'{PREFIX.get(b["ats"], b["ats"][:4])}-{slug_key}-{re.sub(r"[^A-Za-z0-9_-]+", "", str(j["id"]))[:24]}'),
            company=b["company"], companyType=b["type"], title=j["title"].strip(), location=loc or (fallback_city + " (assumed)" if fallback_city else ""),
            cities=city_tags(eff_loc), url=j.get("url"), posted=j.get("posted"), closes=None, salary=None,
            score=s, why=why + (" Found on the company's careers page." if b["ats"] == "page" else ""),
            level=level(j["title"]), tags=tags(j["title"]), source=b["ats"]))
    return b, out, f"ok: {len(raw)} jobs, {len(out)} kept"


def academic():
    jobs, notes = [], []
    ac = {}
    for kw in ("machine learning", "artificial intelligence", "computer vision", "medical imaging", "data science", "deep learning"):
        try:
            for j in B.jobs_ac_uk(kw):
                ac[j["id"]] = j
        except Exception as e:  # noqa: BLE001
            notes.append(f"jobs.ac.uk '{kw}' failed: {e.__class__.__name__}")
    for j in ac.values():
        loc = " ".join(x for x in (j.get("location"), j.get("employer")) if x)
        if not re.search(r"london|cambridge|oxford", loc, re.I) or not academic_ok(j["title"]):
            continue
        if not j.get("location"):
            j["location"] = next((c.title() for c in ("london", "cambridge", "oxford") if c in loc.lower()), "")
        s, why = score(j["title"], "academic", "M")
        jobs.append(dict(id=f'jacuk-{j["id"]}', company=j.get("employer") or "University", companyType="academic",
                         title=j["title"], location=j.get("location") or "", cities=city_tags(loc), url=j["url"],
                         posted=None, closes=parse_close(j.get("closes_text")), salary=j.get("salary"), score=s, why=why,
                         level=level(j["title"]), tags=tags(j["title"]), source="jobs.ac.uk"))
    notes.append(f"jobs.ac.uk: {len(ac)} results scanned")
    try:
        cam = B.cam_research()
        for j in cam:
            if not academic_ok(j["title"], j.get("department", "")):
                continue
            s, why = score(j["title"], "academic", "M")
            jobs.append(dict(id=f'cam-{j["id"]}', company="University of Cambridge", companyType="academic",
                             title=j["title"], location="Cambridge" + (f' ({j["department"]})' if j.get("department") else ""),
                             cities=["cambridge"], url=j["url"], posted=None, closes=parse_close(j.get("closes_text")),
                             salary=j.get("salary"), score=s, why=why, level=level(j["title"]), tags=tags(j["title"]), source="cam.ac.uk"))
        notes.append(f"cam.ac.uk: {len(cam)} vacancies scanned")
    except Exception as e:  # noqa: BLE001
        notes.append(f"cam.ac.uk failed: {e.__class__.__name__}")
    return jobs, notes


def amazon():
    try:
        raw = B.amazon_uk()
    except Exception:  # noqa: BLE001
        return [], "Amazon: failed"
    out = []
    for j in raw:
        if not is_uk(j["location"]) or not wanted_title(j["title"]):
            continue
        s, why = score(j["title"], "lab", "M")
        out.append(dict(id=f'amzn-{j["id"]}', company="Amazon", companyType="lab", title=j["title"], location=j["location"],
                        cities=city_tags(j["location"]), url=j["url"], posted=None, closes=None, salary=None, score=s, why=why,
                        level=level(j["title"]), tags=tags(j["title"]), source="amazon"))
    return out, f"Amazon: {len(raw)} scanned, {len(out)} kept"


ADZUNA_QUERIES = ["machine learning", "research engineer", "research scientist", "applied scientist",
                  "computer vision", "data scientist", "ai engineer", "deep learning"]


def _key(name):
    n = re.sub(r"\(.*?\)", "", name.lower())
    n = re.sub(r"\b(ltd|limited|plc|inc|uk|group|holdings|technologies|technology|the)\b", "", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def adzuna(covered):
    """Roles from listed companies that have no working feed, found through Adzuna's UK search."""
    app_id, app_key = os.environ.get("ADZUNA_APP_ID"), os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        return [], "Adzuna: skipped (no API key set)"
    companies = load_json(CONFIG / "companies.json", {"companies": []})["companies"]
    wanted = {_key(c["name"]): c for c in companies if c["name"] not in covered and len(_key(c["name"])) >= 4}
    try:
        raw = B.adzuna(app_id, app_key, ADZUNA_QUERIES, ["London", "Cambridge", "Oxford"])
    except Exception as e:  # noqa: BLE001
        return [], f"Adzuna failed: {e.__class__.__name__}"
    out = []
    for j in raw:
        c = wanted.get(_key(j["company"]))
        if not c or not is_uk(j["location"] or "UK") or not wanted_title(j["title"]):
            continue
        s, why = score(j["title"], c.get("type", "startup"), c.get("fit", "M"))
        out.append(dict(id=f'adz-{j["id"]}', company=c["name"], companyType=c.get("type", "startup"), title=j["title"],
                        location=j["location"], cities=city_tags(j["location"]), url=j["url"], posted=j["posted"],
                        closes=None, salary=None, score=s, why=why + " Found via Adzuna job search.",
                        level=level(j["title"]), tags=tags(j["title"]), source="adzuna"))
    return out, f"Adzuna: {len(raw)} ads scanned, {len(out)} kept"


def hackernews():
    from . import hn
    try:
        raw = hn.posts()
    except Exception as e:  # noqa: BLE001
        return [], f"Hacker News failed: {e.__class__.__name__}"
    if raw is None:
        return [], "Hacker News failed: thread not found"
    companies = {_key(c["name"]): c for c in load_json(CONFIG / "companies.json", {"companies": []})["companies"]}
    out = []
    for j in raw:
        c = companies.get(_key(j["company"]), {})
        ctype, fit = c.get("type", "startup"), c.get("fit", "M")
        s, why = score(j["title"], ctype, fit)
        out.append(dict(id=f'hn-{j["id"]}', company=c.get("name", j["company"]), companyType=ctype, title=j["title"],
                        location=j["location"], cities=city_tags(j["location"]), url=j["url"], posted=j["posted"],
                        closes=None, salary=None, score=s, why=why + f' Posted in HN "{j["thread"]}".',
                        level=level(j["title"]), tags=tags(j["title"]), source="hackernews"))
    return out, f"Hacker News: {len(out)} UK roles kept"


def main():
    cfg = load_json(CONFIG / "boards.json", {"boards": []})["boards"]
    enabled = [b for b in cfg if b.get("enabled", True)]
    prev = {j["id"]: j for j in load_json(DATA / "jobs.json", {"jobs": []})["jobs"]}

    feeds = [b for b in enabled if b["ats"] != "page"]
    pages = [b for b in enabled if b["ats"] == "page"]
    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(from_board, feeds))
    results += [from_board(b) for b in pages]  # one at a time: the browser isn't thread-safe
    from . import render as R
    R.close()

    found, board_status, failed = [], [], []
    ok_boards = set()
    for b, jobs, msg in results:
        board_status.append(dict(company=b["company"], ats=b["ats"], slug=b["slug"], status=msg))
        if jobs is None:
            failed.append(b["company"])
        else:
            ok_boards.add(b["company"])
            found += jobs

    ac_jobs, notes = academic()
    seen_titles = {}
    for j in sorted(ac_jobs, key=lambda j: j["source"] != "cam.ac.uk"):
        key = (re.sub(r"\W+", " ", j["title"].lower()).strip(), "cambridge" if "cambridge" in j["company"].lower() else j["company"].lower())
        if key not in seen_titles:
            seen_titles[key] = j
    found += list(seen_titles.values())
    adz, adz_note = adzuna(ok_boards)
    found += adz
    notes.append(adz_note)
    hnj, hn_note = hackernews()
    found += hnj
    notes.append(hn_note)
    amz, amz_note = amazon()
    found += amz
    notes.append(amz_note)

    current = {}
    for j in found:
        if j["id"] in current:
            continue
        old = prev.get(j["id"])
        j["firstSeen"] = old["firstSeen"] if old else NOW
        j["lastSeen"] = NOW
        j["active"] = not (j.get("closes") and j["closes"] < TODAY.isoformat())
        current[j["id"]] = j

    # Jobs missing this run: keep them only if their source failed (so a flaky
    # fetch doesn't drop them), else mark closed and keep for a few days.
    academic_src_ok = any(n.startswith("jobs.ac.uk:") for n in notes)
    for jid, old in prev.items():
        if jid in current:
            continue
        adz_ok = adz_note.startswith("Adzuna: ") and "skipped" not in adz_note
        src_failed = (old.get("source") == "adzuna" and not adz_ok) or (old.get("source") == "hackernews" and "failed" in hn_note) or (old.get("source") == "hackernews" and old.get("posted", "") >= (TODAY - timedelta(days=45)).isoformat()) or (old.get("source") != "adzuna" and old.get("companyType") != "academic" and old.get("company") in failed) or (old.get("companyType") == "academic" and not academic_src_ok)
        if src_failed:
            current[jid] = old
            continue
        if old.get("active", True):
            old = dict(old, active=False, closedSeen=NOW)
        closed_at = old.get("closedSeen") or old.get("lastSeen") or NOW
        if datetime.fromisoformat(closed_at) > datetime.now(timezone.utc) - timedelta(days=KEEP_CLOSED_DAYS):
            current[jid] = old

    jobs = sorted(current.values(), key=lambda j: (-j["score"], j["company"], j["title"]))
    active = [j for j in jobs if j["active"]]
    new = [j for j in active if j["firstSeen"] == NOW]
    save_json(DATA / "jobs.json", {"generatedAt": NOW, "jobs": jobs})
    save_json(DATA / "status.json", {
        "lastRun": NOW, "boardsTotal": len(enabled), "boardsOk": len(ok_boards), "boardsFailed": failed,
        "jobsActive": len(active), "newThisRun": len(new), "notes": notes, "boards": board_status,
    })
    print(f"{len(ok_boards)}/{len(enabled)} boards ok; {len(active)} active roles; {len(new)} new")
    for f in failed:
        print("  failed:", f)


if __name__ == "__main__":
    main()
