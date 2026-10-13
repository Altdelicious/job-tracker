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


# ---------- More hiring platforms (found via careers-page detection) ----------
import xml.etree.ElementTree as ET  # noqa: E402
from urllib.parse import urljoin, urlparse  # noqa: E402


def _xml_text(el, *names):
    for n in names:
        for child in el.iter():
            if child.tag.split("}")[-1] == n and (child.text or "").strip():
                return child.text.strip()
    return ""


def teamtailor(slug):
    """slug is a Teamtailor subdomain or a full careers-site base URL."""
    base = slug if "://" in slug else f"https://{slug}.teamtailor.com"
    r = get(base.rstrip("/") + "/jobs.rss")
    if r is None or r.status_code != 200 or "<rss" not in r.text[:500]:
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        return None
    out = []
    for it in root.iter("item"):
        locs = [_xml_text(l, "city", "name") for l in it.iter() if l.tag.split("}")[-1] == "location"]
        link = _xml_text(it, "link")
        out.append(dict(id=link.rstrip("/").rsplit("/", 1)[-1][:12] or _xml_text(it, "guid")[-12:], title=_xml_text(it, "title"),
                        location="; ".join(dict.fromkeys(l for l in locs if l)), url=link, posted=_iso(None)))
    return out


def personio(slug):
    for tld in ("de", "com"):
        r = get(f"https://{slug}.jobs.personio.{tld}/xml")
        if r is None or r.status_code != 200 or "<workzag-jobs" not in r.text[:300]:
            continue
        try:
            root = ET.fromstring(r.content)
        except ET.ParseError:
            return None
        out = []
        for p in root.iter("position"):
            pid = _xml_text(p, "id")
            offices = [_xml_text(p, "office")] + [o.text or "" for o in p.iter("office")]
            out.append(dict(id=pid, title=_xml_text(p, "name"), location="; ".join(dict.fromkeys(o for o in offices if o)),
                            url=f"https://{slug}.jobs.personio.{tld}/job/{pid}", posted=_iso(_xml_text(p, "createdAt"))))
        return out
    return None


def pinpoint(slug):
    r = get(f"https://{slug}.pinpointhq.com/postings.json")
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json().get("data", [])
    except ValueError:
        return None
    out = []
    for j in data:
        loc = j.get("location") or {}
        out.append(dict(id=str(j.get("id")), title=j.get("title", ""),
                        location=", ".join(x for x in (loc.get("city"), loc.get("province"), loc.get("name")) if x) if isinstance(loc, dict) else str(loc),
                        url=j.get("url"), posted=None))
    return out


def bamboohr(slug):
    r = get(f"https://{slug}.bamboohr.com/careers/list")
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json().get("result", [])
    except ValueError:
        return None
    out = []
    for j in data:
        loc = j.get("location") or {}
        out.append(dict(id=str(j.get("id")), title=j.get("jobOpeningName", ""),
                        location=", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x) if isinstance(loc, dict) else "",
                        url=f"https://{slug}.bamboohr.com/careers/{j.get('id')}", posted=None))
    return out


def breezy(slug):
    r = get(f"https://{slug}.breezy.hr/json")
    if r is None or r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    out = []
    for j in data if isinstance(data, list) else []:
        loc = j.get("location") or {}
        out.append(dict(id=str(j.get("id")), title=j.get("name", ""),
                        location=", ".join(x for x in (loc.get("city"), (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else loc.get("country")) if x) if isinstance(loc, dict) else "",
                        url=j.get("url"), posted=_iso(j.get("published_date"))))
    return out


def workday(slug):
    """slug: 'tenant|wdN|site'. Uses Workday's public careers-site search endpoint."""
    try:
        tenant, wd, site = slug.split("|")
    except ValueError:
        return None
    from .common import SESSION
    out, offset = [], 0
    while offset < 400:
        try:
            r = SESSION.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                             json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""}, timeout=25)
        except Exception:  # noqa: BLE001
            return out or None
        if r.status_code != 200:
            return out or None
        posts = r.json().get("jobPostings", [])
        for j in posts:
            path = j.get("externalPath", "")
            out.append(dict(id=path.rsplit("_", 1)[-1] or path[-12:], title=j.get("title", ""), location=j.get("locationsText", ""),
                            url=f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}", posted=None))
        if len(posts) < 20:
            break
        offset += 20
    return out


ROLE_NOUN = re.compile(r"engineer|scientist|researcher|research (assistant|associate)|developer|analyst|intern\b|internship|"
                       r"fellow|resident|specialist|architect|technical staff", re.I)


def page(url):
    """Plain careers page: pull job-like link texts. Location is unknown (caller falls back to company city)."""
    r = get(url)
    if r is None or r.status_code != 200:
        return None
    out, seen = [], set()
    for href, text in re.findall(r'<a\b[^>]*href="([^"#]+)"[^>]*>(.*?)</a>', r.text, re.S | re.I):
        t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))).strip()
        if not (8 <= len(t) <= 120) or not ROLE_NOUN.search(t):
            continue
        link = urljoin(url, href)
        if link in seen or urlparse(link).scheme not in ("http", "https"):
            continue
        seen.add(link)
        out.append(dict(id=re.sub(r"[^A-Za-z0-9]+", "", link.rsplit("/", 1)[-1] or link)[-24:] or str(abs(hash(link)))[:12],
                        title=t, location="", url=link, posted=None))
    return out


READERS.update({
    "teamtailor": teamtailor, "personio": personio, "pinpoint": pinpoint,
    "bamboohr": bamboohr, "breezy": breezy, "workday": workday, "page": page,
})


def adzuna(app_id, app_key, queries, wheres, pages=2):
    """Adzuna UK job search. Returns raw ads with company names."""
    out = {}
    for what in queries:
        for where in wheres:
            for p in range(1, pages + 1):
                r = get(f"https://api.adzuna.com/v1/api/jobs/gb/search/{p}",
                        params={"app_id": app_id, "app_key": app_key, "what_phrase": what, "where": where,
                                "distance": 15, "results_per_page": 50, "max_days_old": 30, "content-type": "application/json"})
                if r is None or r.status_code != 200:
                    break
                try:
                    res = r.json().get("results", [])
                except ValueError:
                    break
                for j in res:
                    out[str(j.get("id"))] = dict(id=str(j.get("id")), title=html.unescape(re.sub(r"<[^>]+>", "", j.get("title", ""))),
                                                 company=(j.get("company") or {}).get("display_name", ""),
                                                 location=(j.get("location") or {}).get("display_name", ""),
                                                 url=j.get("redirect_url"), posted=_iso(j.get("created")))
                if len(res) < 50:
                    break
    return list(out.values())
