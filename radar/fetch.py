"""Fetch every enabled board and academic source, keep UK ML/research roles,
score them, and write data/jobs.json and data/status.json.
Run: python -m radar.fetch
"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from . import boards as B
from .common import (CONFIG, DATA, city_tags, is_uk, level, load_json, save_json,
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


def from_board(b):
    reader = B.READERS[b["ats"]]
    try:
        raw = reader(b["slug"])
    except Exception as e:  # noqa: BLE001
        return b, None, f"error: {e.__class__.__name__}"
    if raw is None:
        return b, None, "board not reachable"
    out = []
    for j in raw:
        if not is_uk(j.get("location", "")) or not wanted_title(j.get("title")):
            continue
        s, why = score(j["title"], b["type"], b.get("fit", "M"))
        out.append(dict(
            id=f'{ {"greenhouse": "gh", "lever": "lv", "ashby": "ashby", "workable": "wk", "smartrecruiters": "sr", "recruitee": "rc"}[b["ats"]] }-{b["slug"]}-{str(j["id"])[:12]}'.replace(" ", ""),
            company=b["company"], companyType=b["type"], title=j["title"].strip(), location=j.get("location", ""),
            cities=city_tags(j.get("location", "")), url=j.get("url"), posted=j.get("posted"), closes=None, salary=None,
            score=s, why=why, level=level(j["title"]), tags=tags(j["title"]), source=b["ats"]))
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
        if not re.search(r"london|cambridge|oxford", loc, re.I) or not wanted_title(j["title"]):
            continue
        s, why = score(j["title"], "academic", "M")
        jobs.append(dict(id=f'jacuk-{j["id"]}', company=j.get("employer") or "University", companyType="academic",
                         title=j["title"], location=j.get("location") or "", cities=city_tags(loc), url=j["url"],
                         posted=None, closes=parse_close(j.get("closes_text")), salary=j.get("salary"), score=s, why=why,
                         level=level(j["title"]), tags=tags(j["title"]), source="jobs.ac.uk"))
    notes.append(f"jobs.ac.uk: {len(ac)} results scanned")
    try:
        cam = B.cam_research()
        for j in cam:
            if not wanted_title(j["title"]):
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


def main():
    cfg = load_json(CONFIG / "boards.json", {"boards": []})["boards"]
    enabled = [b for b in cfg if b.get("enabled", True)]
    prev = {j["id"]: j for j in load_json(DATA / "jobs.json", {"jobs": []})["jobs"]}

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(from_board, enabled))

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
    found += ac_jobs
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
    academic_ok = any(n.startswith("jobs.ac.uk:") for n in notes)
    for jid, old in prev.items():
        if jid in current:
            continue
        src_failed = (old.get("companyType") != "academic" and old.get("company") in failed) or (old.get("companyType") == "academic" and not academic_ok)
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
