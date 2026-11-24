# Job Radar

A personal job-search pipeline that finds **real, early-career software and AI jobs posted in the last 24 hours**, checks each one the way a careful applicant would, and ranks them against my tailored resumes.

Job boards like LinkedIn and aggregator lists are full of reposts, months-old openings shown as "new", staffing agencies, and senior roles with junior-sounding titles. Job Radar skips them and reads company job boards directly.

## What it does

- **Reads ~1,000 company job boards directly** (Greenhouse, Lever, Ashby, Workday, iCIMS, Oracle, SmartRecruiters, Workable, Amazon), about 60,000 jobs per run in ~6 minutes, plus public daily new-grad lists and LinkedIn's public search.
- **Discovers new companies automatically** from the daily lists, so coverage grows on its own.
- **Verifies the real posting date** at the source (Greenhouse `first_published`, Ashby `publishedAt`, Lever `createdAt`, Workday `startDate`, …). A job a list shows as "new" but that was posted months ago is dropped with its real age.
- **Filters for fit:** US only, target roles (backend, full-stack, frontend, AI/ML), 0-2 years required, no "will not sponsor" / citizenship-only / clearance roles, no staffing agencies.
- **Reads experience requirements carefully:** the main must-have (not the smallest number in the post), numbers written as words, Master's-degree alternatives, "preferred" sections ignored, and senior wording in the description ("seeking a Senior…", "proven track record").
- **Matches each job to the right resume** out of several role-tailored versions, scores the fit, and separates skills that are on another resume from real gaps. Skills are matched by meaning (Postgres = PostgreSQL), and "one of Java, C++, or C#" lists don't count the alternatives as missing.
- **Dashboard** with Fresh / Saved / Applied / Hidden tabs, role and match filters, and Apply links.
- **Runs every 3 hours** and sends a Mac notification for new strong matches.
- **Logs why every job was dropped**, so filters can be audited and tuned.

## How it's built

Plain Python standard library, no dependencies: `urllib` for the job board APIs, `sqlite3` for state (first-seen times, statuses, verified dates), `http.server` for the dashboard, and `launchd` for scheduling.

```
run.py            collect -> filter -> verify dates -> merge duplicates -> match -> notify
server.py         local dashboard API (127.0.0.1 only)
dashboard.html    the dashboard UI
radar/sources.py  one fetcher per job system, all returning the same job shape
radar/lists.py    daily new-grad lists, company discovery, LinkedIn guest search
radar/filters.py  freshness, role, location, years, sponsorship and staffing rules
radar/verify.py   real posting date lookups at the source
radar/match.py    skill extraction and resume matching
```

## Running it

```
python3 run.py              # one collection run (add --no-linkedin to skip LinkedIn)
python3 server.py           # dashboard at http://localhost:8787
```

Resumes go in `resumes/tex/<role>.tex` (git-ignored). `launchd/` has the macOS agents for the 3-hour schedule and an always-on dashboard.
