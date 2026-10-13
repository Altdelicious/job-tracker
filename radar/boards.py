"""Readers for public job-board APIs. Each returns a list of raw job dicts:
{id, title, location, url, posted} — or None when the board doesn't exist."""
import html
import re
from datetime import datetime, timezone

from .common import get


def _iso(ts):
    if ts is None or ts == "":
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat()
        return str(ts)[:10]
    except Exception:
        return None


def greenhouse(slug):
    for host in ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"):
        r = get(f"https://{host}/v1/boards/{slug}/jobs")
        if r is not None and r.status_code == 200:
            try:
                jobs = r.json().get("jobs", [])
            except ValueError:
                continue
            out = []
            for j in jobs:
                locs = [(j.get("location") or {}).get("name", "")]
                for o in j.get("offices", []) or []:
                    locs.append(o.get("name", ""))
                out.append(dict(id=str(j["id"]), title=j.get("title", ""), location="; ".join(dict.fromkeys(l for l in locs if l)),
                                url=j.get("absolute_url"), posted=_iso(j.get("first_published") or j.get("updated_at"))))
            return out
    return None


def greenhouse_name(slug):
    for host in ("boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"):
        r = get(f"https://{host}/v1/boards/{slug}")
        if r is not None and r.status_code == 200:
            try:
                return r.json().get("name")
            except ValueError:
                return None
    return None


def lever(slug):
    for host in ("api.lever.co", "api.eu.lever.co"):
        r = get(f"https://{host}/v0/postings/{slug}", params={"mode": "json"})
        if r is not None and r.status_code == 200:
            try:
                jobs = r.json()
            except ValueError:
                continue
            if not isinstance(jobs, list):
                continue
            if not jobs and host == "api.lever.co":
                # an empty list also comes back for unknown slugs on the US host; try EU
                continue
            out = []
            for j in jobs:
                cat = j.get("categories") or {}
                locs = [cat.get("location", "")] + list(cat.get("allLocations") or [])
                out.append(dict(id=j["id"], title=j.get("text", ""), location="; ".join(dict.fromkeys(l for l in locs if l)),
                                url=j.get("hostedUrl"), posted=_iso(j.get("createdAt"))))
            return out
    return None


def ashby(slug):
    r = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", params={"includeCompensation": "false"})
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", []) or []]
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        if addr.get("addressCountry"):
            locs.append(addr["addressCountry"])
        out.append(dict(id=j["id"], title=j.get("title", ""), location="; ".join(dict.fromkeys(l for l in locs if l)),
                        url=j.get("jobUrl"), posted=_iso(j.get("publishedAt"))))
    return out


