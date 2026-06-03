# Signal Selection: Top-N Count Comparison (2016–2026)

**Generated:** 2026-06-02  
**Screener:** v2 (bug-fixed)  
**Signal caps compared:** Top-3, Top-5, Top-8, All signals  
**SHORT months:** bottom-N selection (weakest WR tickers)  
**Script:** `/tmp/topN_comparison.py`

---

## Yearly Totals

| Year | Top-3 | Top-5 | Top-8 | All | T5-T3 | T8-T3 | All-T3 |
|------|-------|-------|-------|-----|-------|-------|--------|
| 2016 | +81.2% | +83.9% | +83.6% | +83.6% | +2.7pp | +2.4pp | +2.4pp |
| 2017 | +34.1% | +38.7% | +32.7% | +32.7% | +4.5pp | -1.5pp | -1.5pp |
| 2018 | +93.3% | +111.2% | +120.6% | +120.6% | +17.8pp | +27.3pp | +27.3pp |
| 2019 | +26.2% | +50.5% | +52.2% | +52.2% | +24.2pp | +26.0pp | +26.0pp |
| 2020 | +80.6% | +90.6% | +79.8% | +79.8% | +10.0pp | -0.8pp | -0.8pp |
| 2021 | -15.7% | +8.0% | +17.1% | +15.8% | +23.8pp | +32.8pp | +31.5pp |
| 2022 | +187.5% | +219.3% | +266.2% | +276.6% | +31.8pp | +78.7pp | +89.1pp |
| 2023 | +38.8% | +70.6% | +79.1% | +78.2% | +31.8pp | +40.3pp | +39.4pp |
| 2024 | +98.3% | +111.7% | +116.8% | +116.8% | +13.4pp | +18.5pp | +18.5pp |
| 2025 | +127.3% | +121.9% | +172.9% | +186.5% | -5.4pp | +45.6pp | +59.2pp |
| 2026 | +67.2% | +63.7% | +56.0% | +67.7% | -3.5pp | -11.2pp | +0.5pp |
| **Total** | **+818.7%** | **+970.0%** | **+1,077.0%** | **+1,110.4%** | **+151pp** | **+258pp** | **+292pp** |

---

## Key Findings

### Wider caps increase cumulative P&L substantially

Moving from Top-3 to All adds +292pp cumulative (+818.7% → +1,110.4%). The gains are not uniform — they cluster in years/months with extreme signal quality:

- **2022** (+89pp): bear year with many qualifying short signals all pointing down; every additional signal added genuine directional exposure
- **2025-Apr** alone: Top-3 +62.1% → All +157.1% (+95pp in a single month)
- **2021** (+31.5pp): Top-3 was negative (-15.7%); wider caps recovered the year

### Top-8 ≈ All in most months

The average daily signal count is 2.1–3.4 across all years. On most days, taking 8 signals captures essentially all fired signals. The difference between Top-8 and All appears mainly in a handful of high-vol days with 9–12 signals.

### Wider caps amplify losses too

The gains are skewed positive, but widening also hurts in specific months:

| Month | Top-3 | All | Δ | Explanation |
|-------|-------|-----|---|-------------|
| 2024-Jul | -11.6% | -28.0% | -16.4pp | Noisy signals; extra tickers added losses |
| 2025-Nov | +17.2% | -10.3% | -27.5pp | Top-3 were the only genuine winners |
| 2025-Mar | -5.0% | -12.0% | -7.0pp | CAUTION month +15m exit; wider net caught weaker signals |
| 2026-Jan | -0.2% | -13.7% | -13.5pp | 2026 has noisier signals beyond the top tier |

### 2026 YTD: Top-3 outperforms wider caps

Top-3 +67.2% vs Top-8 +56.0% (-11.2pp). This suggests 2026 signals have lower average quality beyond rank 3, consistent with the higher avg daily count (3.4/day) combined with a mixed regime (Feb -21.6% drag month).

### Year-wins by cap

| Year | Best cap | Worst cap |
|------|----------|-----------|
| 2016 | Top-5 (+83.9%) | Top-3 (+81.2%) — minimal difference |
| 2017 | Top-5 (+38.7%) | Top-8/All (+32.7%) |
| 2018 | All/Top-8 (+120.6%) | Top-3 (+93.3%) |
| 2019 | All/Top-8 (+52.2%) | Top-3 (+26.2%) |
| 2020 | Top-5 (+90.6%) | Top-8/All (+79.8%) |
| 2021 | Top-8 (+17.1%) | Top-3 (-15.7%) |
| 2022 | All (+276.6%) | Top-3 (+187.5%) |
| 2023 | Top-8 (+79.1%) | Top-3 (+38.8%) |
| 2024 | Top-8/All (+116.8%) | Top-3 (+98.3%) |
| 2025 | All (+186.5%) | Top-5 (+121.9%) |
| 2026 | Top-3 (+67.2%) | Top-8 (+56.0%) |

**Top-3 wins only 2026 YTD. Top-8 or All wins 6 of 11 years.**

### Notable month-level drivers

**2022-Jan (SHORT):** +49.7% → +84.1% (Top-8). The January 2022 crash was the single most impactful month. Every additional short signal captured genuine crash exposure; the top-3 only saw 59.7% EOD decline vs 82.8% for all signals.

**2025-Apr (LONG):** +62.1% → +157.1% (All). The April 2025 tariff-driven bounce produced unusually clean LONG signals. This single month accounts for most of 2025's advantage for wider caps.

**2019-Jan (LONG):** +18.2% → +33.5% (All). The Jan 2019 V-recovery produced strong LONG signals across many tickers — wider net captured more of the move.

---

## Recommendation

**For a conservative live strategy, Top-3 remains appropriate** — it avoids the noise-amplification risk seen in 2024-Jul, 2025-Nov, and 2026. The +292pp cumulative gain from widening to All is heavily back-loaded in extraordinary months that are not guaranteed to recur.

**For a research/simulation baseline, Top-5 is the most consistent upgrade** — adds +151pp cumulative with fewer drawdown months than Top-8/All, and avoids the 2025-Nov cliff (-27.5pp) that hurts Top-8.

If widening to Top-5, watch for months where the regime is uncertain (Mar CAUTION, mixed-signal months like 2020-Dec) — the extra signals often come from lower-quality entries in those environments.
