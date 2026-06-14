"""Walk-forward param tuning for 2026 OOS months — year-by-year training.

Per fold:
  1. Define training segments = full calendar years 2020..2025 + one extra
     one-month chunk per 2026 month before the OOS test month.
  2. For each combo, run a separate backtest on each segment in parallel.
     Per-combo training score = sum of $ P&L across all its segments.
  3. Pick the combo with the highest training score.
  4. Re-run that combo on the OOS test month, record P&L.

All per-(combo, segment) results are appended to a JSONL file as soon as they
complete, so an interrupted run can still be analyzed and resumed from where
it stopped.

Grid: 3 × 3 × 3 = 27 combos (score-entry × qqq-regime × stop-pct).
"""
import csv
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = "/Users/victorhuang/work/alpha_tech_tracker"
BACKTEST_SCRIPT = "alpha_tech_tracker/op_momentum_strategy/op_momentum_selector_backtest.py"
OUT_DIR = Path(PROJECT_ROOT) / "alpha_tech_tracker/op_momentum_strategy/backtest_params_tunning/walkforward_2026"
MAX_WORKERS = 22

TRAIN_FULL_YEARS = [
    ("2020-01-01", "2020-12-31"),
    ("2021-01-01", "2021-12-31"),
    ("2022-01-01", "2022-12-31"),
    ("2023-01-01", "2023-12-31"),
    ("2024-01-01", "2024-12-31"),
    ("2025-01-01", "2025-12-31"),
]

# (extra_2026_train_months_before_oos, oos_start, oos_end, label)
FOLDS = [
    ([], "2026-01-01", "2026-01-31", "2026-01"),
    ([("2026-01-01", "2026-01-31")], "2026-02-01", "2026-02-28", "2026-02"),
    ([("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")], "2026-03-01", "2026-03-31", "2026-03"),
    ([("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31")], "2026-04-01", "2026-04-30", "2026-04"),
    ([("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31"), ("2026-04-01", "2026-04-30")], "2026-05-01", "2026-05-29", "2026-05"),
]

SCORE_ENTRY = [0.55, 0.60, 0.65]
QQQ_REGIME = [0.45, 0.55, 0.65]
STOP_PCT = [0.30, 0.40, 0.50]


@dataclass(frozen=True)
class Params:
    score_entry: float
    qqq_regime: float
    stop_pct: float

    def cli_flags(self) -> list:
        return [
            "--score-entry-weight", f"{self.score_entry:.2f}",
            "--qqq-regime-weight", f"{self.qqq_regime:.2f}",
            "--stop-pct", f"{self.stop_pct:.2f}",
        ]

    def key(self) -> str:
        return f"e{self.score_entry:.2f}_r{self.qqq_regime:.2f}_s{self.stop_pct:.2f}"

    def as_dict(self) -> dict:
        return {
            "score_entry_weight": self.score_entry,
            "qqq_regime_weight": self.qqq_regime,
            "stop_pct": self.stop_pct,
        }


def all_param_combos() -> List[Params]:
    return [Params(*c) for c in product(SCORE_ENTRY, QQQ_REGIME, STOP_PCT)]


def fixed_flags() -> list:
    return [
        "--top", "1",
        "--window", "M1", "09:30", "3",
        "--window", "A1", "10:00", "5",
        "--window", "A2", "12:15", "10",
        "--window", "A3", "14:15", "5",
        "--min-hold-bars", "1",
        "--ma-momentum-gate",
        "--feed", "sip",
        "--qqq-or-weight", "0.40",
        "--normalize-or-by-adr",
        "--reversal", "--bearish-reentry", "--bullish-reentry",
        "--score-avg-win-weight", "0.00",
        "--score-win-rate-weight", "0.10",
        "--score-ev-trend-weight", "0.10",
        "--ev-trend-days", "15",
        "--score-rel-strength-weight", "0.15",
        "--min-pool-vote", "4",
        "--qqq-regime-full-only",
        "--qqq-regime-bearish-only",
        "--qqq-regime-ma200",
        "--qqq-regime-recovery-floor", "0.25",
        "--qqq-regime-bearish-ev-only",
        "--qqq-regime-no-bullish",
        "--qqq-regime-bear-entry-weight", "0.30",
    ]


_TOTAL_RE = re.compile(r"TOTAL\s+\d+\s+\d+W/\d+L\s+([+-]?\$[\d,]+\.\d+)")


def _parse_total_pnl(stdout: str) -> Optional[float]:
    m = _TOTAL_RE.search(stdout)
    if not m:
        return None
    return float(m.group(1).replace("$", "").replace(",", ""))


def _run_backtest(params: Params, start: str, end: str) -> Optional[float]:
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT}
    cmd = [sys.executable, BACKTEST_SCRIPT, *fixed_flags(), *params.cli_flags(),
           "--start", start, "--end", end]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=PROJECT_ROOT)
    return _parse_total_pnl(result.stdout)


