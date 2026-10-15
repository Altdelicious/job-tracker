# ML Job Radar

Daily scan of UK job boards for research, ML engineering and data science roles at AI labs, startups and universities in London, Cambridge and Oxford. Results are shown on a private Claude page.

## How it works

| Step | Where | When |
|---|---|---|
| Find each company's job board (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee) | `radar/discover.py` → `config/boards.json` | When `config/companies.json` changes, weekly, or on demand |
| Fetch all boards, Amazon UK, jobs.ac.uk and Cambridge vacancies; keep UK ML/research roles; score them | `radar/fetch.py` → `data/jobs.json`, `data/status.json` | Daily at 01:17 UTC (GitHub Actions; often starts hours late) |
| Copy results into the radar page | GitHub writes ready-made files to `data/page/`; a Claude scheduled task copies them (it runs no repo code) | Daily at 09:12 London time |

## Common edits

- **Add a company:** add an entry to `config/companies.json` (name, city, focus, type `lab`/`startup`, fit `H`/`M`/`L`). The board finder runs automatically on push.
- **Add a board by hand:** add an entry to `config/boards.json` with `"source": "manual"`, e.g. `{"company": "Wayve", "ats": "greenhouse", "slug": "wayve", "type": "startup", "fit": "H", "enabled": true, "source": "manual"}`.
- **Review uncertain boards:** `data/discovery_report.json` lists boards found with low confidence (disabled). Set `"enabled": true` in `config/boards.json` after checking.
- **JavaScript careers pages:** GitHub runs a headless browser (Playwright) so pages that build their job lists with JavaScript are read too.
- **Hacker News:** the monthly "Who is hiring?" threads are scanned for UK ML/research roles (free Algolia API, no key).
- **Adzuna (optional, paid):** code is present but skipped unless `ADZUNA_APP_ID`/`ADZUNA_APP_KEY` secrets are set.
- **Change what counts as relevant:** title include/exclude patterns and scoring live in `radar/common.py`.

## Run locally

```bash
pip install -r requirements.txt
python -m radar.discover          # find boards
python -m radar.fetch             # fetch and score jobs
```
