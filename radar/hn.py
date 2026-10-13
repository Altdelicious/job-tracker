"""Hacker News "Ask HN: Who is hiring?" — monthly thread where startups post openings.

Uses the free Algolia HN API (no key). Keeps top-level posts whose first line
mentions a UK location and whose role titles pass the same relevance filter
as everything else. Posts are free text, so a role title is taken from the
header segments ("Company | Role | Location | ...") when one matches.
"""
import html
import re

from .common import get, is_uk, wanted_title

API = "https://hn.algolia.com/api/v1"


def latest_threads(n=2):
    r = get(f"{API}/search_by_date", params={"tags": "story,author_whoishiring", "query": "who is hiring", "hitsPerPage": 6})
    if r is None or r.status_code != 200:
        return None
    hits = [h for h in r.json().get("hits", []) if "who is hiring" in (h.get("title") or "").lower()]
    return [(h["objectID"], h.get("title")) for h in hits[:n]]


def _clean(t):
    t = re.sub(r"<p>", "\n", t or "")
    t = re.sub(r"<a [^>]*href=\"([^\"]+)\"[^>]*>.*?</a>", r"\1", t)
    return html.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def posts():
    threads = latest_threads()
    if threads is None:
        return None
    out = []
    for tid, ttitle in threads:
        r = get(f"{API}/items/{tid}", timeout=40)
        if r is None or r.status_code != 200:
            continue
        for c in r.json().get("children", []):
            text = _clean(c.get("text"))
            if not text:
                continue
            header = text.split("\n", 1)[0][:400]
            segs = [s.strip() for s in re.split(r"\s[|•·–—]\s|\s\|\s|\|", header) if s.strip()]
            if len(segs) < 2:
                continue
            loc_segs = [s for s in segs if is_uk(s)]
            if not loc_segs:
                continue
            company = re.sub(r"\(.*?\)|https?://\S+", "", segs[0]).strip()[:60]
            # role titles: header segments that look like jobs; else role-looking lines in the body
            roles = [s for s in segs[1:] if wanted_title(s) and len(s) < 120]
            if not roles:
                roles = [ln.strip(" -*•") for ln in text.split("\n")[1:12]
                         if 8 < len(ln) < 100 and wanted_title(ln) and re.search(r"engineer|scientist|researcher", ln, re.I)]
            for role in roles[:4]:
                for part in re.split(r",\s*(?=[A-Z])|\s/\s|;\s*", role):
                    if not wanted_title(part):
                        continue
                    out.append(dict(id=f'{c["id"]}-{re.sub(r"[^a-z0-9]+", "", part.lower())[:20]}', title=part.strip()[:110],
                                    company=company, location=", ".join(loc_segs)[:80],
                                    url=f'https://news.ycombinator.com/item?id={c["id"]}', posted=(c.get("created_at") or "")[:10] or None,
                                    thread=ttitle))
    return out
