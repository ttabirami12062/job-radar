"""Check a job's real posting date at its source, the way you'd check Ashby's publishedAt
or Greenhouse's first_published by hand. Lists and LinkedIn show when *they* found or
reposted a job, which can be months after the company posted it.

real_date(job) -> (datetime or None, how)   None means it couldn't be verified.
"""
import re
import threading
import urllib.request
from datetime import datetime, timezone

from radar.sources import UA, day_to_time, get_json, get_text, parse_time

_ashby_cache, _lock = {}, threading.Lock()


def resolve(url):
    # Short links (go.vansh.nyc) redirect to the company's real job page.
    if "go.vansh.nyc" not in url:
        return url
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.geturl()


def _day(s):
    try:
        return day_to_time(datetime.strptime(s[:10], "%Y-%m-%d").date(), datetime.now(timezone.utc))
    except (TypeError, ValueError):
        return None


def ats_date(url):
    m = re.search(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/([\w-]+)/jobs/(\d+)", url)
    if m:
        j = get_json(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}")
        return parse_time(j.get("first_published")), "greenhouse first_published"
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        slug = m[1]
        with _lock:
            board = _ashby_cache.get(slug)
        if board is None:
            board = {j["id"]: j for j in get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}").get("jobs", [])}
            with _lock:
                _ashby_cache[slug] = board
        j = board.get(m[2])
        return (parse_time(j.get("publishedAt")), "ashby publishedAt") if j else (None, "no longer on the Ashby board")
    m = re.search(r"jobs\.lever\.co/([^/?#]+)/([0-9a-f-]{36})", url)
    if m:
        j = get_json(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}")
        return datetime.fromtimestamp(j["createdAt"] / 1000, tz=timezone.utc), "lever createdAt"
    m = re.search(r"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)(/job/[^?#]+)", url)
    if m:
        info = get_json(f"https://{m[1]}.{m[2]}.myworkdayjobs.com/wday/cxs/{m[1]}/{m[3]}{m[4]}").get("jobPostingInfo", {})
        return _day(info.get("startDate")), "workday startDate"
    m = re.search(r"jobs\.smartrecruiters\.com/([\w-]+)/(\d+)", url)
    if m:
        j = get_json(f"https://api.smartrecruiters.com/v1/companies/{m[1]}/postings/{m[2]}")
        return parse_time(j.get("releasedDate")), "smartrecruiters releasedDate"
    return None, "company site we can't read dates from"


def linkedin_apply_url(job_id):
    page = get_text(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    m = re.search(r'id="applyUrl"[^>]*>\s*<!--"([^"]+)"', page)
    if not m:
        return None
    m2 = re.search(r"[?&]url=([^&]+)", m[1])
    return urllib.request.unquote(m2[1]) if m2 else None


def real_date(job):
    try:
        if "jobright.ai" in job["url"]:
            return None, "Jobright link (no company page to check)"
        if job["ats"] == "linkedin":
            target = linkedin_apply_url(job["key"].split(":")[-1])
            if not target:
                return None, "LinkedIn Easy Apply (no company page to check)"
            return ats_date(target)
        return ats_date(resolve(job["url"]))
    except Exception as e:
        return None, f"couldn't check ({str(e)[:60]})"
