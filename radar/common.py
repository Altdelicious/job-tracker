"""Shared helpers: HTTP, location and title filters, scoring."""
import json
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CONFIG = ROOT / "config"

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "ml-job-radar/1.0 (personal job search; contact via GitHub)"


PROBE = {"on": False}  # discovery mode: fail fast, no retries
HTTP_LOG = {}  # url -> last status code or exception name, for diagnosing failed boards


def get(url, *, params=None, timeout=25, retries=2):
    """GET with small retry; returns Response or None."""
    if PROBE["on"]:
        timeout, retries = 10, 0
    for attempt in range(retries + 1):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            HTTP_LOG[url] = r.status_code
            if r.status_code in (429, 503) and attempt < retries:
                time.sleep(int(r.headers.get("Retry-After", 0) or 0) or 5 * (attempt + 1))
                continue
            return r
        except requests.RequestException as e:
            HTTP_LOG[url] = e.__class__.__name__
            if attempt == retries:
                return None
            time.sleep(2)
    return None


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False, sort_keys=False) + "\n")


# ---------- Location ----------
UK_PLACES = (
    r"london|cambridge|oxford|edinburgh|manchester|bristol|glasgow|leeds|sheffield|birmingham|"
    r"belfast|cardiff|nottingham|brighton|reading|guildford|milton keynes|bath|york|newcastle|"
    r"liverpool|southampton|harwell|stevenage|hatfield|united kingdom|\buk\b|u\.k\.|england|scotland|wales|great britain|\bgb\b|\bgbr\b"
)
UK_RE = re.compile(UK_PLACES, re.I)
NOT_UK_RE = re.compile(
    r"new york|new england|new south wales|"
    r"cambridge,?\s*(ma|massachusetts|us|usa)\b|london,?\s*(on|ontario|canada|ky|kentucky)\b|oxford,?\s*(ms|oh|mississippi|ohio)\b|"
    r"manchester,?\s*(nh|new hampshire)\b|birmingham,?\s*(al|alabama|mi|michigan)\b|reading,?\s*(pa|pennsylvania)\b|"
    r"bath,?\s*(me|maine|ny)\b|york,?\s*(pa|pennsylvania)\b|bristol,?\s*(ct|tn|connecticut|tennessee)\b",
    re.I)
REMOTE_EU_RE = re.compile(r"remote.*(emea|europe)|(emea|europe).*remote", re.I)


def is_uk(*locations):
    text = " | ".join(l for l in locations if l)
    if not text:
        return False
    cleaned = NOT_UK_RE.sub("", text)
    return bool(UK_RE.search(cleaned)) or bool(REMOTE_EU_RE.search(text))


def city_tags(location):
    l = (location or "").lower()
    l = NOT_UK_RE.sub("", l)
    return [c for c in ("london", "cambridge", "oxford") if c in l]


# ---------- Title filtering ----------
INCLUDE = re.compile(
    r"machine learning|\bml\b|\bai\b|a\.i\.|artificial intelligence|deep learning|research (scientist|engineer|associate|assistant|fellow)|"
    r"researcher|applied scientist|data scientist|data science|computer vision|perception|\bnlp\b|natural language|"
    r"\bllm|language model|foundation model|generative|reinforcement learning|robot|autonom|"
    r"member of technical staff|\bmts\b|research software engineer|speech|audio ml|multimodal|"
    r"inference|training (infrastructure|performance)|model (training|evaluation)|evals?\b|alignment|interpretability|"
    r"fellowship|residency|resident\b|imaging|biomedical|bioinformatic|computational (biolog|chem|scien)|"
    r"postdoc|post-doc|post doctoral|postdoctoral|statistic|quantitative research",
    re.I,
)
EXCLUDE = re.compile(
    r"(?<!technical )\bstaff\b|\b(principal|distinguished|director|head of|head,|vp\b|vice president|chief|cto|manager|"
    r"sales|account executive|account manager|recruit|talent|people partner|hr\b|legal|counsel|paralegal|"
    r"marketing|communications|finance|accountant|payroll|procurement|office|executive assistant|"
    r"customer success|support specialist|solutions architect|sales engineer|partnerships|"
    r"lecturer|professor|reader in|teaching|technician|nurse|clinical fellow|phd studentship|studentship|"
    r"data associate|annotat|linguist|language specialist|transcri|strategist|evangelist|advocate|"
    r"policy|government affairs|public affairs|security officer|facilities|workplace|events)",
    re.I,
)
SENIOR = re.compile(r"\b(senior|sr\.?|lead)\b", re.I)
EARLY = re.compile(r"\b(intern|internship|graduate|junior|assistant|fellow|residen|new grad|early career|placement)", re.I)


def wanted_title(title):
    if not title:
        return False
    if EXCLUDE.search(title):
        return False
    return bool(INCLUDE.search(title))


# ---------- Academic posts ----------
# Topic must be clearly AI/ML/CV/data; generic "Research Assistant" titles only
# pass when the department is computing-related.
ACADEMIC_TOPIC = re.compile(
    r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|neural network|computer vision|"
    r"\bvision\b|image (analysis|processing|understanding)|medical imag|imaging ai|biomedical image|"
    r"robot (learning|perception)|robot learning|\brobotics\b|autonomous|perception|"
    r"data[- ]driven|data scien|data scientist|statistical learning|probabilistic|bayesian|"
    r"language model|\bllm|\bnlp\b|natural language|speech recognition|reinforcement learning|"
    r"foundation model|generative|signal processing|computational imaging",
    re.I)
