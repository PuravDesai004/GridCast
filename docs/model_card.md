# GridCast model card

Source: EIA API v2 `electricity/rto/region-data`, REAL_EIA PJM D; hourly megawatthours (MWh), UTC interval ends without an hour shift. Retrospective availability assumes a three-hour delay; historical publication vintages were not reconstructed. Detailed implementation and worked examples: [architecture](../architecture.md).

Champion: **candidate**. Final fitting ends at 2025-10-01 00:00:00+00:00. Training examples: 15123; final training peak threshold: 118411.40000000001 megawatthours.

Selection and validation: [selection receipt](evidence/selection.json). Frozen test: [test receipt](evidence/test_result.json) (2208 matched targets, 92/92 origins).

The 26 ordered float64 features comprise 11 horizon/calendar columns, two 168/336-clock-hour lags, two cutoff-eligible anchor columns, five trailing 24-hour statistics/counts, five trailing 168-hour statistics/counts, and 24-hour anchor change. One global histogram gradient boosting candidate; no random internal validation. Exact names and dtypes: [feature contract](../config/feature_contract.yaml).

Candidate gates: anchor age <=6h, >=22/24 recent, >=160/168 weekly, >=22/24 week lags. The seasonal baseline is the target's same hour last week. Fallback requires all 24 week lags; otherwise UNAVAILABLE with no numeric forecasts. Predictions are clipped at zero under nonnegative_clip_v1 in evaluation and serving. Serving honors the validation-selected champion and may use the complete seasonal fallback when candidate loading, prediction, or quality gates fail.

Intended use: portfolio planning/error inspection. No dispatch, realized savings, production SLA, prospective accuracy, or warehouse integration claims. No weather features or uncertainty intervals; unusually hot/cold weeks can defeat weekly lags.

## Matched measured results

| Scope / model | MAE, MWh | WAPE | Signed bias, MWh | Peak MAE, MWh | Paired targets |
|---|---:|---:|---:|---:|---:|
| July–September 2025 validation baseline | 10,047.5576 | 9.7198669% | 1,905.9771 | 12,007.2331 | 2,136 |
| Validation candidate | 3,954.8796 | 3.8258953% | 696.4367 | 5,130.8323 | 2,136 |
| October–December 2025 test baseline | 6,454.3931 | 6.9578812% | −294.8478 | 13,128.4478 | 2,208 |
| Test candidate | 3,353.3136 | 3.6148957% | −727.9941 | 9,521.1243 | 2,208 |

Validation:89/92 complete paired origins,2,136 targets, summed actual denominator220,801,203 MWh and502 peak targets. All92 origins have native baseline/candidate quality eligibility; July 31/August 31/September 30 are purged from selection because their24 labels are not all available by the next fit cutoff. Four configurations across three chronological folds produce 12 selection fits. WAPE relative improvement60.6384% passes2%; candidate peakMAE passes1.05×baseline and coverage96.7391% passes90%.

Test:92/92 paired origins, no missing actuals/quality failures/clipped targets, summed absolute actual204,822,410 MWh. Candidate absolute error sum7,404,116.4099 MWh. Peak threshold118,411.4 MWh comes only from final fitted training labels;67 test targets meet it. Peak error is much larger than average error, limiting operational use. WAPE aggregates error/actual sums; zero denominator is unavailable. Raw candidate metrics contain no seasonal fallback predictions.

## Fit, source, and identities

Final fitted row count reconciles as 639 × 24 possible rows, minus 192 rows from eight quality-excluded origins, minus 21 further missing/boundary labels = 15,123. The reported 25 missing/unavailable labels are counted before quality filtering; four overlap the excluded March 11 origin. This overlap is not subtracted twice.

Initial fitting spans January 2024–June 2025; expanding chronological validation is July/August/September 2025. Fixed final candidate uses leaves 15, L2= 1, max_iter 150, seed 42, early_stopping=False, two CPU threads. Final eligible label count15,123 and latest fitted target2025-09-30 21:00 UTC; no January 2026 guard label is fitted. Twenty-five purged/unavailable labels comprise22 real missing values and3 boundary labels. The three partially purged final origins are March 10/11 2024 and September 30 2025.

Source:17,906 valid padded observations (17,522 core,336 warm-up,48 guard),17,928 delivered versions,22 rejected/null gaps,0 observed multi-version real identities. Collection was in October 2026; historical revised data and simulated three-hour availability do not prove historically available publication vintages or prospective accuracy. Scoring features use windows `(anchor−N hours,anchor]`, population stddev and UTC timestamp joins. Local calendar includes UTC offset and DST fold. Missing observations remain missing.

Candidate checksum:`a06c37975ca1dd53e1483cf0c9da655d94d3cfade6b97f7793b0d69158e71278`.
Local MLflow run:`8b3b63019dcf4be6ab54c3121ef1bd45`; registry `GridCast_PJM_Candidate` version 1.
Authoritative release:`8a4cc72606d13028cbe716c4`.
Selection seal:`14dccd120b80c5c6c65e53eb34c433b601d0b1a8a04ca4ab2688c6c4962077c7`.
First test evaluated2026-10-11T13:12:20.398108 UTC. The first receipt and test result hashes were preserved across reruns. No post-test prediction repair or tuning occurred.

Executed versions:Python 3.14.7, scikit-learn 1.9.1, NumPy 2.5.4, pandas 3.0.6, MLflow 3.17.0, DuckDB 1.5.6; exact resolved dependencies in the local lock/environment receipt. Trusted locally trained artifacts use cloudpickle serialization and checksum validation. The immutable bundle retains its original card; this concise working card links explanatory evidence without modifying that release. Later local pipeline fixes have different code fingerprints and cannot inherit these historical model results; see the [local audit](bug_audit.md).

Evidence: [source](evidence/source_validation.json), [selection](evidence/selection.json), [fit](evidence/final_fit.json), [test](evidence/test_result.json), [first evaluation](evidence/first_test_evaluation.json), [seal](evidence/selection_seal.json), [MLflow](evidence/mlflow.json), [recovery](evidence/recovery.json), and [leakage check](evidence/trained_candidate_leakage.json). No probabilistic intervals, causal savings, live reliability SLA, warehouse execution or hosted CI pass is claimed.