def workable(slug):
    r = get(f"https://apply.workable.com/api/v1/widget/accounts/{slug}")
    if r is None or r.status_code != 200:
        r = get(f"https://www.workable.com/api/accounts/{slug}", params={"details": "false"})
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    out = []
    for j in data.get("jobs", []):
        locs = [", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)]
        for l in j.get("locations", []) or []:
            locs.append(", ".join(x for x in (l.get("city"), l.get("country")) if x))
        out.append(dict(id=j.get("shortcode") or j.get("id"), title=j.get("title", ""), location="; ".join(dict.fromkeys(l for l in locs if l)),
                        url=j.get("url") or j.get("shortlink"), posted=_iso(j.get("published_on") or j.get("created_at"))))
    return out


def smartrecruiters(slug):
    r = get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings", params={"limit": 100})
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    if not data.get("totalFound"):
        return None
    out = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        out.append(dict(id=j["id"], title=j.get("name", ""), location=", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
                        url=f"https://jobs.smartrecruiters.com/{slug}/{j['id']}", posted=_iso(j.get("releasedDate"))))
    return out


def recruitee(slug):
    r = get(f"https://{slug}.recruitee.com/api/offers/")
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    out = []
    for j in data.get("offers", []):
        out.append(dict(id=str(j["id"]), title=j.get("title", ""), location=", ".join(x for x in (j.get("location"), j.get("country")) if x),
                        url=j.get("careers_url"), posted=_iso(j.get("published_at"))))
    return out


READERS = {
    "greenhouse": greenhouse,
    "lever": lever,
    "ashby": ashby,
    "workable": workable,
    "smartrecruiters": smartrecruiters,
    "recruitee": recruitee,
}


# ---------- Special sources ----------
def amazon_uk():
    """Amazon's public search JSON, UK science/ML roles."""
    out = []
    for q in ("machine learning", "applied scientist", "research scientist", "data scientist"):
        r = get("https://www.amazon.jobs/en/search.json",
                params={"base_query": q, "country": "GBR", "result_limit": 100, "sort": "recent"})
        if r is None or r.status_code != 200:
            continue
        try:
            for j in r.json().get("jobs", []):
                out.append(dict(id=str(j.get("id_icims") or j.get("id")), title=j.get("title", ""),
                                location=j.get("normalized_location") or j.get("location", ""),
                                url="https://www.amazon.jobs" + (j.get("job_path") or ""), posted=None))
        except ValueError:
            continue
    uniq = {j["id"]: j for j in out}
    return list(uniq.values())


JOBS_AC_RE = re.compile(r'href="(/job/([A-Z0-9]+)/[^"]+)"[^>]*>\s*(.*?)\s*</a>', re.S)


def jobs_ac_uk(keywords, pages=3):
    """Parse jobs.ac.uk search results. Returns jobs with employer/location when found."""
    out = {}
    for p in range(pages):
        r = get("https://www.jobs.ac.uk/search/", params={"keywords": keywords, "sortOrder": 1, "pageSize": 25, "startIndex": 1 + 25 * p})
        if r is None or r.status_code != 200:
            break
        page = r.text
        # each result block: split on result container
        blocks = re.split(r'class="j-search-result__result', page)[1:] or [page]
        found = 0
        for b in blocks:
            m = JOBS_AC_RE.search(b)
            if not m:
                continue
            path, code, title = m.groups()
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            emp = re.search(r'class="j-search-result__employer"[^>]*>(.*?)</', b, re.S)
            loc = re.search(r'Location:\s*</[^>]+>\s*(.*?)<', b, re.S) or re.search(r'class="j-search-result__location"[^>]*>(.*?)</', b, re.S)
            sal = re.search(r'Salary:\s*</[^>]+>\s*(.*?)<', b, re.S)
            closes = re.search(r'Closes:\s*</[^>]+>\s*(.*?)<', b, re.S) or re.search(r'Closes:\s*(\d{1,2}\w*\s+\w+(?:\s+\d{4})?)', b)
            clean = lambda x: html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", x.group(1)))).strip() if x else None
            out[code] = dict(id=code, title=title, employer=clean(emp), location=clean(loc) or "", salary=clean(sal),
                             closes_text=clean(closes), url="https://www.jobs.ac.uk" + path, posted=None)
            found += 1
        if found < 20:
            break
    return list(out.values())


CAM_ROW_RE = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)


def cam_research():
    """University of Cambridge research vacancies table."""
    out = []
    for term in ("research", "academic"):
        r = get(f"https://www.cam.ac.uk/jobs/term/{term}")
        if r is None or r.status_code != 200:
            continue
        for row in CAM_ROW_RE.findall(r.text):
            link = re.search(r'href="(/jobs/[^"]+)"[^>]*>(.*?)</a>', row, re.S)
            if not link:
                continue
            cells = [html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c))).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            ref = re.search(r"\b([A-Z]{2}\d{5})\b", row)
            title = html.unescape(re.sub(r"<[^>]+>", "", link.group(2))).strip()
            out.append(dict(id=ref.group(1) if ref else link.group(1).rsplit("-", 1)[-1], title=title,
                            department=cells[1] if len(cells) > 1 else "", salary=cells[2] if len(cells) > 2 else None,
                            closes_text=cells[5] if len(cells) > 5 else None, location="Cambridge",
                            url="https://www.cam.ac.uk" + link.group(1), posted=None))
    return list({j["id"]: j for j in out}.values())
