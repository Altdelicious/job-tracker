"""Prepare the documents the radar page reads, from data/ and config/.

Writes JSON files to --out:
  feed/part-0.json, part-1.json ...  each {"jobs": [...]} under ~180 KB
  meta/status.json                    run status for the page header
  config/companies.json               company list with "tracked" flags
  manifest.json                       list of {collection, doc_id, file}
Run: python -m radar.sync_plan --out /tmp/radar-sync
"""
import argparse
import json
from pathlib import Path

from .common import CONFIG, DATA, load_json

LIMIT = 180_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    (out / "feed").mkdir(parents=True, exist_ok=True)
    (out / "meta").mkdir(parents=True, exist_ok=True)
    (out / "config").mkdir(parents=True, exist_ok=True)
    manifest = []

    jobs = load_json(DATA / "jobs.json", {"jobs": []})["jobs"]
    parts, cur, size = [], [], 0
    for j in jobs:
        n = len(json.dumps(j, ensure_ascii=False))
        if cur and size + n > LIMIT:
            parts.append(cur)
            cur, size = [], 0
        cur.append(j)
        size += n
    if cur or not parts:
        parts.append(cur)
    for i, p in enumerate(parts):
        f = out / "feed" / f"part-{i}.json"
        f.write_text(json.dumps({"jobs": p}, ensure_ascii=False))
        manifest.append({"collection": "feed", "doc_id": f"part-{i}", "file": str(f)})

    st = load_json(DATA / "status.json", {})
    rep = load_json(DATA / "discovery_report.json", {})
    boards = load_json(CONFIG / "boards.json", {"boards": []})["boards"]
    enabled = [b for b in boards if b.get("enabled", True)]
    notes = []
    if st.get("boardsFailed"):
        notes.append("Couldn't read this run: " + ", ".join(st["boardsFailed"]) + ".")
    for n in st.get("notes", []):
        if "failed" in n.lower():
            notes.append(n)
    nf = rep.get("notFound", [])
    if nf:
        notes.append(f"{len(nf)} companies have no job board found yet (custom careers sites): " + ", ".join(nf[:40]) + ("…" if len(nf) > 40 else ""))
    enabled_names = {b["company"] for b in enabled}
    low = [x for x in rep.get("lowConfidence", []) if x.split(" → ")[0] not in enabled_names]
    if low:
        notes.append(f"{len(low)} possible boards need a check before they're used: " + "; ".join(low[:15]) + ("…" if len(low) > 15 else ""))
    status = {
        "lastRun": st.get("lastRun"), "sourcesOk": st.get("boardsOk", 0) + 3, "sourcesTotal": st.get("boardsTotal", 0) + 3,
        "jobsActive": st.get("jobsActive", 0), "newThisRun": st.get("newThisRun", 0), "coverageNotes": notes,
        "feedParts": len(parts), "pipeline": "github",
    }
    f = out / "meta" / "status.json"
    f.write_text(json.dumps(status, ensure_ascii=False))
    manifest.append({"collection": "meta", "doc_id": "status", "file": str(f)})

    tracked = {b["company"] for b in enabled}
    cos = load_json(CONFIG / "companies.json", {"companies": []})["companies"]
    for c in cos:
        c["tracked"] = c["name"] in tracked or (c["name"].startswith("Amazon"))
    f = out / "config" / "companies.json"
    f.write_text(json.dumps({"companies": cos, "count": len(cos)}, ensure_ascii=False))
    manifest.append({"collection": "config", "doc_id": "companies", "file": str(f)})

    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(jobs)} jobs in {len(parts)} part(s); {len(tracked)} boards tracked; manifest at {out/'manifest.json'}")


if __name__ == "__main__":
    main()
