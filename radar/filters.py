"""Decide whether a job is worth Abi's time. Each check returns a reason when it says no,
so a run can show exactly why jobs were dropped and the rules can be tuned."""
import re
from datetime import datetime, timedelta, timezone


MAX_AGE_HOURS = 24
MAX_YEARS = 2  # SDE 1 / early career: drop anything that asks for 3+ years

# ── TITLE ──
TITLE_WANT = re.compile(
    r"software|\bswe\b|\bsde\b|developer|(back|front|full)[- ]?(end|stack)\s*(software\s*)?(engineer|developer|dev\b)|"
    r"machine learning|\bml\b|\bai\b|\bllm|deep learning|applied scientist|"
    r"forward[- ]deployed|product engineer|web engineer|mobile engineer|ios engineer|android engineer",
    re.I,
)
TITLE_SKIP = re.compile(
    r"senior|\bsr\.?\b|staff|principal|\blead\b|manager|director|head of|architect|\bvp\b|"
    r"president|intern\b|internship|co-?op|apprentice|\b(ii|iii|iv|v)\b|\b[2-5]\b|\bl[4-9]\b|\be[4-9]\b|"
    r"business develop|sales|solutions? (engineer|consultant)|support engineer|recruit|"
    r"hardware|firmware|embedded|asic|fpga|rtl|silicon|verification|mechanical|electrical|"
    r"\brf\b|analog|manufacturing|technician|clearance|instructor|teacher|tutor|"
    r"contract|freelance|part[- ]time|marketing|designer|writer|counsel|attorney|"
    r"supervisor|leader|postdoc|post-doc|ph\.?d|fellow\b|trainer|analyst|laborer|operator|"
    r"industrial|process engineer|environmental|chemical|civil|test engineer|summer|student|"
    r"\b(s|l|p)?mts\b|member of technical staff|researcher|research scientist|professor|"
    r"neuro|clinical|nurse|financial|accountant|technical writer|\bhubspot|salesforce developer|"
    r"coordinator|key holder|cashier|retail|\bstore\b|\bts\b|mid[- ]?level|expert|devops|"
    r"tester|\bqa\b|quality assurance|\bemb\b|\bcno\b|power platform|consultant|customer success",
    re.I,
)


def check_title(title):
    if TITLE_SKIP.search(title):
        return f"title: {TITLE_SKIP.search(title).group(0).strip()}"
    if not TITLE_WANT.search(title):
        return "title: not a target role"
    return None


# ── LOCATION (US only) ──
US_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
US_WORDS = re.compile(
    r"united states|\busa\b|\bu\.s\.|\bus\b|\bamerica|new york|nyc|san francisco|bay area|seattle|"
    r"boston|austin|chicago|los angeles|denver|atlanta|dallas|houston|miami|san jose|palo alto|"
    r"mountain view|sunnyvale|menlo park|redmond|bellevue|cambridge, ma|washington|philadelphia|"
    r"pittsburgh|portland|salt lake|phoenix|san diego|raleigh|durham|nashville|minneapolis|detroit|"
    r"columbus|charlotte|irvine|santa clara|oakland|brooklyn|boulder|jersey city|hoboken|"
    r"california|texas|florida|illinois|massachusetts|colorado|georgia|virginia|oregon|arizona|"
    r"north carolina|ohio|michigan|minnesota|utah|tennessee|pennsylvania|new jersey|maryland",
    re.I,
)
NON_US = re.compile(
    r"canada|toronto|vancouver|montreal|ontario|united kingdom|\buk\b|london|england|scotland|"
    r"ireland|dublin|india|bangalore|bengaluru|hyderabad|pune|chennai|mumbai|delhi|gurgaon|noida|"
    r"germany|berlin|munich|france|paris|netherlands|amsterdam|spain|madrid|barcelona|portugal|"
    r"lisbon|poland|warsaw|krakow|israel|tel aviv|singapore|japan|tokyo|australia|sydney|melbourne|"
    r"brazil|s[aã]o paulo|mexico|argentina|buenos aires|colombia|bogot|chile|peru|costa rica|"
    r"philippines|manila|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|korea|seoul|"
    r"vietnam|malaysia|indonesia|thailand|emea|apac|latam|europe|romania|ukraine|sweden|stockholm|"
    r"switzerland|zurich|denmark|copenhagen|italy|milan|czech|prague|belgium|austria|vienna|norway|"
    r"finland|hungary|serbia|greece|turkey|istanbul|uae|dubai|egypt|nigeria|kenya|south africa|"
    r"new zealand|estonia|lithuania|latvia|bulgaria|croatia|pakistan|bangladesh|sri lanka",
    re.I,
)
STATE_ABBR = re.compile(r"(?:,|\b-)\s*(" + "|".join(US_STATES) + r")\b")


def is_us(location):
    loc = location or ""
    if not loc.strip():
        return True  # unknown: keep rather than lose a real job
    if US_WORDS.search(loc):
        return True
    if NON_US.search(loc):
        return False
    if STATE_ABBR.search(loc):
        return True
    return bool(re.search(r"remote|anywhere|hybrid", loc, re.I))


# ── YEARS OF EXPERIENCE ──
YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to|or more)\s*\d{0,2}\s*\+?\s*)?years?(?:'|’)?\b[^.\n]{0,80}?\b"
    r"(experience|exp\b|industry|professional|working|software|engineering|development)",
    re.I,
)


