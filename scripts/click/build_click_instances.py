"""Build SWE-Gym task instances for pallets/click.

Mirrors the SWE-Bench-Fork collection pipeline used for SWE-Gym (paper §3.1):
  1. create_instance  (swebench/collect/build_dataset.py)
       - base_commit = PR base sha
       - PR diff split into `patch` (non-test files) and `test_patch`
         (paths containing test/tests/e2e/testing), see collect/utils.extract_patches
       - problem_statement = "<issue title>\n<issue body>\n" for each resolved issue
       - hints_text = issue comments made before the PR's first commit
  2. versioning       (swebench/versioning/get_versions.py, github retrieval)
       - read __version__ from the version file at base_commit, keep major.minor
  3. environment_setup_commit = base commit of the newest instance in each version
     group (same convention as SWE-bench), so instances of a version share one env image.

FAIL_TO_PASS / PASS_TO_PASS are filled in later from the execution-based
validation run (run_validation.py -> scripts/click/make_f2p_p2p.py).

Uses unauthenticated public GitHub endpoints (a handful of calls, well under the
60/h limit). Set GITHUB_TOKEN to raise the limit.

Usage:
    python scripts/click/build_click_instances.py --prs 2724 2730 --out data/click/click_instances.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = "pallets/click"
API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
VERSION_PATHS = ["src/click/__init__.py", "click/__init__.py"]
VERSION_PATTERN = r'__version__ = [\'"](.*)[\'"]'
TEST_WORDS = ["test", "tests", "e2e", "testing"]
# same regex SWE-bench uses to find "fixes #123" style references
ISSUE_REF = re.compile(
    r"(?:close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#(\d+)", re.I
)


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": "swebench-collect"})
    tok = os.environ.get("GITHUB_TOKEN")
    if tok and url.startswith(API):
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def get_json(path: str):
    return json.loads(_get(f"{API}{path}"))


def split_diff(diff: str) -> tuple[str, str]:
    """Equivalent of collect/utils.extract_patches without unidiff."""
    patch_fix, patch_test = "", ""
    for block in re.split(r"(?=^diff --git )", diff, flags=re.M):
        if not block.startswith("diff --git"):
            continue
        path = re.match(r"diff --git a/(\S+) b/", block).group(1)
        if any(w in path for w in TEST_WORDS):
            patch_test += block
        else:
            patch_fix += block
    return patch_fix, patch_test


def resolved_issues(pull: dict) -> list[int]:
    text = (pull.get("title") or "") + "\n" + (pull.get("body") or "")
    return sorted({int(n) for n in ISSUE_REF.findall(text)})


def hints_for(pull_number: int, issue_number: int) -> list[str]:
    commits = get_json(f"/repos/{REPO}/pulls/{pull_number}/commits?per_page=100")
    if not commits:
        return []
    first = time.mktime(time.strptime(commits[0]["commit"]["author"]["date"], "%Y-%m-%dT%H:%M:%SZ"))
    out = []
    for c in get_json(f"/repos/{REPO}/issues/{issue_number}/comments?per_page=100"):
        if time.mktime(time.strptime(c["updated_at"], "%Y-%m-%dT%H:%M:%SZ")) < first:
            out.append(c["body"])
        else:
            break
    return out


def version_at(commit: str) -> str | None:
    for p in VERSION_PATHS:
        try:
            text = _get(f"{RAW}/{REPO}/{commit}/{p}").decode()
        except Exception:
            continue
        m = re.search(VERSION_PATTERN, text)
        if m:
            return ".".join(m.group(1).strip().split(".")[:2])
    return None


def create_instance(pr: int, issues_override: list[int] | None) -> dict:
    pull = get_json(f"/repos/{REPO}/pulls/{pr}")
    diff = _get(f"https://github.com/{REPO}/pull/{pr}.diff").decode()
    patch, test_patch = split_diff(diff)
    issues = issues_override or resolved_issues(pull)
    if not issues:
        raise SystemExit(f"PR {pr}: no linked issue found; pass --issue {pr}:<n>")
    problem, hints = "", []
    for n in issues:
        issue = get_json(f"/repos/{REPO}/issues/{n}")
        problem += f"{issue.get('title') or ''}\n{issue.get('body') or ''}\n"
        hints.append("\n".join(hints_for(pr, n)))
    base = pull["base"]["sha"]
    return {
        "repo": REPO,
        "pull_number": pr,
        "instance_id": f"{REPO}-{pr}".replace("/", "__"),
        "issue_numbers": [str(n) for n in issues],
        "base_commit": base,
        "patch": patch,
        "test_patch": test_patch,
        "problem_statement": problem,
        "hints_text": "\n".join(hints),
        "created_at": pull["created_at"],
        "version": version_at(base),
        # filled after validation
        "FAIL_TO_PASS": "[]",
        "PASS_TO_PASS": "[]",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prs", type=int, nargs="+", required=True)
    ap.add_argument("--issue", action="append", default=[], help="override linked issue: PR:ISSUE")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    overrides = defaultdict(list)
    for s in a.issue:
        pr, n = s.split(":")
        overrides[int(pr)].append(int(n))

    insts = [create_instance(pr, overrides.get(pr)) for pr in a.prs]
    insts = [i for i in insts if i["version"] and i["patch"] and i["test_patch"] and i["problem_statement"]]

    # environment_setup_commit: newest base commit per version group
    by_ver = defaultdict(list)
    for i in insts:
        by_ver[i["version"]].append(i)
    for group in by_ver.values():
        newest = max(group, key=lambda i: i["created_at"])["base_commit"]
        for i in group:
            i["environment_setup_commit"] = newest

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(i) + "\n" for i in insts), encoding="utf-8")
    for i in insts:
        print(i["instance_id"], "version", i["version"], "issues", i["issue_numbers"], "base", i["base_commit"][:10])


if __name__ == "__main__":
    main()
