"""Find job feeds for companies not on the standard boards, by visiting their website.

For each company without an enabled board (and not marked noBoard):
  1. Use its "website" from config/companies.json, or guess a domain from the name
     (accepted only if the page title names the company and the page looks AI/tech).
  2. Fetch the homepage and likely careers pages; look for links or widgets from a
     known hiring platform (Greenhouse, Lever, Ashby, Workable, SmartRecruiters,
     Recruitee, Teamtailor, Personio, Pinpoint, BambooHR, Breezy, Workday).
  3. If a platform is found and its feed answers, add it to config/boards.json.
     Otherwise, if a careers page exists, add it as a watched page ("page").
Writes data/sites_report.json with what was found for each company.
Run: python -m radar.sites [--only "A,B"]
"""
import argparse
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from .boards import READERS
from .common import CONFIG, DATA, PROBE, get, is_uk, load_json, save_json
from .discover import norm

PATTERNS = [
    ("greenhouse", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)"),
    ("greenhouse", r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("ashby", r"ashbyhq\.com/[^\"']*?embed\?[^\"']*?(?:organizationHostedJobsPageName|board)=([A-Za-z0-9_.-]+)"),
    ("workable", r"apply\.workable\.com/([A-Za-z0-9_-]+)"),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"),
    ("recruitee", r"([A-Za-z0-9-]+)\.recruitee\.com"),
    ("teamtailor", r"([A-Za-z0-9-]+)\.teamtailor\.com"),
    ("personio", r"([A-Za-z0-9-]+)\.jobs\.personio\.(?:de|com)"),
    ("pinpoint", r"([A-Za-z0-9-]+)\.pinpointhq\.com"),
    ("bamboohr", r"([A-Za-z0-9-]+)\.bamboohr\.com"),
    ("breezy", r"([A-Za-z0-9-]+)\.breezy\.hr"),
    ("workday", r"([A-Za-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)"),
]
IGNORE_SLUGS = {"embed", "api", "js", "www", "jobs", "careers", "static", "assets", "cdn", "app", "widget", "v1", "boards"}
CAREER_LINK = re.compile(r"career|jobs?\b|join[- ]?(us|the[- ]team)|hiring|work[- ]with[- ]us|open[- ]roles|vacanc|we.?re[- ]hiring|opportunities", re.I)
COMMON_PATHS = ["/careers", "/jobs", "/careers/", "/join-us", "/join", "/company/careers", "/about/careers", "/work-with-us", "/about-us/careers"]
TECHY = re.compile(r"\bai\b|artificial intelligence|machine learning|deep learning|computer vision|robot|data|model|platform|software|algorithm", re.I)


def page_html(url):
    r = get(url, timeout=15)
    if r is None or r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return None, None
    return r.url, r.text


def guess_site(name):
    base = norm(re.sub(r"\(.*?\)", "", name))
    words = base.split()
    stems = {"".join(words), "-".join(words)}
    if words and words[-1] == "ai":
        stems.add("".join(words[:-1]))
    if "." in name:
        stems.add(name.lower().replace(" ", ""))
    for stem in stems:
        for tld in ([""] if "." in stem else [".ai", ".com", ".co.uk", ".io", ".tech", ".bio", ".health"]):
            url = f"https://{stem}{tld}"
            final, text = page_html(url)
            if not text:
                continue
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
            site_name = re.search(r'property="og:site_name"\s+content="([^"]+)"', text, re.I)
            label = norm((title.group(1) if title else "") + " " + (site_name.group(1) if site_name else ""))
            if base.replace(" ", "") in label.replace(" ", "") and TECHY.search(text[:200000]):
                return final
    return None


def detect(text):
    for ats, pat in PATTERNS:
        for m in re.finditer(pat, text, re.I):
            if ats == "workday":
                return ats, f"{m.group(1)}|{m.group(2)}|{m.group(3)}"
            slug = m.group(1).strip("/").split("/")[0]
            if slug.lower() in IGNORE_SLUGS or len(slug) < 2:
                continue
            return ats, slug
    if re.search(r"teamtailor", text, re.I):
        return "teamtailor-custom", None
    return None, None


def explore(company):
    name = company["name"]
    site = company.get("website")
    guessed = False
    if not site:
        site = guess_site(name)
        guessed = bool(site)
    if not site:
        return dict(company=name, result="no website found")
    home_url, home = page_html(site)
    if not home:
        return dict(company=name, website=site, result="website not reachable")
    pages = [(home_url, home)]
    links = []
    for href, text in re.findall(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', home, re.S | re.I):
        if CAREER_LINK.search(href) or CAREER_LINK.search(re.sub(r"<[^>]+>", " ", text)):
            links.append(urljoin(home_url, href))
    host = urlparse(home_url).netloc
    links += [urljoin(home_url, p) for p in COMMON_PATHS]
    seen, careers_page = set(), None
    for link in links:
        if link in seen or len(seen) >= 8:
            continue
        seen.add(link)
        # an off-site careers link is often the hiring platform itself
        ats, slug = detect(link)
        if ats and slug:
            return dict(company=name, website=site, guessed=guessed, result="platform", ats=ats, slug=slug, via=link)
        if urlparse(link).netloc not in (host, "www." + host, host.removeprefix("www.")):
            continue
        u, t = page_html(link)
        if t:
            pages.append((u, t))
            if careers_page is None and CAREER_LINK.search(urlparse(u).path):
                careers_page = u
    for u, t in pages:
        ats, slug = detect(t)
        if ats == "teamtailor-custom":
            return dict(company=name, website=site, guessed=guessed, result="platform", ats="teamtailor", slug=f"{urlparse(u).scheme}://{urlparse(u).netloc}", via=u)
        if ats:
            return dict(company=name, website=site, guessed=guessed, result="platform", ats=ats, slug=slug, via=u)
    if careers_page:
        return dict(company=name, website=site, guessed=guessed, result="page", ats="page", slug=careers_page, via=careers_page)
    return dict(company=name, website=site, guessed=guessed, result="no careers page found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    PROBE["on"] = True

    companies = load_json(CONFIG / "companies.json", {"companies": []})["companies"]
    boards = load_json(CONFIG / "boards.json", {"boards": []})["boards"]
    covered = {b["company"] for b in boards if b.get("enabled") and b.get("ats") != "page"}
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    todo = [c for c in companies if not c.get("noBoard") and (c["name"] in only if only else c["name"] not in covered)]
    print(f"Exploring {len(todo)} company websites")
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(explore, todo))

    by_name = {c["name"]: c for c in companies}
    added = 0
    for res in results:
        c = by_name[res["company"]]
        if res["result"] not in ("platform", "page"):
            continue
        try:
            jobs = READERS[res["ats"]](res["slug"])
        except Exception:  # noqa: BLE001
            jobs = None
        res["jobs"] = None if jobs is None else len(jobs)
        if jobs is None:
            res["result"] += " (feed did not answer)"
            continue
        res["ukJobs"] = sum(1 for j in jobs if is_uk(j.get("location") or c.get("city", "")))
        entry = dict(company=c["name"], ats=res["ats"], slug=res["slug"], type=c.get("type", "startup"), fit=c.get("fit", "M"),
                     city=c.get("city", ""), confidence="medium" if res.get("guessed") else "high",
                     enabled=True, source="site", via=res.get("via"))
        boards = [b for b in boards if not (b["company"] == c["name"] and b.get("source") in ("discovered", "site") and not b.get("enabled"))]
        boards = [b for b in boards if not (b["company"] == c["name"] and b.get("source") == "site")]
        if not any(b["company"] == c["name"] and b.get("enabled") for b in boards):
            boards.append(entry)
            added += 1
        print(f'  {c["name"]}: {res["ats"]} {res["slug"]} ({res["jobs"]} jobs, {res["ukJobs"]} UK){" [guessed site]" if res.get("guessed") else ""}')
    boards.sort(key=lambda b: b["company"].lower())
    save_json(CONFIG / "boards.json", {"boards": boards})
    save_json(DATA / "sites_report.json", {"ranAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "results": results})
    print(f"Added {added} feeds from {len(todo)} websites")


if __name__ == "__main__":
    main()
