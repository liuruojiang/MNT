# ADK Spread Layered Test Process

Updated: 2026-06-09

This document is the required workflow for standalone ADK spread research lines such as `long SZ50 / short CYB`, `long CYB / short SZ50`, and other two-index spread sleeves. It exists to prevent layer-order mistakes and to keep every candidate comparable.

## Hard Rules

- Test one layer at a time. After each layer, write artifacts, run the strict checker, summarize the layer, and stop for user confirmation.
- Do not skip the layer order. A later overlay can be run only as a clearly labeled side diagnostic, not as the formal next layer.
- Every reported candidate table must include annualized return and max drawdown for `full`, `last_10y`, `last_5y`, `last_3y`, and `last_1y`.
- When comparing a candidate with the original baseline or previous-layer baseline, always show the complete window set: `full`, `last_10y`, `last_5y`, `last_3y`, and `last_1y`, with annualized return and max drawdown for every row.
- Do not pick an edge-of-grid maximum if a sufficiently wide secondary ridge exists. Report ridge/neighbor width before recommending a tuple.
- Carry at least one primary line, one nearby confirmation line, and any user-requested return-heavy line until the user explicitly drops it.
- Every layer must state data source, formal start/end dates, row count, direction, execution timing, cost model, and whether the result is formal, quasi-formal, or diagnostic.

## Formal Layer Order

### Layer 0/1 - Direction, Data, And Signal Family

Purpose: establish the correct spread direction and signal family.

Required checks:
- Confirm the direction, for example `long SZ50 / short CYB`.
- Confirm listing/publication availability and formal common sample start.
- Confirm the price ratio and return stream, for example `SZ50 / CYB` and `SZ50 return - CYB return`.
- Compare signal families from scratch for this direction; do not inherit the opposite direction's family.

Outputs:
- Best family and tuple.
- Family-level width or ridge support.
- Full/10Y/5Y/3Y/1Y return and drawdown table.

### Layer 1 Dense Patch - Signal Parameter Width

Purpose: widen around the promising signal family and avoid thin or edge-bound choices.

Typical parameters:
- signal window, bias MA, momentum day, weighted-slope weight, score threshold if already part of the family.

Required decision:
- Select a non-edge, width-supported anchor if available.
- Keep a nearby confirmation tuple.
- Exclude edge-bound global maxima unless explicitly approved.

### Layer 2 - Score And Absolute Bias Filter

Purpose: test whether a score threshold and absolute ratio-bias gate improve the signal without damaging recent windows.

Typical parameters:
- score threshold.
- absolute MA.
- absolute bias threshold.

Required checks:
- Compare against the exact Layer 1 anchor.
- Report full-sample and 5Y non-underperformance counts.
- Prefer broad patches over a single high-score point.

### Layer 3 - Target Vol

Purpose: test portfolio scaling after the signal/filter layer.

Typical parameters:
- target vol.
- realized-vol window.
- max leverage.
- min leverage or floor if used.
- leverage rebalance threshold / scale-change deadband if target-vol leverage is used.

Required checks:
- Recompute turnover and costs after scaling.
- Report target-vol width across target vol, window, and max leverage.
- If target-vol leverage is enabled, scan the leverage rebalance threshold / scale-change deadband in this layer, for example the minimum relative or absolute scale change required before changing exposure.
- Report turnover, cost, average scale, scale-change frequency, and whether the selected threshold avoids impractical day-to-day leverage adjustments.
- Do not carry a target-vol candidate forward on raw return/drawdown alone if the leverage threshold was not scanned or if the resulting exposure path requires frequent small live adjustments.
- Carry return-heavy variants only as watchlist unless width and drawdown are both acceptable.

### Layer 4 - NAV Defense

Purpose: test prior-row NAV drawdown defense after target-vol.

Typical parameters:
- NAV drawdown threshold.
- defense scale.

Required implementation:
- Compute pre-overlay candidate NAV and prior-row drawdown.
- Apply defense to the next execution row only.
- Recompute turnover, costs, return, NAV, and drawdown after defense.

Important:
- NAV defense is followed by momentum decay in the formal sequence.
- Overheat, vol-hot, amount, or volume overlays are not the formal next layer after NAV defense.

