"""Free, instant resume match: which skills a job asks for, which resume covers them best,
and what's truly missing (versus just missing from that one resume).

Each skill has one name and every spelling it shows up as, so "Postgres" in a job and
"PostgreSQL" on a resume count as the same thing.
"""
import re

from radar.resumes import load

# name: pattern (case-insensitive unless the pattern starts with (?-i:...))
SKILLS = {
    # languages
    "Python": r"\bpython\b", "Java": r"\bjava\b(?!\s*script)", "JavaScript": r"\bjavascript\b|\bjs\b|\bes6\b",
    "TypeScript": r"\btypescript\b|\bts\b(?=\s*[,/)])", "Go": r"\bgolang\b|(?-i:\bGo\b)(?=\s*[,/)]|\s+(?:and|or)\b)",
    "C++": r"c\+\+|\bcpp\b", "C#": r"c#|\.net\b|\bdotnet\b", "C": r"(?-i:\bC\b)(?![+#])(?=\s*[,/)]|\s+(?:and|or)\b)",
    "Rust": r"\brust\b", "Kotlin": r"\bkotlin\b", "Swift": r"\bswift\b(?!ui)", "Scala": r"\bscala\b",
    "Ruby": r"\bruby\b", "PHP": r"\bphp\b", "SQL": r"\bsql\b", "Bash": r"\bbash\b|shell script",
    # frontend
    "React": r"\breact(\.js|js)?\b(?!\s*native)", "React Native": r"react native", "Next.js": r"\bnext\.?js\b",
    "Vue": r"\bvue(\.js)?\b", "Angular": r"\bangular\b", "Svelte": r"\bsvelte\b", "HTML/CSS": r"\bhtml5?\b|\bcss3?\b",
    "Tailwind": r"\btailwind\b", "Redux": r"\bredux\b",
    # backend
    "Node.js": r"\bnode(\.js|js)?\b", "Express": r"\bexpress(\.js)?\b", "FastAPI": r"\bfastapi\b",
    "Flask": r"\bflask\b", "Django": r"\bdjango\b", "Spring Boot": r"\bspring( boot)?\b", "Rails": r"\brails\b",
    "REST APIs": r"(?-i:\bREST(ful)?\b)|restful", "GraphQL": r"\bgraphql\b", "gRPC": r"\bgrpc\b",
    "Microservices": r"micro-?services", "OAuth": r"\boauth", "WebSockets": r"websockets?",
    # data
    "PostgreSQL": r"\bpostgres(ql)?\b", "MySQL": r"\bmysql\b", "MongoDB": r"\bmongo(db)?\b",
    "Redis": r"\bredis\b", "DynamoDB": r"\bdynamo(db)?\b", "Elasticsearch": r"elastic ?search|opensearch",
    "Kafka": r"\bkafka\b", "RabbitMQ": r"rabbitmq", "Spark": r"\b(py)?spark\b", "Airflow": r"\bairflow\b",
    "Snowflake": r"\bsnowflake\b", "BigQuery": r"bigquery", "Supabase": r"\bsupabase\b",
    "Vector databases": r"pinecone|weaviate|chroma(db)?|faiss|pgvector|vector (db|database|store)",
    # cloud & infra
    "AWS": r"\baws\b|amazon web services|\bec2\b|\bs3\b|\blambda\b", "GCP": r"\bgcp\b|google cloud",
    "Azure": r"\bazure\b", "Docker": r"\bdocker\b|container", "Kubernetes": r"kubernetes|\bk8s\b|\beks\b|\bgke\b",
    "Terraform": r"terraform|infrastructure as code|\biac\b", "CI/CD": r"ci\s*/\s*cd|continuous (integration|deployment|delivery)|github actions|jenkins|gitlab ci",
    "Linux": r"\blinux\b|\bunix\b", "Git": r"\bgit\b|github|gitlab", "Monitoring": r"monitoring|observability|cloudwatch|datadog|prometheus|grafana",
    # AI / ML
    "PyTorch": r"pytorch|\btorch\b", "TensorFlow": r"tensorflow|keras", "scikit-learn": r"scikit|sklearn",
    "Pandas/NumPy": r"\bpandas\b|\bnumpy\b", "LLMs": r"\bllms?\b|large language model|\bgpt|generative ai|genai",
    "RAG": r"\brag\b|retrieval[- ]augmented", "LangChain": r"langchain|llamaindex|langgraph",
    "OpenAI API": r"openai", "Hugging Face": r"hugging ?face|transformers library",
    "Prompt engineering": r"prompt engineering|prompting", "AI agents": r"\bagents?\b|agentic|tool[- ]use|\bmcp\b",
    "LLM evaluation": r"\bevals?\b|evaluation (framework|pipeline|harness)|llm[- ]as[- ]a[- ]judge",
    "Fine-tuning": r"fine-?tun", "Computer vision": r"computer vision|\bopencv\b|\byolo|object detection|image (classification|segmentation)",
    "NLP": r"\bnlp\b|natural language processing", "Deep learning": r"deep learning|neural network",
    "Machine learning": r"machine learning|\bml\b", "MLOps": r"mlops|model (deployment|serving)|mlflow|kubeflow|sagemaker|vertex ai",
    # testing & practice
    "Unit testing": r"unit test|pytest|junit|jest\b|mocha|mockito|\btdd\b|test[- ]driven",
    "E2E testing": r"cypress|selenium|playwright|end[- ]to[- ]end test", "Load testing": r"\bk6\b|load test|jmeter|locust",
    "Distributed systems": r"distributed systems?", "System design": r"system design", "Data structures & algorithms": r"data structures|algorithms|\bdsa\b",
    "Agile": r"\bagile\b|\bscrum\b",
}
COMPILED = {k: re.compile(v, re.I) for k, v in SKILLS.items()}