def _run_unit(args):
    params, start, end = args
    pnl = _run_backtest(params, start, end)
    return params, start, end, pnl


def _append_jsonl(path: Path, row: dict) -> None:
    with path.open("a") as f:
        f.write(json.dumps(row) + "\n")


def _load_jsonl(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def run_fold(fold_idx: int, extra_2026_months: List[Tuple[str, str]],
             test_start: str, test_end: str, label: str):
    print(f"\n{'=' * 80}\nFOLD {fold_idx}: train = 2020-2025 yearly + {len(extra_2026_months)} extra 2026 month(s)  |  OOS = {label}\n{'=' * 80}", flush=True)

    train_segments = TRAIN_FULL_YEARS + extra_2026_months
    combos = all_param_combos()
    units = [(p, s, e) for p in combos for (s, e) in train_segments]
    print(f"  {len(combos)} combos × {len(train_segments)} segments = {len(units)} unit-runs", flush=True)

    jsonl_path = OUT_DIR / f"fold_{fold_idx:02d}_{label}_units.jsonl"
    if jsonl_path.exists():
        jsonl_path.unlink()

    done = 0
    with ProcessPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(_run_unit, u): u for u in units}
        for fut in as_completed(futs):
            done += 1
            p, s, e, pnl = fut.result()
            _append_jsonl(jsonl_path, {
                "params": p.as_dict(),
                "param_key": p.key(),
                "start": s,
                "end": e,
                "pnl": pnl,
            })
            if done % 25 == 0 or done == len(units):
                print(f"    [{done:3d}/{len(units)}]", flush=True)

    rows = _load_jsonl(jsonl_path)
    by_key: dict = {}
    for r in rows:
        if r["pnl"] is None:
            continue
        by_key.setdefault(r["param_key"], {"params": r["params"], "segments": 0, "total_pnl": 0.0})
        by_key[r["param_key"]]["segments"] += 1
        by_key[r["param_key"]]["total_pnl"] += r["pnl"]

    expected_segments = len(train_segments)
    complete = [v for v in by_key.values() if v["segments"] == expected_segments]
    complete.sort(key=lambda v: v["total_pnl"], reverse=True)

    if not complete:
        print(f"  NO COMPLETE COMBOS — aborting fold.", flush=True)
        return None

    best = complete[0]
    print(f"  BEST TRAIN: ${best['total_pnl']:+,.2f}  params={best['params']}", flush=True)

    best_params = Params(
        score_entry=best["params"]["score_entry_weight"],
        qqq_regime=best["params"]["qqq_regime_weight"],
        stop_pct=best["params"]["stop_pct"],
    )
    print(f"  Running OOS on {label}...", flush=True)
    oos_pnl = _run_backtest(best_params, test_start, test_end)
    oos_str = f"${oos_pnl:+,.2f}" if oos_pnl is not None else "ERR"
    print(f"  OOS {label} P&L: {oos_str}", flush=True)

    summary = {
        "fold": fold_idx,
        "train_segments": train_segments,
        "test_start": test_start,
        "test_end": test_end,
        "test_label": label,
        "best_params": best["params"],
        "best_train_pnl": best["total_pnl"],
        "oos_test_pnl": oos_pnl,
        "top10_train": [{"params": v["params"], "train_pnl": v["total_pnl"]} for v in complete[:10]],
    }
    out_file = OUT_DIR / f"fold_{fold_idx:02d}_{label}.json"
    out_file.write_text(json.dumps(summary, indent=2))
    print(f"  Wrote {out_file}", flush=True)
    return summary


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries = []
    for i, (extra, test_start, test_end, label) in enumerate(FOLDS, 1):
        s = run_fold(i, extra, test_start, test_end, label)
        if s is not None:
            all_summaries.append(s)

    csv_path = OUT_DIR / "summary.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "fold", "test_month",
            "score_entry_weight", "qqq_regime_weight", "stop_pct",
            "best_train_pnl_usd", "oos_test_pnl_usd",
        ])
        for s in all_summaries:
            bp = s["best_params"]
            w.writerow([
                s["fold"], s["test_label"],
                bp["score_entry_weight"], bp["qqq_regime_weight"], bp["stop_pct"],
                s["best_train_pnl"], s["oos_test_pnl"],
            ])
    print(f"\nWrote {csv_path}", flush=True)

    print("\n" + "=" * 80)
    print("WALK-FORWARD OOS P&L BY MONTH (degradation chart)")
    print("=" * 80)
    print(f"  {'Month':<10} {'Best params':<35} {'OOS P&L':>14}")
    for s in all_summaries:
        bp = s["best_params"]
        pk = f"e{bp['score_entry_weight']:.2f}/r{bp['qqq_regime_weight']:.2f}/s{bp['stop_pct']:.2f}"
        oos = s["oos_test_pnl"]
        ps = f"${oos:+,.2f}" if oos is not None else "ERR"
        print(f"  {s['test_label']:<10} {pk:<35} {ps:>14}")
    print("=" * 80)


if __name__ == "__main__":
    main()
