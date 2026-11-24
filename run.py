"""Collect fresh jobs from every company board, filter them, and save the keepers.

    python3 run.py            # full run
    python3 run.py --limit 50 # quick test on 50 companies
"""
import argparse
import re
import json
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from radar import filters, lists
from radar.sources import COARSE, FETCHERS

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DB = DATA / "jobs.db"
SEEDS = DATA / "seed_slugs.txt"
ATS_NAMES = {"gh": "greenhouse", "lever": "lever", "ashby": "ashby", "wd": "workday", "icims": "icims",
             "sr": "smartrecruiters", "workable": "workable", "oracle": "oracle"}
# When the same job shows up in several places, keep the copy with the best data.
SOURCE_RANK = {"greenhouse": 0, "lever": 0, "ashby": 0, "smartrecruiters": 0, "workday": 1, "oracle": 1,
               "amazon": 1, "workable": 1, "icims": 1, "list": 2, "linkedin": 3}


def load_companies():
    out = []
    for line in SEEDS.read_text().splitlines():
        if line.strip():
            ats, slug = line.split(maxsplit=1)
            out.append((ATS_NAMES[ats], slug.strip()))
    return out


def open_db():
    db = sqlite3.connect(DB)
    db.execute("""create table if not exists jobs (
        key text primary key, company text, ats text, title text, location text, url text,
        posted_at text, first_seen text, last_seen text, years int, sponsorship text,
        keep int, reason text, status text default 'new', description text)""")
    db.execute("create table if not exists boards (ats text, slug text, ok int, jobs int, error text, checked text, first_ok text, primary key (ats, slug))")
    return db


def title_ok(t):
    return filters.check_title(t) is None


def fetch(ats, slug, list_texts):
    if ats == "list":
        return lists.lists_source(list_texts, title_ok)
    if ats == "linkedin":
        return lists.linkedin(title_ok)
    if ats in ("greenhouse", "lever", "ashby", "amazon"):
        return FETCHERS[ats](slug)
    return FETCHERS[ats](slug, title_ok=title_ok)


def same_job(j):
    norm = lambda s: re.sub(r"\b(inc|llc|corp|corporation|company|co|technologies|the|usa|us)\b|[^a-z0-9]", "",
                            re.sub(r"\([^)]*\)", "", (s or "").lower()))
    return norm(j["company"]), norm(j["title"])


def refresh_seeds(list_texts):
    known = set(l.strip() for l in SEEDS.read_text().splitlines() if l.strip())
    new = lists.discover_seeds(list_texts.values()) - known
    if new:
        SEEDS.write_text("\n".join(sorted(known | new)) + "\n")
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, help="only check this many companies (for testing)")
    ap.add_argument("--no-linkedin", action="store_true", help="skip LinkedIn this run")
    args = ap.parse_args()

    print("Reading daily new-grad lists...")
    list_texts = lists.download_lists()
    print(f"  {refresh_seeds(list_texts)} new company boards discovered")
    companies = load_companies()[: args.limit] if args.limit else load_companies()
    companies += [("amazon", "amazon"), ("list", "all")] + ([] if args.no_linkedin else [("linkedin", "all")])
    db = open_db()
    now = datetime.now(timezone.utc)
    now_s = now.isoformat()
    start = time.time()
    reasons, kept, total, failed = Counter(), [], 0, 0
    seen_keys = set()

    print(f"Checking {len(companies)} company job boards...")
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = {pool.submit(fetch, ats, slug, list_texts): (ats, slug) for ats, slug in companies}
        for n, fut in enumerate(as_completed(futures), 1):
            ats, slug = futures[fut]
            try:
                jobs = fut.result()
                prev = db.execute("select first_ok from boards where ats=? and slug=?", (ats, slug)).fetchone()
                first_ok = (prev and prev[0]) or now_s
                db.execute("insert or replace into boards values (?,?,?,?,?,?,?)", (ats, slug, 1, len(jobs), None, now_s, first_ok))
            except Exception as e:
                failed += 1
                prev = db.execute("select first_ok from boards where ats=? and slug=?", (ats, slug)).fetchone()
                db.execute("insert or replace into boards values (?,?,?,?,?,?,?)", (ats, slug, 0, 0, str(e)[:200], now_s, prev and prev[0]))
                continue
            for j in jobs:
                if j["key"] in seen_keys:
                    continue
                seen_keys.add(j["key"])
                total += 1
                row = db.execute("select first_seen, status from jobs where key=?", (j["key"],)).fetchone()
                j["first_seen"] = row[0] if row else now_s
                j["baseline"] = j["first_seen"] <= first_ok
                status = row[1] if row else "new"
                keep, reason = filters.evaluate(j, now)
                reasons[reason or "KEPT"] += 1
                db.execute(
                    """insert into jobs values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                       on conflict(key) do update set title=excluded.title, location=excluded.location,
                       posted_at=excluded.posted_at, last_seen=excluded.last_seen, years=excluded.years,
                       sponsorship=excluded.sponsorship, keep=excluded.keep, reason=excluded.reason,
                       description=excluded.description""",
                    (j["key"], j["company"], j["ats"], j["title"], j["location"], j["url"], j["posted_at"],
                     j["first_seen"], now_s, j["years"], j["sponsorship"], int(keep), reason, status,
                     j["description"] if keep else ""),
                )
                if keep:
                    kept.append(j)
            if n % 50 == 0:
                print(f"  {n}/{len(companies)} boards, {len(kept)} matches so far")
                db.commit()
    db.commit()

    best = {}
    for j in kept:
        k = same_job(j)
        if k not in best or SOURCE_RANK[j["ats"]] < SOURCE_RANK[best[k]["ats"]]:
            best[k] = j
    dupes = len(kept) - len(best)
    kept = sorted(best.values(), key=lambda j: j["posted_at"] or j["first_seen"], reverse=True)
    (DATA / "fresh_jobs.json").write_text(json.dumps(
        [{k: v for k, v in j.items() if k not in ("description", "baseline")} for j in kept], indent=2))

    print(f"\nDone in {time.time() - start:.0f}s. {total} jobs read from {len(companies) - failed} boards ({failed} boards failed).")
    print("\nWhy jobs were dropped:")
    for r, c in reasons.most_common():
        print(f"  {c:>6}  {r}")
    print(f"\n{len(kept)} fresh jobs for you ({dupes} duplicates across sources merged):\n")
    print("  by source:", dict(Counter(j["ats"] for j in kept)))
    for j in kept:
        if j["ats"] in COARSE:
            print(f"  {j['posted_label'][:9]:>9} | {j['company'][:22]:22} | {j['title'][:55]:55} | {j['location'][:28]:28} | yrs {(str(j['years'])+'y') if j['years'] else '-':3} | sponsor {j['sponsorship']}")
            print(f"            {j['url']}")
            continue
        age = (now - datetime.fromisoformat(j["posted_at"] or j["first_seen"])).total_seconds() / 3600
        yrs = f"{j['years']}y" if j["years"] else "-"
        print(f"  {age:5.0f}h ago | {j['company'][:22]:22} | {j['title'][:55]:55} | {j['location'][:28]:28} | yrs {yrs:3} | sponsor {j['sponsorship']}")
        print(f"            {j['url']}")


if __name__ == "__main__":
    sys.exit(main())