COMPUTING_DEPT = re.compile(r"computer science|computer laboratory|computing|informatics|machine learning|engineering \(information", re.I)
# Grades a Master's graduate can be appointed at.
MASTERS_GRADE = re.compile(
    r"research assistant|research engineer|research software engineer|software engineer|ktp associate|"
    r"machine learning (scientist|engineer)|data scientist|research technician|\bresearcher\b(?! in residence)",
    re.I)
# Titles that signal a PhD is required.
NEEDS_PHD = re.compile(
    r"post[- ]?doc|postdoctoral|post doctoral|research fellow|fellowship|senior research|senior researcher|"
    r"lecturer|professor|principal investigator|group leader|clinical research",
    re.I)


def academic_ok(title, department=""):
    """True for an academic post that is about AI/ML and open to a Master's graduate."""
    t = title or ""
    if NEEDS_PHD.search(t):
        return False
    if re.search(r"theolog|archaeolog|histor|\bart\b|music|philosoph|\blaw\b|legal|politic|literat|classics|religio|ethic", t, re.I):
        return False
    # A plain "Research Associate" (without "Assistant") is the post-PhD grade.
    if re.search(r"research associate", t, re.I) and not re.search(r"assistant", t, re.I) and not re.search(r"ktp", t, re.I):
        return False
    if not MASTERS_GRADE.search(t) and not re.search(r"ktp|scientist|engineer", t, re.I):
        return False
    if ACADEMIC_TOPIC.search(t):
        return True
    # Generic title ("Research Assistant (Fixed Term)"): accept only in a computing department.
    generic = not re.search(r"\bin\b|[-–:]", re.sub(r"\(.*?\)", "", t))
    return generic and bool(COMPUTING_DEPT.search(department or ""))


def level(title):
    if SENIOR.search(title or ""):
        return "senior"
    if EARLY.search(title or ""):
        return "early"
    return "mid"


TAGS = {
    "research": r"research|scientist|fellow|postdoc|post-doc|residen",
    "engineering": r"engineer|technical staff|developer|software|\bmts\b",
    "data science": r"data scien|analytics|statistic|quantitative",
    "vision": r"vision|imag|perception|(?<!prime )video|\b3d\b|visual|camera|lidar|avatar",
    "health": r"medical|health|clinical|biomed|bioinformat|biolog|drug|patholog|radiolog|genom|protein|molecul",
    "autonomy": r"autonom|robot|driving|self-driving|embodied|navigation|slam",
    "llm": r"\bllm|language model|nlp|natural language|generative|foundation model|agent",
    "speech": r"speech|audio|voice",
}


def tags(title):
    return [k for k, p in TAGS.items() if re.search(p, title or "", re.I)]


# ---------- Scoring against the profile ----------
# Profile: MPhil MLMI (Cambridge, 2027), EE IIT Bombay, ~3y medical imaging,
# healthcare AI and self-driving perception. Wants research/ML engineering roles.
FIT_BONUS = {"H": 1, "M": 0, "L": -1}


def score(title, company_type, fit="M"):
    """1-5. Roughly: 5 = core research/ML role in your domains at a strong-fit
    employer; 4 = core role at a strong-fit employer, or core role in your
    domains elsewhere; 3 = relevant but adjacent; 2 = needs a PhD or weak fit."""
    t = title or ""
    tg = tags(t)
    s = 2
    reasons = []
    if re.search(r"research (engineer|scientist)|applied scientist|member of technical staff|\bmts\b|machine learning engineer|ml engineer|research software engineer|ai engineer|fellows? program|fellowship|residency", t, re.I):
        s += 1
        reasons.append("core research or ML engineering role")
    if "vision" in tg or "health" in tg or "autonomy" in tg:
        s += 1
        hit = [x for x in ("vision", "health", "autonomy") if x in tg]
        reasons.append("matches your " + " / ".join({"vision": "computer vision and perception", "health": "medical and healthcare AI", "autonomy": "autonomy and robotics"}[h] for h in hit) + " background")
    if re.search(r"postdoc|post-doc|postdoctoral|senior research associate|research fellow", t, re.I):
        s -= 2
        reasons.append("usually needs a PhD")
    elif company_type == "academic" and re.search(r"research associate", t, re.I) and not re.search(r"assistant", t, re.I):
        s -= 1
        reasons.append("Research Associate grade often expects a PhD")
    elif company_type == "academic" and re.search(r"research assistant|assistant/associate|ktp", t, re.I):
        s += 1
        reasons.append("grade open to Master's graduates")
    if re.search(r"intern|internship|placement", t, re.I):
        s -= 1
        reasons.append("internship")
    if re.search(r"infrastructure|platform|devops|sre|site reliability|backend|frontend|full[- ]stack", t, re.I) and "core research or ML engineering role" not in reasons:
        s -= 1
        reasons.append("more infrastructure than modelling")
    if re.search(r"data scientist|data science", t, re.I):
        reasons.append("data science role")
    if company_type == "academic":
        s += 1  # academic posts are scored on grade and topic, not employer fit
    else:
        s += max(0, FIT_BONUS.get(fit, 0))
        if fit == "H":
            reasons.append("employer close to your interests")
        elif fit == "L":
            s -= 1
    s = max(1, min(5, s))
    why = "; ".join(reasons) if reasons else "relevant ML or data role"
    return s, why[0].upper() + why[1:] + "."
