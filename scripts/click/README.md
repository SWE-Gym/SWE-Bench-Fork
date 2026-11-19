# Adding `pallets/click` to SWE-Gym

This coursework follows the SWE-Gym paper (Pan et al., ICML 2025), §3.1
"Dataset Construction". It adds a new repository and its task instances to
SWE-Gym's environment code, which lives in
[`SWE-Gym/SWE-Bench-Fork`](https://github.com/SWE-Gym/SWE-Bench-Fork). The
`SWE-Gym/SWE-Gym` repo only holds the paper, training and verifier code.

## 1. Why click

The paper's repository criteria are:

- created before 1 July 2022
- more than 500 stars, 500 PRs and 100 contributors
- Python
- not already in SWE-Bench or SWE-Gym, to avoid contamination

`pallets/click` meets all of these. It's also pure Python and its test suite
runs fast.

## 2. Pipeline steps and where each one lives

| Paper step (§3.1) | What was done | File |
|---|---|---|
| Identify repositories | Chose `pallets/click` (see above) | none |
| Extract training instances | Built instances from merged PRs. The PR diff is split into `patch` (non-test files) and `test_patch` (test files). The issue title and body become `problem_statement`. Issue comments made before the PR's first commit become `hints_text`. Same logic as `swebench/collect/build_dataset.py::create_instance`. | `scripts/click/build_click_instances.py` |
| Version training instances | Read `__version__` from `src/click/__init__.py` at `base_commit` and keep `major.minor` (`8.1`). | `swebench/versioning/constants.py` (click path and regex) |
| Set up executable environments | Configured by hand from the repo snapshot: `requirements/tests.txt` (the pinned pytest lock used by `tox.ini`), then `pip install -e .` (flit backend), on Python 3.11. Spec key `8.1`. | `swebench/harness/constants.py` (`SPECS_CLICK`, `MAP_REPO_TO_REQS_PATHS`) |
| Test log parsing | Standard pytest `-rA` summary parser | `swebench/harness/log_parsers.py` (`parse_log_click`) |
| Verify instances | `run_validation.py` runs each instance in Docker twice, once with the gold patch and once with an empty patch. FAIL_TO_PASS = tests that pass only with gold. PASS_TO_PASS = tests that pass in both. An instance is kept only if F2P is non-empty and there is no PASS_TO_FAIL. | `swebench/harness/run_validation.py`, `scripts/click/make_f2p_p2p.py` |

## 3. Instances

| instance_id | Issue | Bug |
|---|---|---|
| `pallets__click-2724` | #2500 | `show_default=True` shows nothing when the default is `""` |
| `pallets__click-2730` | #2632 | A boolean flag's help shows the wrong default when the value comes from `default_map` |

Click links issues through `:issue:` roles in `CHANGES.rst` rather than "fixes #N"
in the PR body, so the issue numbers are passed with `--issue PR:ISSUE`.

Files:

- `data/click/click_instances.jsonl`: raw instances, before validation
- `data/click/click_instances.validated.jsonl`: final SWE-Gym instances with F2P/P2P

## 4. Reproduce

The harness needs Linux because it uses the `resource` module. On Windows it is
run inside a container that drives the host Docker daemon:

```bash
docker build -t swegym-harness:local -f scripts/click/harness.Dockerfile scripts/click

# 1. build instances
python scripts/click/build_click_instances.py --prs 2724 2730 \
  --issue 2724:2500 --issue 2730:2632 --out data/click/click_instances.jsonl

# 2. execution-based validation (gold vs empty patch)
docker run --rm --add-host raw.githubusercontent.com:185.199.108.133 \
  -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD:/work" -w /work \
  swegym-harness:local python -m swebench.harness.run_validation \
  --dataset_name data/click/click_instances.jsonl --run_id click-validate \
  --cache_level instance --max_workers 2 --timeout 900

# 3. derive FAIL_TO_PASS / PASS_TO_PASS and keep verified instances
python scripts/click/make_f2p_p2p.py data/click/click_instances.jsonl click-validate \
  data/click/click_instances.validated.jsonl

# 4. final check: gold patch must be "resolved" under the standard evaluator
docker run ... python -m swebench.harness.run_evaluation \
  --dataset_name data/click/click_instances.validated.jsonl \
  --predictions_path gold --run_id click-gold-eval --max_workers 2
```

`--add-host` is a local network workaround and does not change the harness. On
this machine, containers could not complete TLS to one GitHub raw-content server
(185.199.110.133), so another GitHub server is pinned.

## 5. Results

_Filled in after the validation run, see below._

## 6. How trajectories fit in (paper §4–5)

SWE-Gym instances are environments, not training data in themselves.
Trajectories come from running an agent inside these Docker images:

- **Agent training (rejection-sampling fine-tuning).** An OpenHands agent was
  driven by GPT-4o / Claude 3.5 Sonnet. Each run's final diff was graded by
  FAIL_TO_PASS and PASS_TO_PASS. Only successful runs were kept: 491
  trajectories, about 19 turns each. Qwen2.5-Coder was fine-tuned on them.
- **Verifier training.** Successful and failed trajectories, mixing off-policy
  runs (from the teacher models) and on-policy runs (from the fine-tuned model),
  were balanced 1:1. A model was then trained to output `<YES>`/`<NO>`. At
  inference it reranks k sampled trajectories (Best@k).

The new click instances plug into the same loop: they use the same harness, the
same grading and the same image naming (`sweb.eval.x86_64.<instance_id>`).
