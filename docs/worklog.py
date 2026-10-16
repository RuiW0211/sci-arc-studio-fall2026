"""Build web/data/worklog.json, the working record on the Methods page (user, 2026-10-16: "在网页method里加入已工作了多长
时间，看看能不能把github里的工作流程记录可视化到我的网站method模块里").

Two parts:
  github  every commit (merges left out) and pull request of this repository and of the archived Blender one
          (RuiW0211/sci-arc-studio-fall2026-blender), from git and the GitHub CLI (gh). The Pages workflow reruns this
          part on every deploy (--github), so the page is never behind GitHub.
  claude  minutes of work with Claude per day, from the local Claude Code session logs of this project (their message
          timestamps only, nothing of what was said). Only the owner's computer has them, so this part is refreshed by
          running the script there; a deploy keeps the minutes already in the file.
          Working time: the messages of all the sessions in one line; two messages less than GAP_MIN minutes apart
          count the time between them (parallel sessions count once), a longer gap is a break.

  python docs/worklog.py            both parts (on the owner's computer)
  python docs/worklog.py --github   the GitHub part only, the Claude minutes kept (the Pages workflow)
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "data" / "worklog.json"
REPO = "RuiW0211/sci-arc-studio-fall2026"
ARCHIVED = "RuiW0211/sci-arc-studio-fall2026-blender"
# the Claude Code project folders whose sessions are this project's work (~/.claude/projects/<folder>/*.jsonl)
CLAUDE_FOLDERS = ["D--OneDrive---Syracuse-University-Rui-Wang-Syracuse-M-Arch-2026FALL-Visiting-Studio",
                  "D--GitHub-sci-arc-studio-fall2026"]
GAP_MIN = 10
TZ = "America/Los_Angeles"     # the days of the record (the page groups commits by the same zone)
SUBJECT_MAX = 140


def run(*cmd):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def gh_json(*args):
    return json.loads(run("gh", *args))


def subject(msg):
    s = (msg or "").strip().splitlines()[0] if (msg or "").strip() else ""
    return s if len(s) <= SUBJECT_MAX else s[: SUBJECT_MAX - 1].rstrip() + "…"


def github_part():
    prs = []
    for repo in (REPO, ARCHIVED):
        for p in gh_json("pr", "list", "-R", repo, "--state", "all", "--limit", "100",
                         "--json", "number,title,createdAt,mergedAt,headRefName,state"):
            shas = [c["sha"] for c in gh_json("api", f"repos/{repo}/pulls/{p['number']}/commits?per_page=100", "--paginate")]
            prs.append({"repo": repo, "n": p["number"], "title": p["title"], "created": p["createdAt"],
                        "merged": p["mergedAt"], "branch": p["headRefName"], "state": p["state"].lower(), "shas": shas})
    pr_of = {(p["repo"], s): p["n"] for p in prs for s in p["shas"]}
    commits = []
    # this repository: the published history of main (no merge commits; a pull request is shown as one)
    ref = "origin/main" if run("git", "branch", "-r", "--list", "origin/main").strip() else "HEAD"
    for line in run("git", "log", ref, "--no-merges", "--format=%H%x1f%aI%x1f%B%x1e").split("\x1e"):
        if not line.strip():
            continue
        sha, t, msg = line.strip("\n").split("\x1f", 2)
        commits.append({"repo": REPO, "sha": sha[:9], "t": t, "s": subject(msg), "pr": pr_of.get((REPO, sha))})
    # the archived repository, from the API
    for c in gh_json("api", f"repos/{ARCHIVED}/commits?per_page=100", "--paginate"):
        if len(c.get("parents") or []) > 1:
            continue
        sha = c["sha"]
        commits.append({"repo": ARCHIVED, "sha": sha[:9], "t": c["commit"]["author"]["date"],
                        "s": subject(c["commit"]["message"]), "pr": pr_of.get((ARCHIVED, sha))})
    commits.sort(key=lambda c: c["t"])
    for p in prs:
        p["commits"] = len(p.pop("shas"))
    prs.sort(key=lambda p: p["created"])
    return {"repos": [{"name": REPO, "archived": False}, {"name": ARCHIVED, "archived": True}],
            "commits": commits, "prs": prs}


def claude_part():
    base = Path.home() / ".claude" / "projects"
    ts = []
    for folder in CLAUDE_FOLDERS:
        for f in (base / folder).glob("*.jsonl"):
            with open(f, encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") in ("user", "assistant") and d.get("timestamp"):
                        ts.append(datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).timestamp())
    ts.sort()
    days = {}
    for a, b in zip(ts, ts[1:]):
        if 0 < b - a <= GAP_MIN * 60:
            day = datetime.fromtimestamp(a, ZoneInfo(TZ)).strftime("%Y-%m-%d")
            days[day] = days.get(day, 0) + (b - a) / 60
    return {"gap_min": GAP_MIN, "sessions_from": datetime.fromtimestamp(ts[0], ZoneInfo(TZ)).strftime("%Y-%m-%d") if ts else None,
            "days": {d: round(m) for d, m in sorted(days.items())},
            "source": "Claude Code session logs of this project on the owner's computer: message timestamps only"}


def main():
    github_only = "--github" in sys.argv[1:]
    old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    out = {"_": "The working record on the Methods page (docs/worklog.py). Commits and pull requests from git and GitHub; "
                "minutes of work with Claude per day from the session logs' timestamps (two messages less than "
                f"{GAP_MIN} min apart count the time between them).",
           "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tz": TZ}
    try:
        out.update(github_part())
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        print(f"GitHub part not refreshed ({e}); the previous one kept", file=sys.stderr)
        out.update({k: old[k] for k in ("repos", "commits", "prs") if k in old})
    out["claude"] = old.get("claude") if github_only else claude_part()
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    c = out.get("claude") or {}
    print(f"{len(out.get('commits', []))} commits, {len(out.get('prs', []))} pull requests, "
          f"{sum((c.get('days') or {}).values()) / 60:.1f} h with Claude -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
