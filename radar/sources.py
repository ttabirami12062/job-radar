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
WORKABLE_SLOTS = threading.Semaphore(2)


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


# ── MORE COMPANY JOB SYSTEMS ──
# Sources whose dates are only a day (or missing) are "coarse": the filters lean on
# when we first saw the job instead of trusting the date alone.
COARSE = {"workday", "amazon", "oracle", "workable", "icims", "list", "linkedin"}


def day_to_time(d, now):
    # A date with no time counts as noon local time that day (never in the future):
    # today's jobs are fresh, the day before yesterday's never are.
    if not d:
        return None
    noon = datetime(d.year, d.month, d.day, 12).astimezone(timezone.utc)
    return min(noon, now)


def amazon(_slug="amazon"):
    now = datetime.now(timezone.utc)
    out = []
    for cat in ["software-development", "machine-learning-science"]:
        for offset in range(0, 300, 100):
            d = get_json("https://www.amazon.jobs/en/search.json?base_query=&sort=recent&country=USA"
                         f"&result_limit=100&offset={offset}&category%5B%5D={cat}")
            for j in d.get("jobs", []):
                try:
                    day = datetime.strptime(j["posted_date"], "%B %d, %Y").date()
                except (KeyError, ValueError):
                    day = None
                desc = "\n".join(strip_html(j.get(k)) for k in ("description", "basic_qualifications", "preferred_qualifications"))
                out.append(job("Amazon", "amazon", j["id_icims"], j["title"], j.get("normalized_location"),
                               "https://www.amazon.jobs" + j["job_path"], day_to_time(day, now), desc,
                               j.get("posted_date", "")))
            if len(d.get("jobs", [])) < 100:
                break
    return out


def smartrecruiters(slug, title_ok=None):
    out, offset = [], 0
    while offset < 500:
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}")
        for p in d.get("content", []):
            loc = p.get("location") or {}
            posted = parse_time(p.get("releasedDate"))
            desc = ""
            if posted and datetime.now(timezone.utc) - posted <= timedelta(days=1) and (title_ok is None or title_ok(p["name"])):
                try:
                    ad = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{p['id']}").get("jobAd", {})
                    desc = "\n".join(strip_html(s.get("text")) for s in (ad.get("sections") or {}).values() if isinstance(s, dict))
                except Exception:
                    pass
            place = ", ".join(x for x in [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()] if x)
            if loc.get("remote"):
                place += " (Remote)"
            out.append(job((p.get("company") or {}).get("name") or slug, "smartrecruiters", p["id"], p["name"],
                           place, f"https://jobs.smartrecruiters.com/{slug}/{p['id']}", posted, desc))
        offset += 100
        if offset >= d.get("totalFound", 0):
            break
    return out


def workable(slug, title_ok=None):
    with WORKABLE_SLOTS:
        return _workable(slug, title_ok)


def _workable(slug, title_ok=None):
    # The public widget feed (what companies embed on their sites) has dates and descriptions
    # in one request; the v3 search API rate-limits for a whole day.
    d = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
    now = datetime.now(timezone.utc)
    out = []
    for p in d.get("jobs", []):
        try:
            day = datetime.strptime(p.get("published_on") or p.get("created_at") or "", "%Y-%m-%d").date()
        except ValueError:
            day = None
        place = ", ".join(x for x in [p.get("city"), p.get("state"), p.get("country")] if x)
        if p.get("telecommuting"):
            place += " (Remote)"
        out.append(job(d.get("name") or slug, "workable", p["shortcode"], p["title"], place,
                       p.get("url") or f"https://apply.workable.com/{slug}/j/{p['shortcode']}/",
                       day_to_time(day, now), strip_html(p.get("description")), p.get("published_on", "")))
    return out


def oracle(slug, title_ok=None):
    host, site = slug.split("|")
    base = f"https://{host}/hcmRestApi/resources/latest"
    now = datetime.now(timezone.utc)
    seen, out = set(), []
    for term in ["software", "machine learning", "developer"]:
        d = get_json(f"{base}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.secondaryLocations"
                     f"&finder=findReqs;siteNumber={site},keyword={urllib.request.quote(term)},sortBy=POSTING_DATES_DESC,limit=50")
        for r in (d.get("items") or [{}])[0].get("requisitionList", []):
            if r["Id"] in seen:
                continue
            seen.add(r["Id"])
            try:
                day = datetime.strptime(r.get("PostedDate", ""), "%Y-%m-%d").date()
            except ValueError:
                day = None
            desc = ""
            if day and day >= (now - timedelta(days=1)).date() and (title_ok is None or title_ok(r["Title"])):
                try:
                    det = get_json(f"{base}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
                                   f"&finder=ById;Id=%22{r['Id']}%22,siteNumber={site}")["items"][0]
                    desc = "\n".join(strip_html(det.get(k)) for k in ("ExternalDescriptionStr", "ExternalQualificationsStr", "ExternalResponsibilitiesStr"))
                except Exception:
                    pass
            locs = [r.get("PrimaryLocation") or ""] + [s.get("Name", "") for s in r.get("secondaryLocations") or []]
            out.append(job(host.split(".")[0], "oracle", r["Id"], r["Title"], " / ".join(l for l in locs if l),
                           f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{r['Id']}",
                           day_to_time(day, now), desc, r.get("PostedDate", "")))
    return out


def get_text(url, timeout=20):
    return get_page(url, timeout)[0]


def get_page(url, timeout=20):
    """Returns (text, final url after redirects)."""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.geturl()


def icims(host, title_ok=None):
    # iCIMS has no feed and usually no dates; links on the search page are the jobs.
    out, seen = [], set()
    for term in ["software", "machine learning", "developer"]:
        page = get_text(f"https://{host}/jobs/search?ss=1&in_iframe=1&searchKeyword={urllib.request.quote(term)}")
        for m in re.finditer(r'href="(https://[^"]+?/jobs/(\d+)/[^"]+?/job)[^"]*"[^>]*>(.*?)</a>', page, re.S):
            url, jid = m.group(1), m.group(2)
            title = re.sub(r"\s+", " ", re.sub(r"(External )?Job (Posting )?Title", "", strip_html(m.group(3)), flags=re.I)).strip()
            if jid in seen or not title or title.lower() in ("apply", "view job"):
                continue
            seen.add(jid)
            out.append(job(host.split(".")[0].replace("careers-", ""), "icims", jid, title, "", url, None, ""))
    # Descriptions only for titles that already look right (one request each).
    for j in out:
        if title_ok is None or title_ok(j["title"]):
            try:
                page = get_text(j["url"] + "?in_iframe=1")
                j["description"] = strip_html(page)[:20000]
                loc = re.search(r"(?:Job Locations?|Location)\s*</?[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,80})", page)
                if loc:
                    j["location"] = loc.group(1).strip()
            except Exception:
                pass
    return out


FETCHERS.update({"amazon": amazon, "smartrecruiters": smartrecruiters, "workable": workable,
                 "oracle": oracle, "icims": icims})
