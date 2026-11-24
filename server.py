"""Job Radar dashboard: python3 server.py, then open http://localhost:8787

Runs only on this Mac (127.0.0.1), so nobody else on the network can see it.
"""
import json
import sqlite3
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data" / "jobs.db"
LOG = ROOT / "data" / "last_run.txt"
PORT = 8787
run_proc = None


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def jobs():
    con = db()
    last = con.execute("select * from runs order by started desc limit 1").fetchone()
    # Applied and hidden jobs stay visible in their tabs after they stop being fresh.
    rows = con.execute(
        """select key, company, ats, title, location, url, posted_at, first_seen, years, sponsorship,
                  status, match, date_check, length(description) as desc_len
           from jobs
           where (keep=1 and last_seen >= ?) or status in ('applied', 'hidden', 'saved')""",
        (last["started"] if last else "",),
    ).fetchall()
    out = []
    for r in rows:
        j = dict(r)
        j["match"] = json.loads(j["match"]) if j["match"] else None
        out.append(j)
    return {"jobs": out, "last_run": dict(last) if last else None, "running": is_running()}


def is_running():
    return run_proc is not None and run_proc.poll() is None


def start_run():
    global run_proc
    if is_running():
        return False
    log = open(LOG, "w")
    run_proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    return True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, (ROOT / "dashboard.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/jobs":
            return self.send(200, jobs())
        if self.path == "/api/run":
            tail = LOG.read_text(errors="replace").splitlines()[-3:] if LOG.exists() else []
            return self.send(200, {"running": is_running(), "log": tail})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/status":
            if body.get("status") not in ("new", "applied", "hidden", "saved"):
                return self.send(400, {"error": "bad status"})
            con = db()
            con.execute("update jobs set status=? where key=?", (body["status"], body["key"]))
            con.commit()
            return self.send(200, {"ok": True})
        if self.path == "/api/run":
            return self.send(200, {"started": start_run()})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    print(f"Job Radar dashboard: http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
