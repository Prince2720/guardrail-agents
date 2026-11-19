"""The final experiment: the same attacks against several firewall configurations, in one command.

    python -m redteam.experiment                      # baseline, full, and each layer on its own
    python -m redteam.experiment --leave-one-out      # also: full minus one layer at a time
    python -m redteam.experiment --configs baseline,full
    python -m redteam.experiment --results-dir DIR --force

Design
  * Same model, same prompts, LLM cache ON: an identical prompt gets the identical model reply in every
    configuration (paired replay), so differences between configurations come from the firewall, not from sampling noise.
  * Configurations that already have a result file are skipped (use --force to redo). If a provider limit stops the run,
    re-run the same command and it resumes where it stopped.
  * Each configuration runs two suites: 'main' (54 attacks, 20 benign) and 'heldout' (written after the firewall was frozen).
"""
import argparse, os, sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).parent
LAYERS = ["ingress", "context", "tools", "egress"]

CONFIGS = {
    "baseline": {"FIREWALL_ENABLED": "false"},
    "full": {"FIREWALL_ENABLED": "true", "FIREWALL_LAYERS": "all"},
    **{f"only_{l}": {"FIREWALL_ENABLED": "true", "FIREWALL_LAYERS": l} for l in LAYERS},
}
LOO = {f"without_{l}": {"FIREWALL_ENABLED": "true", "FIREWALL_LAYERS": ",".join(x for x in LAYERS if x != l)} for l in LAYERS}
SUITES = {"main": ("attacks.jsonl", "benign.jsonl"), "heldout": ("heldout_attacks.jsonl", "heldout_benign.jsonl")}


@contextmanager
def env(**kv):
    saved = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: str(v) for k, v in kv.items()})
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


def label(cfg, suite):
    return f"exp_{cfg}_{suite}"


def main(argv=None):
    from redteam.run import run_suite, RunStopped
    ap = argparse.ArgumentParser()
    ap.add_argument("--configs", default=None, help="comma list; default: baseline,full,only_* (+ without_* with --leave-one-out)")
    ap.add_argument("--leave-one-out", action="store_true")
    ap.add_argument("--results-dir", default=str(HERE / "results"))
    ap.add_argument("--force", action="store_true", help="re-run configurations that already have results")
    ap.add_argument("--no-report", action="store_true")
    a = ap.parse_args(argv)

    allc = {**CONFIGS, **(LOO if a.leave_one_out or (a.configs and "without_" in a.configs) else {})}
    names = a.configs.split(",") if a.configs else list(allc)
    unknown = [n for n in names if n not in allc]
    if unknown:
        sys.exit(f"unknown configuration(s): {unknown}. choose from {list(allc)}")
    results = Path(a.results_dir); results.mkdir(parents=True, exist_ok=True)

    print(f"Model: {os.getenv('LLM_PROVIDER', 'mock')} {os.getenv('LLM_MODEL', '')} | cache: ON | results: {results}")
    for cfg in names:
        for suite, (atk, ben) in SUITES.items():
            lab = label(cfg, suite)
            if (results / f"{lab}.json").exists() and not a.force:
                print(f"skip  {lab} (already done)")
                continue
            if a.force:
                (results / f"{lab}.json").unlink(missing_ok=True)
            with env(**allc[cfg]):
                try:
                    s = run_suite(lab, atk, ben, results_dir=results, cache=True,
                                  audit_db=results / f"audit_{lab}.db", quiet=True)
                except RunStopped as e:
                    print("\n" + str(e))
                    print("\nRe-run the same command to resume; finished configurations are skipped.")
                    sys.exit(1)
            print(f"done  {lab:<28} ASR {s['attack_success_rate']:>5}%  unauth {s['unauthorized_tool_exec_rate']:>5}%  "
                  f"FP {s['false_positive_rate']:>4}%  tokens {s['llm_tokens']:>7}  mean {s['latency_ms_mean']:>8} ms")
    if not a.no_report and all((results / f"{label(c, 'main')}.json").exists() for c in ("baseline", "full")):
        from redteam import report
        report.build(results)
    return 0


if __name__ == "__main__":
    main()
