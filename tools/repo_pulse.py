#!/usr/bin/env python3
# ⬡ repo-pulse — zero-dependency git activity pulse for any repo
# made by Mayank Bhaskar · https://github.com/qtjg
# usage: python3 tools/repo_pulse.py
import collections
import datetime
import subprocess
import sys


def git(*args):
    return subprocess.run(("git",) + args, capture_output=True, text=True)


def main():
    if git("rev-parse", "--git-dir").returncode != 0:
        print("repo-pulse: not inside a git repository")
        return 1
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    dirty = bool(git("status", "--porcelain").stdout.strip())
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=27)).isoformat()

    days = collections.Counter(
        git("log", f"--since={since}", "--pretty=format:%ad", "--date=short").stdout.split())
    files = collections.Counter(
        ln.strip() for ln in git("log", f"--since={since}", "--name-only",
                                 "--pretty=format:").stdout.splitlines() if ln.strip())
    authors = collections.Counter(
        git("log", f"--since={since}", "--pretty=format:%an").stdout.splitlines())

    print(f"⬡ repo-pulse · branch {branch} @ {head}"
          + (" · dirty tree" if dirty else " · clean"))
    total = sum(days.values())
    bar = "".join(
        "█" if days.get((today - datetime.timedelta(days=i)).isoformat()) else "·"
        for i in range(27, -1, -1))
    print(f"  {total:>4} commits / 28d   {bar}")
    if days:
        peak, n = max(days.items(), key=lambda kv: kv[1])
        print(f"  peak day: {peak} ({n} commits)")
    if files:
        print("  hot files:")
        for f, n in files.most_common(5):
            print(f"    {n:>3}x  {f[:72]}")
    if authors:
        top = ", ".join(f"{a} ({n})" for a, n in authors.most_common(3))
        print(f"  contributors: {len(authors)} — {top}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
