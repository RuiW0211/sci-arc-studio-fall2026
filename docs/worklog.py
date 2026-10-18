"""Build web/data/worklog.json, the working record on the Methods page (user, 2026-10-16: "在网页method里加入已工作了多长
时间 ... 把github里的工作流程记录可视化到我的网站method模块里"; "要注明是谁的工作时间 ... 我希望每个人都记录工作时间").

The rule (docs/WORKFLOW.md): everyone's working time is counted from their first Claude Code session about this
project, day by day, and each day shows what came of it (pull requests opened and merged). Each person adds their own
time from their own computer, where their session logs are, by running this script before they open a pull request.

Two parts:
  people  per person: minutes of work with Claude per day, from the timestamps of their Claude Code session logs of
          this project (~/.claude/projects/<folder>/*.jsonl, and the logs of the subagents those sessions start,
          <folder>/<session>/subagents/*.jsonl; nothing of what was said is read). All their sessions on one line: two
          messages less than GAP_MIN minutes apart count the time between them (sessions and subagents open at the same
          time count once), a longer gap is a break. A run updates only the person running it; the others are kept.
  github  every commit (merges left out) and pull request of this repository and of the archived Blender one, with
          who made it, from git and the GitHub CLI (gh). The Pages workflow reruns this part on every deploy.

  python docs/worklog.py               your own time (you = the GitHub user gh is logged in as) and the GitHub part
  python docs/worklog.py --me <login>  the same, for <login>
  python docs/worklog.py --github      the GitHub part only, everyone's time kept (the Pages workflow)
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "worklog.json"
REPO = "RuiW0211/sci-arc-studio-fall2026"
ARCHIVED = "RuiW0211/sci-arc-studio-fall2026-blender"
GAP_MIN = 10
TZ = "America/Los_Angeles"     # the days of the record (the page groups commits and pull requests by the same zone)
SUBJECT_MAX = 140
# The people of the project, by GitHub login: the name shown, and which Claude Code project folders hold their
# sessions about this project. Every folder whose name contains PROJECT_KEY (a session started in a clone of this
# repository) counts for everyone; add a person's other folders here (e.g. where they worked before cloning).
PROJECT_KEY = "sci-arc-studio-fall2026"
PEOPLE = {
    "RuiW0211": {"name": "Rui Wang",
                 # the studio folder, where the work began on 2026-09-17 (research, then the site model)
                 "folders": ["D--OneDrive---Syracuse-University-Rui-Wang-Syracuse-M-Arch-2026FALL-Visiting-Studio"]},
    "clarkamenudo": {"name": "Clark Amenudo", "folders": []},   # the population layer (Blender repository)
}


def run(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def gh_json(*args):
    return json.loads(run("gh", *args))


def subject(msg):
    s = (msg or "").strip().splitlines()[0] if (msg or "").strip() else ""
    return s if len(s) <= SUBJECT_MAX else s[: SUBJECT_MAX - 1].rstrip() + "…"


def login_of(name, email):
    """A commit's author as a GitHub login: from the GitHub noreply address, else the person whose name it is."""
    m = re.match(r"(?:\d+\+)?([^@]+)@users\.noreply\.github\.com$", email or "")
    if m:
        return m.group(1)
    return next((k for k, p in PEOPLE.items() if p["name"] == name), name)


def github_part():
    prs = []
    for repo in (REPO, ARCHIVED):
        for p in gh_json("pr", "list", "-R", repo, "--state", "all", "--limit", "100",
                         "--json", "number,title,createdAt,mergedAt,headRefName,state,author"):
            shas = [c["sha"] for c in gh_json("api", f"repos/{repo}/pulls/{p['number']}/commits?per_page=100", "--paginate")]
            prs.append({"repo": repo, "n": p["number"], "title": p["title"], "by": (p.get("author") or {}).get("login"),
                        "created": p["createdAt"], "merged": p["mergedAt"], "branch": p["headRefName"],
                        "state": p["state"].lower(), "shas": shas})
    pr_of = {(p["repo"], s): p["n"] for p in prs for s in p["shas"]}
    commits = []
    # this repository: the published history of main (no merge commits; a pull request is shown by its merge)
    ref = "origin/main" if run("git", "branch", "-r", "--list", "origin/main").strip() else "HEAD"
    for line in run("git", "log", ref, "--no-merges", "--format=%H%x1f%aI%x1f%an%x1f%ae%x1f%B%x1e").split("\x1e"):
        if not line.strip():
            continue
        sha, t, name, email, msg = line.strip("\n").split("\x1f", 4)
        commits.append({"repo": REPO, "sha": sha[:9], "t": t, "by": login_of(name, email), "s": subject(msg),
                        "pr": pr_of.get((REPO, sha))})
    # the archived repository, from the API
    for c in gh_json("api", f"repos/{ARCHIVED}/commits?per_page=100", "--paginate"):
        if len(c.get("parents") or []) > 1:
            continue
        a = c["commit"]["author"]
        commits.append({"repo": ARCHIVED, "sha": c["sha"][:9], "t": a["date"],
                        "by": (c.get("author") or {}).get("login") or login_of(a["name"], a["email"]),
                        "s": subject(c["commit"]["message"]), "pr": pr_of.get((ARCHIVED, c["sha"]))})
    commits.sort(key=lambda c: c["t"])
    for p in prs:
        p["commits"] = len(p.pop("shas"))
    prs.sort(key=lambda p: p["created"])
    return {"repos": [{"name": REPO, "archived": False}, {"name": ARCHIVED, "archived": True}],
            "commits": commits, "prs": prs}


