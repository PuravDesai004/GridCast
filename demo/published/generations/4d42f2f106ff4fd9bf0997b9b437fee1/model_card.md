# GridCast model card

Source: REAL_EIA PJM D; megawatthours, UTC interval ends. Retrospective availability assumes a three-hour delay; historical publication vintages were not reconstructed.

Champion: **candidate**. Final fitting ends at 2025-10-01 00:00:00+00:00. Training examples: 15123; final training peak threshold: 118411.40000000001 megawatthours.

Selection and validation: `C:\Users\purav\OneDrive\Desktop\Data Projects\GridCast\state\selection.json`. Frozen test: `C:\Users\purav\OneDrive\Desktop\Data Projects\GridCast\state\test_result.json` (2208 matched targets, 92/92 origins).

Features use known calendars, 168/336-clock-hour lags, a cutoff-eligible anchor, trailing 24/168-hour population statistics and coverage, and 24-hour anchor change. One global histogram gradient boosting candidate; no random internal validation.

Candidate gates: anchor age <=6h, >=22/24 recent, >=160/168 weekly, >=22/24 week lags. Fallback requires all 24 week lags; otherwise UNAVAILABLE with no numeric forecasts. Predictions are clipped at zero under nonnegative_clip_v1 in evaluation and serving.

Intended use: portfolio planning/error inspection. No dispatch, realized savings, production SLA, prospective accuracy, or warehouse integration claims. No weather features or uncertainty intervals; unusually hot/cold weeks can defeat weekly lags.
