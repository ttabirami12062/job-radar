"""Read jobs straight from company job boards (Greenhouse, Lever, Ashby, Workday).

Every fetcher returns the same shape, so the filters never care where a job came from.
"""
import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (job-radar personal job search)"}


# Workday rate-limits hard (HTTP 429) when many companies are asked at once.
WORKDAY_SLOTS = threading.Semaphore(4)


def get_json(url, body=None, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    headers = dict(UA)
    if data:
        headers["Content-Type"] = "application/json"
    for attempt in range(4):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))


def parse_time(s):
    # Python 3.9's fromisoformat can't read "Z" or 2-digit fractions, so tidy first.
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    m = re.match(r"(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)", s)
    if m:
        frac = (m.group(2) or ".0")[1:7].ljust(6, "0")
        s = f"{m.group(1)}.{frac}{m.group(3)}"
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def strip_html(s):
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()


def job(company, ats, job_id, title, location, url, posted_at, description, posted_label=""):
    return {
        "key": f"{ats}:{company}:{job_id}",
        "company": company,
        "ats": ats,
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "url": url,
        "posted_at": posted_at.astimezone(timezone.utc).isoformat() if posted_at else None,
        "posted_label": posted_label,
        "description": description or "",
    }


def greenhouse(slug):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", timeout=40)
    out = []
    for j in d.get("jobs", []):
        # first_published is the real post date; updated_at changes on every edit,
        # which is how old jobs sneak back in as "new" on other sites.
        posted = parse_time(j.get("first_published")) or parse_time(j.get("updated_at"))
        out.append(job(j.get("company_name") or slug, "greenhouse", j["id"], j["title"],
                       (j.get("location") or {}).get("name"), j["absolute_url"], posted,
                       strip_html(j.get("content"))))
    return out


def lever(slug):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json", timeout=40)
    out = []
    for j in d:
        posted = datetime.fromtimestamp(j["createdAt"] / 1000, tz=timezone.utc) if j.get("createdAt") else None
        lists = "\n".join(f"{l.get('text', '')}\n{strip_html(l.get('content'))}" for l in j.get("lists", []))
        desc = "\n".join([j.get("descriptionPlain") or "", lists, j.get("additionalPlain") or ""])
        cats = j.get("categories") or {}
        loc = cats.get("location") or ", ".join(cats.get("allLocations") or [])
        out.append(job(slug, "lever", j["id"], j["text"], loc, j["hostedUrl"], posted, desc))
    return out


def ashby(slug):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", timeout=40)
    out = []
    for j in d.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
        if j.get("isRemote") and "remote" not in " ".join(locs).lower():
            locs.append("Remote")
        out.append(job(slug, "ashby", j["id"], j["title"], " / ".join(l for l in locs if l),
                       j["jobUrl"], parse_time(j.get("publishedAt")), j.get("descriptionPlain")))
    return out


WORKDAY_SEARCHES = ["software engineer", "software developer", "machine learning", "new grad"]


def workday_posted(label, now):
    # Workday only says "Posted Today" / "Posted Yesterday" / "Posted 3 Days Ago".
    label = (label or "").lower()
    if "today" in label:
        return now
    if "yesterday" in label:
        # Could be anywhere from 24 to 47 hours ago, so don't count it as fresh by date alone.
        return now - timedelta(hours=36)
    m = re.search(r"(\d+)\+? days", label)
    return now - timedelta(days=int(m.group(1))) if m else None


def workday(slug, title_ok=None):
    with WORKDAY_SLOTS:
        return _workday(slug, title_ok)


def _workday(slug, title_ok=None):
    tenant, wd, site = slug.split("|")
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{base}/wday/cxs/{tenant}/{site}"
    now = datetime.now(timezone.utc)
    seen, out = set(), []
    for term in WORKDAY_SEARCHES:
        d = get_json(f"{api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term})
        for p in d.get("jobPostings", []):
            path = p.get("externalPath")
            if not path or path in seen:
                continue
            seen.add(path)
            label = p.get("postedOn", "")
            posted = workday_posted(label, now)
            # Descriptions cost one extra request each, so only fetch them for
            # fresh jobs whose title already looks right.
            desc = ""
            if (not posted or now - posted <= timedelta(days=2)) and (title_ok is None or title_ok(p.get("title", ""))):
                try:
                    info = get_json(f"{api}{path}").get("jobPostingInfo", {})
                    desc = strip_html(info.get("jobDescription"))
                except Exception:
                    pass
            # The same job shows up under several career sites (External, external, annarbor),
            # so key it on the requisition id at the end of the path.
            req = re.sub(r"-\d+$", "", path.rsplit("_", 1)[-1]).lower()
            loc = p.get("locationsText") or ""
            if not loc or re.match(r"\d+ locations", loc, re.I):
                loc = f"{loc} {path.split('/')[2].replace('-', ' ')}".strip()
            out.append(job(tenant, "workday", req, p.get("title"), loc,
                           f"{base}/{site}{path}", posted, desc, label))
    return out


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}