def my_time(login):
    """This computer's Claude Code sessions about the project: minutes per day for login."""
    base = Path.home() / ".claude" / "projects"
    want = set(PEOPLE.get(login, {}).get("folders", []))
    folders = [d for d in base.iterdir() if d.is_dir() and (PROJECT_KEY in d.name or d.name in want)] if base.exists() else []
    ts = []
    for folder in folders:
        # subagents count too (user, 2026-10-18: "子任务的时间也算进去"): while a background agent works, the session
        # itself is quiet, and without its log that time read as a break
        for f in [*folder.glob("*.jsonl"), *folder.glob("*/subagents/*.jsonl")]:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") in ("user", "assistant") and d.get("timestamp"):
                        ts.append(datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp())
    if not ts:
        return None
    ts.sort()
    days = {}
    for a, b in zip(ts, ts[1:]):
        if 0 < b - a <= GAP_MIN * 60:
            day = datetime.fromtimestamp(a, ZoneInfo(TZ)).strftime("%Y-%m-%d")
            days[day] = days.get(day, 0) + (b - a) / 60
    return {"login": login, "name": PEOPLE.get(login, {}).get("name", login),
            "since": datetime.fromtimestamp(ts[0], ZoneInfo(TZ)).strftime("%Y-%m-%d"),
            "days": {d: round(m) for d, m in sorted(days.items())},
            "sessions": len({f.name for folder in folders for f in folder.glob("*.jsonl")}),
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main():
    a = sys.argv[1:]
    github_only = "--github" in a
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out = {"_": "The working record on the Methods page (docs/worklog.py; the rule: docs/WORKFLOW.md). Per person, minutes of "
                "work with Claude per day from the timestamps of their Claude Code sessions about this project, counted from "
                f"their first one (two messages less than {GAP_MIN} min apart count the time between them); commits and pull "
                "requests from git and GitHub.",
           "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tz": TZ, "gap_min": GAP_MIN}
    try:
        out.update(github_part())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(f"GitHub part not refreshed ({e}); the previous one kept", file=sys.stderr)
        out.update({k: old[k] for k in ("repos", "commits", "prs") if k in old})
    people = {p["login"]: p for p in old.get("people", [])}
    if not github_only:
        me = a[a.index("--me") + 1] if "--me" in a else run("gh", "api", "user", "-q", ".login").strip()
        mine = my_time(me)
        if mine:
            people[me] = mine
        else:
            print(f"no Claude Code sessions of this project found for {me} on this computer", file=sys.stderr)
    out["people"] = sorted(people.values(), key=lambda p: p["since"])
    out["names"] = {k: v["name"] for k, v in PEOPLE.items()}   # for the people with no recorded time yet
    # nothing new (only the time of the run differs): the file is left as it is, so a daily run makes no empty commit
    same = lambda d: {k: v for k, v in d.items() if k != "generated"} | {
        "people": [{k: v for k, v in q.items() if k != "updated"} for q in d.get("people", [])]}
    if old and same(old) == same(out):
        print("nothing new; web/data/worklog.json unchanged")
        return
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(out.get('commits', []))} commits, {len(out.get('prs', []))} pull requests; "
          + "; ".join(f"{p['name']} {sum(p['days'].values()) / 60:.1f} h since {p['since']}" for p in out["people"])
          + f" -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
