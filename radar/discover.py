"""Find each company's public job board by trying likely slugs on each platform.

Reads config/companies.json and config/boards.json; writes config/boards.json
(found boards) and data/discovery_report.json (what was tried, what wasn't found).
Manually added boards (source == "manual") are never overwritten.
Run: python -m radar.discover [--only "Company A,Company B"] [--retry-missing]
"""
import argparse
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .boards import READERS, greenhouse_name
from .common import CONFIG, DATA, PROBE, is_uk, load_json, save_json

ORDER = ["greenhouse", "ashby", "lever", "workable", "smartrecruiters", "recruitee"]
STRIP = re.compile(r"\b(ltd|limited|plc|inc|group|holdings|technologies|technology|tech|the)\b", re.I)


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def candidates(name):
    base = norm(re.sub(r"\(.*?\)", "", name))
    words = base.split()
    core = norm(STRIP.sub("", base)).split() or words
    c = []
    for w in (words, core):
        c += ["".join(w), "-".join(w)]
    j = "".join(core)
    if not j.endswith("ai"):
        c += [j + "ai", j + "-ai"]
    if not j.endswith("labs"):
        c.append(j + "labs")
    c += [j + "hq", j + "io"]
    dotted = re.sub(r"\s+", "", name.lower())
    if "." in dotted:
        c.insert(0, dotted)
    if j.endswith("ai") and len(j) > 4:
        c.append(j[:-2])
    if len(core) > 1:
        c.append(core[0])
    seen, out = set(), []
    for x in c:
        if x and x not in seen and len(x) >= 3:
            seen.add(x)
            out.append(x)
    return out


def probe(company):
    name = company["name"]
    tried = []
    best = None
    for slug in candidates(name):
        for ats in ORDER:
            tried.append(f"{ats}:{slug}")
            try:
                jobs = READERS[ats](slug)
            except Exception:
                jobs = None
            if jobs is None or len(jobs) == 0:
                continue
            uk = sum(1 for j in jobs if is_uk(j.get("location", "")))
            # confidence: board name matches company, or full-name slug with UK jobs
            conf = "low"
            if ats == "greenhouse":
                bn = greenhouse_name(slug) or ""
                if norm(bn) and (norm(bn) in norm(name) or norm(name) in norm(bn) or norm(bn).replace(" ", "") == slug.replace("-", "")):
                    conf = "high"
            full = norm(re.sub(r"\(.*?\)", "", name)).replace(" ", "")
            if conf == "low" and slug.replace("-", "") in (full, full + "ai", full + "labs") and len(full) >= 5 and uk > 0:
                conf = "high"
            if conf == "low" and uk > 0 and len(slug) >= 7:
                conf = "medium"
            cand = dict(company=name, ats=ats, slug=slug, jobs=len(jobs), ukJobs=uk, confidence=conf)
            if best is None or ({"high": 2, "medium": 1, "low": 0}[conf], uk) > ({"high": 2, "medium": 1, "low": 0}[best["confidence"]], best["ukJobs"]):
                best = cand
            if conf == "high":
                return best, tried
    return best, tried


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--retry-missing", action="store_true")
    args = ap.parse_args()
    PROBE["on"] = True

    companies = load_json(CONFIG / "companies.json", {"companies": []})["companies"]
    boards = load_json(CONFIG / "boards.json", {"boards": []})["boards"]
    have = {b["company"] for b in boards}
    report = load_json(DATA / "discovery_report.json", {"notFound": [], "lowConfidence": []})
    missing_before = set(report.get("notFound", []))

    only = {x.strip() for x in args.only.split(",") if x.strip()}
    todo = [c for c in companies if not c.get("noBoard")
            and (c["name"] in only if only else (c["name"] not in have and (args.retry_missing or c["name"] not in missing_before)))]
    print(f"Probing {len(todo)} companies")

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, todo))

    not_found, low = [], []
    by_name = {c["name"]: c for c in companies}
    for company, (best, _) in zip(todo, results):
        if not best:
            not_found.append(company["name"])
            continue
        c = by_name[company["name"]]
        entry = dict(company=company["name"], ats=best["ats"], slug=best["slug"], type=c.get("type", "startup"),
                     fit=c.get("fit", "M"), confidence=best["confidence"], enabled=best["confidence"] != "low",
                     source="discovered", jobsAtDiscovery=best["jobs"], ukJobsAtDiscovery=best["ukJobs"])
        boards = [b for b in boards if not (b["company"] == entry["company"] and b.get("source") != "manual")]
        if not any(b["company"] == entry["company"] for b in boards):
            boards.append(entry)
        if best["confidence"] == "low":
            low.append(f'{company["name"]} → {best["ats"]}:{best["slug"]} ({best["jobs"]} jobs, {best["ukJobs"]} UK)')
        print(f'  {company["name"]}: {best["ats"]}:{best["slug"]} [{best["confidence"]}] {best["jobs"]} jobs / {best["ukJobs"]} UK')

    boards.sort(key=lambda b: b["company"].lower())
    save_json(CONFIG / "boards.json", {"boards": boards})
    prev_nf = [n for n in report.get("notFound", []) if n not in {t["name"] for t in todo}]
    save_json(DATA / "discovery_report.json", {
        "ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "probed": len(todo),
        "found": len(todo) - len(not_found),
        "notFound": sorted(set(prev_nf + not_found)),
        "lowConfidence": low,
    })
    print(f"Found {len(todo) - len(not_found)} of {len(todo)}; {len(low)} low-confidence (disabled until reviewed)")


if __name__ == "__main__":
    main()
