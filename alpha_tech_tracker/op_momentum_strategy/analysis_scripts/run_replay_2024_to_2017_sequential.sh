#!/usr/bin/env bash
# run_replay_2024_to_2017_sequential.sh
# Runs years 2024 → 2017 one at a time with:
#   fixed-signal-alloc | reversal+reentry | doubledown | compact summary
#
# Usage:
#   ./run_replay_2024_to_2017_sequential.sh
#   ./run_replay_2024_to_2017_sequential.sh --force

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FORCE_FLAG=""

while [ $# -gt 0 ]; do
  case "$1" in
    --force) FORCE_FLAG="--force"; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

source ~/.pyenv/versions/alpha_tech_tracker/bin/activate

YEARS=(2024 2023 2022 2021 2020 2019 2018 2017)

for YEAR in "${YEARS[@]}"; do
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  Starting $YEAR"
  echo "════════════════════════════════════════════════════════════"
  "$SCRIPT_DIR/run_replay_m1_winrate_regimehold_cap80k.sh" \
    --year "$YEAR" \
    --fixed-signal-alloc \
    --reversal \
    --doubledown \
    --compact-summary \
    $FORCE_FLAG
  echo ""
done

echo "════════════════════════════════════════════════════════════"
echo "  All years complete (2024 → 2017)"
echo "════════════════════════════════════════════════════════════"