### Layer 5 - Momentum Decay

Purpose: test whether weakening signal strength inside an active trade should decay exposure.

Correct definition:
- Momentum decay must be based on signal strength, such as pair score or bias-momentum score, relative to the current trade's score peak.
- It must not be a second NAV drawdown gate.
- The trigger is evaluated at T close and shifted to next execution.

Typical parameters:
- decay ratio threshold, for example current score divided by trade peak.
- recovery ratio threshold.
- warmup or confirmation days if used.
- derisk scale.

Required implementation:
- Track score peak only during active holding segments.
- After recovery, require a new score peak before another decay cycle if that is the local pattern.
- Recompute final exposure changes and costs.
- Compare to the exact NAV-defense baseline from Layer 4.

Required decision:
- If momentum decay is thin, label it rejected and carry Layer 4 unchanged.
- If it is broad and improves return/DD, carry the best width-supported decay tuple.
- If it conflicts with NAV defense, run the four-quadrant check before promoting.

### Layer 6 - Four-Quadrant Interaction Check, If Needed

Purpose: identify whether two state overlays are complementary or redundant before stacking more layers.

Run this check when any of these are true:
- NAV defense and momentum decay both trigger materially.
- Momentum decay improves headline metrics but hurts one or more recent windows.
- The best candidate depends on a narrow interaction of two state gates.
- The next candidate layer may overlap the same stress regime.

Default four quadrants after Layer 5:
- Q00: NAV defense off, momentum decay off.
- Q10: NAV defense on, momentum decay off.
- Q01: NAV defense off, momentum decay on.
- Q11: NAV defense on, momentum decay on.

Required outputs:
- Days in each quadrant.
- Average and median final exposure in each quadrant.
- Gross return, cost, and net return contribution in each quadrant.
- Full/10Y/5Y/3Y/1Y candidate-level annualized return and max drawdown for: NAV only, decay only, NAV plus decay, and baseline without the new layer.
- Explicit statement whether the two overlays are complementary, redundant, or conflicting.

Decision rules:
- If Q11 dominates drawdown improvement without large return damage, stacking may continue.
- If Q10 and Q01 each work but Q11 damages return, keep only the better single overlay.
- If one quadrant has too few days, mark the interaction as under-supported and do not promote based on it alone.

### Later Layers - Overheat, Volhot, Amount, Volume, Final Ridge

These layers come after momentum decay or after the four-quadrant check when needed.

Typical order:
- realized-vol or score overheat.
- first-entry staging, for example enter half exposure first, then add the remaining half after a bearish candle or approved pullback trigger.
- amount/volume filter if a clean source panel exists.
- final ridge or fixed-script landing.

Important:
- A volhot/overheat scan immediately after NAV defense is a side diagnostic only. It is not the formal Layer 5.
- First-entry staging must record whether true OHLC candles are available. If open prices are unavailable, a close-to-close pullback proxy such as `close < prior close` is diagnostic or quasi-formal, not a formal bearish-candle conclusion.
- First-entry staging must state the initial exposure fraction, the add-on trigger, whether a maximum wait is used, and whether the add-on state is shifted to the next execution row.
- Amount/volume tests must record data source, unit normalization, and whether the result is formal or quasi-formal.

## Artifact Requirements

Every formal layer must write:
- `scan_summary.csv`
- `window_metrics.csv`
- `daily_curves.csv`
- `ridge_width.csv` or an equivalent width table
- `scan_meta.json`
- `record.md`
- `command_log.txt`

Every `record.md` must include:
- formal direction and sample dates.
- execution timing and cost model.
- layer inputs and exact anchor tuples.
- full/10Y/5Y/3Y/1Y return and drawdown table.
- width/ridge summary.
- decision and next-layer carry list.
- verification commands and strict checker result.

## Correction Note For 2026-06-09 SZ50/CYB Run

The run folder `quant_param_scan_runs/20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer5_overheat_after_nav_with_return_line` was created out of formal order. It should be treated as a side diagnostic only.

The formal next layer after `quant_param_scan_runs/20260609_adk_sz50_cyb_reverse_spread_long_only_v77_adk_reverse_spread_layer4_nav_defense_after_l3_tv_with_return_line` is momentum decay.