def years_required(text):
    found = [int(m.group(1)) for m in YEARS.finditer(text or "") if 0 < int(m.group(1)) <= 15]
    # The smallest number is usually the real minimum; bigger ones are "preferred" or company history.
    return min(found) if found else None


# ── SPONSORSHIP ──
NO_SPONSOR = re.compile(
    r"(not|unable to|cannot|can ?not|won'?t|will not|do not|does not|don'?t|no longer)\s+(be\s+)?(able\s+to\s+)?"
    r"(offer\s+|provide\s+|support\s+)?(visa\s+|immigration\s+|employment\s+|h-?1b\s+)?sponsor|"
    r"no\s+(visa\s+|immigration\s+)?sponsorship|sponsorship\s+(is\s+)?not\s+(available|offered|provided)|"
    r"without\s+(the\s+need\s+for\s+|requiring\s+|needing\s+)?(current\s+or\s+future\s+|future\s+)?(visa\s+)?sponsorship|"
    r"u\.?s\.? citizen(ship)?\s+(is\s+)?(required|only)|must\s+be\s+(a\s+)?u\.?s\.?\s+citizen|"
    r"security clearance|secret clearance|ts/sci|\bitar\b|green card holders? only|"
    r"(citizens?|permanent residents?) only",
    re.I,
)
YES_SPONSOR = re.compile(
    r"(visa|h-?1b|immigration) sponsorship (is\s+)?(available|offered|provided)|"
    r"(will|can|able to|happy to|we) sponsor|sponsorship (is\s+)?available|open to sponsor",
    re.I,
)


def sponsorship(text):
    if NO_SPONSOR.search(text or ""):
        return "no"
    if YES_SPONSOR.search(text or ""):
        return "yes"
    return "unknown"


# ── STAFFING / FAKE POSTERS ──
BLOCKED_COMPANIES = re.compile(
    r"beacon ?fire|synergistic ?it|revature|smart ?it ?frame|fdm group|skill ?storm|genspark|"
    r"collabera|infosys|cognizant|tata consultancy|\btcs\b|wipro|\bhcl\b|tech ?mahindra|capgemini|"
    r"mindtree|ltimindtree|mphasis|accenture federal|jobot|\bdice\b|cybercoders|robert half|"
    r"teksystems|insight global|randstad|kforce|apex systems|staffing|recruiting|talent solutions|"
    r"consultancy|consulting services|it services|infotech|software solutions|tech solutions llc|\btalent",
    re.I,
)
STAFFING_TEXT = re.compile(
    r"\bc2c\b|corp[- ]to[- ]corp|\bw2 only\b|on behalf of (our|a) client|our client is|"
    r"third[- ]party (vendor|recruit)|training and placement|marketing your (profile|resume)",
    re.I,
)


# Defense and government contractors almost always need US citizenship or a clearance,
# even when the short list entry doesn't say so.
CITIZEN_ONLY_COMPANIES = re.compile(
    r"lockheed|northrop|raytheon|\brtx\b|l3harris|general dynamics|\bgdms\b|bae systems|leidos|\bsaic\b|"
    r"booz allen|\bcaci\b|peraton|parsons|\bsmx\b|anduril|spacex|naval nuclear|mantech|\bmitre\b|"
    r"sandia|los alamos|lawrence livermore|huntington ingalls|keylogic|american systems|b/core|"
    r"wyetech|woodsong|altron|ita international|bluestaq|noblis|\bgdit\b|textron|sierra nevada|"
    r"shield ai|palantir usg|jacobs|amentum|\bkbr\b|\bv2x\b|chenega|\bicf\b|aerovironment|\bav\b",
    re.I,
)


def check_fake(company, text):
    if BLOCKED_COMPANIES.search(company):
        return "staffing/consultancy company"
    if STAFFING_TEXT.search(text or ""):
        return "staffing language in description"
    return None


# ── ALL TOGETHER ──
def evaluate(j, now=None):
    """Returns (keep, reason). Fills j['years'] and j['sponsorship'] for the dashboard."""
    now = now or datetime.now(timezone.utc)
    text = f"{j['title']}\n{j['description']}"
    j["years"] = years_required(j["description"])
    j["sponsorship"] = sponsorship(text)

    # Only when there's no date at all (iCIMS) or Workday's vague "Posted Yesterday" do we
    # fall back to when we first saw the job, and never on a board's very first check.
    # A clear old date always wins.
    fresh = timedelta(hours=MAX_AGE_HOURS)
    age = now - datetime.fromisoformat(j["posted_at"]) if j.get("posted_at") else None
    posted_ok = age is not None and age <= fresh
    vague = age is None or (j["ats"] == "workday" and age <= timedelta(hours=48))
    seen_ok = vague and not j.get("baseline") and now - datetime.fromisoformat(j["first_seen"]) <= fresh
    if not (posted_ok or seen_ok):
        return False, "older than 24h" if j.get("posted_at") else "no date (first check)"

    reason = (
        check_title(j["title"])
        or (None if is_us(j["location"]) else "not in the US")
        or check_fake(j["company"], text)
        or ("defense company (usually US citizens only)" if CITIZEN_ONLY_COMPANIES.search(j["company"]) else None)
        or ("says no sponsorship" if j["sponsorship"] == "no" else None)
        or (f"needs {j['years']}+ years" if j["years"] and j["years"] > MAX_YEARS else None)
    )
    return (reason is None), reason
