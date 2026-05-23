# ZZ500 Focus Platform Check

## Question

After the multi-index amount scan, ZZ500 had the best recent-window drawdown improvement but failed the formal 10Y bar. This note checks whether ZZ500 is a single lucky point or a broader research platform.

## Inputs

- Source run: `20260523_a_us_momentum_combo_v7_7_sub_a_dk_multi_index_amount_filter`.
- Strategy baseline: V7.7 8-pair ADK, formal start `2014-10-17`.
- Rule family: ZZ500 index amount below its own MA for `N` consecutive days.
- Grid: `MA 10..80`, `days 2..20`, T close signal, T+1 ADK total exposure to `50%`.
- Extra cost: `10bp * abs(scale change)`.
- Analysis source: existing `scan_summary_wide_detailed.csv`; no production strategy script was changed.

## Result

ZZ500 is not a one-point accident, but the platform is only a research lead, not a production rule.

- Formal robust pass count: `0`.
- Recent-only pass count: `38`, using `5Y DD >= +1pp`, `3Y DD >= +1pp`, `5Y annual >= -1pp`, and `3Y annual >= -1pp`.
- Relaxed recent pass count: `69`, if annual loss tolerance is widened to `-2pp`.
- Recent-pass range: `MA 26..54`, `days 5..9`.
- Core cluster: `days=5..7`, especially `MA34..41`.
- Best formal-defense-score row remains `MA34 / 4 days`, but it only appears after relaxing the 5Y annual loss tolerance because its 5Y annual delta is `-1.28pp`.

## Key Rows

| Candidate | 10Y Ann Delta | 10Y DD Delta | 5Y Ann Delta | 5Y DD Delta | 3Y Ann Delta | 3Y DD Delta | Read |
|---|---:|---:|---:|---:|---:|---:|---|
| MA34 / 4 days | -2.61pp | +0.00pp | -1.28pp | +2.39pp | +2.09pp | +2.39pp | Best score, but 10Y and 5Y annual drag are too large |
| MA28 / 5 days | -2.06pp | -0.01pp | -0.86pp | +1.98pp | +1.65pp | +1.98pp | Best under recent-only pass |
| MA35 / 5 days | -2.85pp | -0.09pp | -0.68pp | +2.14pp | +1.47pp | +2.14pp | Part of the main day-5 ridge |
| MA37 / 6 days | -1.96pp | +0.00pp | -0.45pp | +1.60pp | +1.39pp | +1.60pp | Softer trigger, still not 10Y robust |
| MA26 / 8 days | -1.09pp | +0.00pp | -0.10pp | +1.26pp | +0.74pp | +1.26pp | Better 10Y annual drag, weaker recent payoff |

## Platform Shape

Recent-only candidates are concentrated rather than scattered:

- `days=5`: 18 candidates, `MA28..54`, max score `3.39`.
- `days=6`: 10 candidates, `MA26..41`, max score `2.60`.
- `days=7`: 8 candidates, `MA34..41`, max score `0.89`.
- `days=8`: 1 candidate, `MA26`.
- `days=9`: 1 candidate, `MA37`.

The local neighborhood around `MA28..42 / days 2..8` confirms the ridge:

- `days=4` has the highest average score and best raw drawdown pickup, but tends to lose too much annual return.
- `days=5` is the most defensible research area: still gives about `+1.9pp` recent DD improvement on average while reducing the annual-return damage.
- `days=6..7` fades quickly; they remain useful for sensitivity checks, not for promotion.

## Interpretation

ZZ500 has a real near-window platform, mainly a `days=5` ridge around `MA34..41`, with adjacent support down to `MA28` and up to `MA50`. However, the platform does not touch the formal target:

- 10Y drawdown improvement is effectively zero for the useful cluster.
- 10Y annual return drag is still around `-2pp` to `-3pp` for the main ridge.
- The rows that reduce 10Y annual drag, such as `MA26 / 8 days`, give weaker recent-window payoff and still do not improve 10Y drawdown.

Conclusion: keep DK amount as warning-only. If this family is revisited, start with `ZZ500 MA28..41 / days 5..6` as a research lead, not as a production candidate.

## Derived Files

- `zz500_focus_platform_candidates.csv`: selected top, recent-pass, and relaxed-recent ZZ500 rows.
- `zz500_focus_platform_by_days.csv`: recent-pass grouping by consecutive-day threshold.
- `zz500_focus_neighborhood_ma28_42_d2_8.csv`: local-neighborhood grouped diagnostics.
