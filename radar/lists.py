"""Public daily new-grad lists (Simplify, Jobright, SpeedyApply, Vansh) and LinkedIn's public search.

They catch jobs on custom career sites we can't read directly, and they're also where
new company boards get discovered for the seed list.
"""
import re
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from radar.sources import day_to_time, get_text, job, strip_html

LISTS = {
    "simplify": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
    "simplify-intern": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
    "jobright-swe": "https://raw.githubusercontent.com/jobright-ai/2026-Software-Engineer-New-Grad/master/README.md",
    "speedyapply-swe": "https://raw.githubusercontent.com/speedyapply/2026-SWE-College-Jobs/main/NEW_GRAD_USA.md",
    "speedyapply-ai": "https://raw.githubusercontent.com/speedyapply/2026-AI-College-Jobs/main/NEW_GRAD_USA.md",
    "vansh": "https://raw.githubusercontent.com/vanshb03/New-Grad-2026/dev/README.md",
}
# Internship lists are only read for company discovery, never shown as jobs.
DISCOVERY_ONLY = {"simplify-intern"}


def download_lists():
    out = {}
    for name, url in LISTS.items():
        try:
            out[name] = get_text(url, timeout=40)
        except Exception as e:
            print(f"  could not read list {name}: {e}")
    return out


# ── SEED DISCOVERY ──
SEED_PATTERNS = [
    ("gh", r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b|v1\b)([A-Za-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([A-Za-z0-9_.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)"),
    ("wd", r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?(?!job\b|wday\b)([A-Za-z0-9_-]+)"),
    ("icims", r"\b((?:[a-z0-9-]+)\.icims\.com)"),
    ("sr", r"(?:jobs|careers)\.smartrecruiters\.com/(?!oneclick)([A-Za-z0-9_-]+)"),
    ("workable", r"apply\.workable\.com/(?!j\b|api\b)([a-z0-9_-]+)"),
    ("oracle", r"([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z_]+/sites/([A-Za-z0-9_]+)"),
]


def discover_seeds(texts):
    found = set()
    for text in texts:
        for ats, pat in SEED_PATTERNS:
            for m in re.finditer(pat, text):
                g = m.groups()
                found.add(f"{ats} {'|'.join(g)}")
    return found


# ── LIST ROWS AS JOBS ──
def _rows(text):
    for tr in re.findall(r"<tr>(.*?)</tr>", text, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(cells) >= 4:
            yield cells
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith("| Company") and not re.match(r"\|\s*-", line):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) >= 4:
                yield cells


def _age(cell, now):
    t = strip_html(cell).strip()
    m = re.fullmatch(r"(\d+)d", t)
    if m:
        return day_to_time((now.astimezone() - timedelta(days=int(m.group(1)))).date(), now), t
    try:
        d = datetime.strptime(f"{t} {now.astimezone().year}", "%b %d %Y").date()
        return day_to_time(d, now), t
    except ValueError:
        return None, t


def list_jobs(texts):
    now = datetime.now(timezone.utc)
    out = []
    for name, text in texts.items():
        if name in DISCOVERY_ONLY:
            continue
        company = ""
        for cells in _rows(text):
            row = " ".join(cells)
            if "🔒" in row:  # closed
                continue
            c = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", strip_html(cells[0])).replace("*", "").strip()
            company = company if c in ("↳", "") else c
            hrefs = [h for cell in cells[1:] for h in re.findall(r'href="([^"]+)"|\]\((https?://[^)\s]+)\)', cell)]
            urls = [a or b for a, b in hrefs if "imgur" not in (a or b) and "simplify.jobs/c/" not in (a or b)]
            if not urls:
                continue
            title = strip_html(cells[1])
            if "](" in title:  # markdown link, sometimes with brackets inside: [[2027] Title](url)
                title = title[title.index("[") + 1: title.rindex("](")]
            title = title.replace("*", "").strip()
            location = strip_html(re.sub(r"</?br/?>", " / ", cells[2]))
            posted, label = _age(cells[-1], now)
            url = urls[0].split("?utm")[0]
            out.append(job(company, "list", f"{name}:{url}", title, location, url, posted, "", f"{label} ({name})"))
    return out


# ── LINKEDIN (public guest search, no login) ──
LINKEDIN_SEARCHES = ["software engineer", "new grad software engineer", "machine learning engineer", "full stack engineer"]
_li_lock = threading.Lock()


def _li_get(url):
    # One request at a time with a pause, so LinkedIn doesn't block the computer's connection.
    with _li_lock:
        time.sleep(3)
        return get_text(url)


def linkedin(title_ok=None, pages=2):
    now = datetime.now(timezone.utc)
    out, seen, blocked = [], set(), False
    for q in LINKEDIN_SEARCHES:
        for start in range(0, pages * 25, 25):
            if blocked:
                break
            try:
                html_ = _li_get("https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
                                f"keywords={urllib.request.quote(q)}&location=United%20States&f_TPR=r86400&f_E=2&start={start}")
            except Exception as e:
                print(f"  linkedin stopped early: {e}")
                blocked = True
                break
            cards = html_.split("<li>")[1:]
            for c in cards:
                jid = re.search(r"jobs/view/[^\"?]*?-?(\d{6,})", c)
                if not jid or jid.group(1) in seen:
                    continue
                seen.add(jid.group(1))
                pick = lambda cls: strip_html((re.search(r'class="' + cls + r'[^"]*"[^>]*>(.*?)</', c, re.S) or [None, ""])[1])
                ago = pick("job-search-card__listdate")
                m = re.search(r"(\d+)\s+(minute|hour|day|week)", ago)
                posted = now - timedelta(**{m.group(2) + "s": int(m.group(1))}) if m else None
                out.append(job(pick("base-search-card__subtitle"), "linkedin", jid.group(1), pick("base-search-card__title"),
                               pick("job-search-card__location"), f"https://www.linkedin.com/jobs/view/{jid.group(1)}",
                               posted, "", ago))
            if len(cards) < 10:
                break
    for j in out:
        if not blocked and (title_ok is None or title_ok(j["title"])):
            try:
                page = _li_get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{j['key'].split(':')[-1]}")
                m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', page, re.S)
                j["description"] = strip_html(m.group(1)) if m else ""
            except Exception:
                blocked = True
    return out


def lists_source(texts, title_ok=None):
    # Jobright pages sit behind a bot check, so we never open them; their jobs get a real
    # date only by matching the same job on a company board we read directly.
    return list_jobs(texts)
