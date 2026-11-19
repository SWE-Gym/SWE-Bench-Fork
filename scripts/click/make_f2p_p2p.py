"""Derive FAIL_TO_PASS / PASS_TO_PASS from a run_validation.py run and keep only
verified instances (SWE-Gym paper §3.1: "ensure that the gold patch ... passes
more unit tests than the original code").

run_validation.py runs every instance twice with the test_patch applied:
  - "gold":  with the human-written fix
  - "empty": with no fix (original code)
and writes logs/run_evaluation/<run_id>/<gold|empty>/<instance_id>/report.json.

  FAIL_TO_PASS = tests that pass with gold and do not pass with empty
  PASS_TO_PASS = tests that pass in both
An instance is kept only if FAIL_TO_PASS is non-empty and gold has no failures
among the tests that passed before (i.e. no PASS_TO_FAIL).

Usage:
    python scripts/click/make_f2p_p2p.py data/click/click_instances.jsonl click-validate \
        data/click/click_instances.validated.jsonl
"""
import json
import sys
from pathlib import Path

LOG_ROOT = Path("logs/run_evaluation")


def load_status(run_id: str, model: str, iid: str):
    p = LOG_ROOT / run_id / model / iid / "report.json"
    if not p.exists():
        return None
    rep = json.loads(p.read_text())[iid]
    if not rep.get("patch_successfully_applied"):
        return None
    st = rep.get("tests_status", {})
    return set(st.get("PASS", [])), set(st.get("FAIL", []))


def main(inp: str, run_id: str, out: str) -> None:
    kept = []
    for line in Path(inp).read_text(encoding="utf-8").splitlines():
        inst = json.loads(line)
        iid = inst["instance_id"]
        gold, empty = load_status(run_id, "gold", iid), load_status(run_id, "empty", iid)
        if gold is None or empty is None:
            print(f"[drop] {iid}: missing/failed gold or empty run")
            continue
        g_pass, g_fail = gold
        e_pass, _ = empty
        f2p = sorted(g_pass - e_pass)
        p2p = sorted(g_pass & e_pass)
        p2f = sorted(e_pass & g_fail)
        print(f"{iid}: F2P={len(f2p)} P2P={len(p2p)} P2F={len(p2f)} gold_fail={len(g_fail)}")
        if not f2p or p2f:
            print(f"[drop] {iid}: gold patch does not strictly improve tests")
            continue
        inst["FAIL_TO_PASS"] = json.dumps(f2p)
        inst["PASS_TO_PASS"] = json.dumps(p2p)
        kept.append(inst)
    Path(out).write_text("".join(json.dumps(i) + "\n" for i in kept), encoding="utf-8")
    print(f"kept {len(kept)} verified instance(s) -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