# Each resume is tailored to one kind of role, so the job title picks the resume.
# Order matters: the first match wins ("AI Full Stack Engineer" is an AI role).
ROLE_HINTS = {
    "ai": r"\bai\b|\bllm|agent|applied ai|forward[- ]deployed|genai",
    "ml": r"machine learning|\bml\b|data scien|applied scien|computer vision|deep learning",
    "frontend": r"front[- ]?end|\bui\b|web developer|react",
    "fullstack": r"full[- ]?stack",
    "backend": r"back[- ]?end|\bapi\b|platform|infrastructure|distributed",
    "software-testing": r"\btest|\bqa\b|quality|sdet|automation",
    "linux": r"linux|systems? engineer|devops|site reliability|\bsre\b|cloud engineer|infrastructure engineer",
}
# Generic "Software Engineer" titles: pick from these by what the job description stresses.
GENERAL = ["backend", "fullstack", "frontend", "ai", "ml"]


def skills_in(text):
    return {k for k, rx in COMPILED.items() if rx.search(text or "")}


# "Java, C++, or C#" / "such as" / "at least one of": having any one of these is enough.
EITHER = re.compile(r"\bsuch as\b|\bone (or more )?of\b|\be\.g\.|\bor similar\b|\bor equivalent\b|\blike\b|\bincluding\b|\bany\b|\bor\b", re.I)


def either_or_covered(text, have):
    """Skills that only appear in pick-one lists where Abi already has another option."""
    covered, needed_alone = set(), set()
    for sentence in re.split(r"(?<=[.;:!?])\s+|\n+", text or ""):
        found = skills_in(sentence)
        if not found:
            continue
        if len(found) >= 2 and EITHER.search(sentence) and found & have:
            covered |= found - have
        else:
            needed_alone |= found
    return covered - needed_alone


_resumes = None


def resume_skills():
    global _resumes
    if _resumes is None:
        _resumes = {name: skills_in(text) for name, text in load().items()}
    return _resumes


def match(job):
    """Fills job['match'] with the best resume, a 0-100 score, and matched / missing skills."""
    wanted = skills_in(f"{job['title']}\n{job.get('description', '')}")
    if len(wanted) < 3:
        job["match"] = {"score": None, "best": None, "note": "not enough detail in the job post to score"}
        return job["match"]
    resumes = resume_skills()
    anywhere = set().union(*resumes.values())

    by_title = [r for r, rx in ROLE_HINTS.items() if r in resumes and re.search(rx, job["title"], re.I)]
    if by_title:
        best = by_title[0]
    else:
        options = [r for r in GENERAL if r in resumes] or list(resumes)
        best = max(options, key=lambda r: len(wanted & resumes[r]))
    text = f"{job['title']}\n{job.get('description', '')}"
    wanted -= either_or_covered(text, resumes[best])
    have = wanted & resumes[best]
    job["match"] = {
        "score": round(100 * len(have) / len(wanted)),
        "best": best,
        "matched": sorted(have),
        # On another resume of yours: worth swapping in. Not on any: a real gap.
        "on_other_resume": sorted((wanted - have) & anywhere),
        "missing": sorted(wanted - anywhere),
    }
    return job["match"]
