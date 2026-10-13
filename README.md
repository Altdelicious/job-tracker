# ML Job Radar

Hourly scan of UK job boards for research, ML engineering and data science roles at AI labs, startups and universities in London, Cambridge and Oxford. Results are shown on a private Claude page.

## How it works

| Step | Where | When |
|---|---|---|
| Find each company's job board (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee) | `radar/discover.py` → `config/boards.json` | When `config/companies.json` changes, weekly, or on demand |
| Fetch all boards, Amazon UK, jobs.ac.uk and Cambridge vacancies; keep UK ML/research roles; score them | `radar/fetch.py` → `data/jobs.json`, `data/status.json` | Hourly (GitHub Actions) |
| Copy results into the radar page | Claude scheduled task using `radar/sync_plan.py` | A few times a day |

## Common edits

- **Add a company:** add an entry to `config/companies.json` (name, city, focus, type `lab`/`startup`, fit `H`/`M`/`L`). The board finder runs automatically on push.
- **Add a board by hand:** add an entry to `config/boards.json` with `"source": "manual"`, e.g. `{"company": "Wayve", "ats": "greenhouse", "slug": "wayve", "type": "startup", "fit": "H", "enabled": true, "source": "manual"}`.
- **Review uncertain boards:** `data/discovery_report.json` lists boards found with low confidence (disabled). Set `"enabled": true` in `config/boards.json` after checking.
- **Change what counts as relevant:** title include/exclude patterns and scoring live in `radar/common.py`.

## Run locally

```bash
pip install -r requirements.txt
python -m radar.discover          # find boards
python -m radar.fetch             # fetch and score jobs
```
