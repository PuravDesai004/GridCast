# GridCast — evidence-backed portfolio language

Use the following claims with their scope intact. There is no verified cloud integration, prospective accuracy, dispatch result, cost saving, production SLA, or employer business impact.

- Built an auditable PJM forecasting pipeline, measured by 17,906 valid hourly EIA observations across a padded 2024–2025 source window, by separating immutable observation versions from collection receipts and using timestamp-joined cutoff-safe features. Evidence: `evidence/source_validation.json`, `evidence/source_fetch_summary.json`, `src/gridcast/storage.py`.
- Reduced matched **validation** WAPE by 60.64% relative to same-hour-last-week forecasting, from 9.7199% to 3.8259% across 2,136 target hours and 89/92 scheduled origins, by comparing four bounded chronological histogram-boosting configurations under predeclared coverage and peak gates. Evidence: `evidence/selection.json`; this is retrospective simulated availability, not observed publication vintages.
- Achieved 3.6149% WAPE and 3,353.31 MWh MAE on the sealed October–December 2025 test, covering 92/92 daily origins and 2,208 paired targets, by fitting the validation-chosen candidate on eligible pre-test labels and preserving the first evaluation receipt. Evidence: `evidence/test_result.json`, `evidence/first_test_evaluation.json`, `evidence/selection_seal.json`.
- Verified 18 **synthetic engineering** recovery checks, including A→B→A delivery chronology, zero-duplicate replay, interrupted-transaction rollback, corrupted-model fallback and export-pointer preservation, by injecting isolated failures and preserving before/after counts and checksums. Evidence: `evidence/recovery.json`; this is not evidence of 18 production incidents handled.

Keep the grains separate: 17,928 source versions delivered (22 invalid), 17,906 valid distinct observations, 17,544 feature horizon rows across 731 scheduled origins, 15,123 final fitted label rows, 2,136 validation comparison targets, and 2,208 final-test comparison targets. Training examples are not independent days. Adjacent horizons are correlated; no confidence interval was claimed.

Describe local MLflow tracking/registered candidate and immutable local serving releases as executed. The first hosted Ubuntu CI run failed Windows-drive path containment (42 passed, one failed, one skipped); the cleanup run also failed overall. Snowflake scripts remain prepared and unexecuted. See the [CI review](evidence/hosted_ci_review.json). Use measured peak MAE 9,521.12 MWh on 67 high-demand test targets as a limitation, not as evidence of operational safety. Full claims and denominators are in the [model card](model_card.md) and [README](../README.md).

Architecture companion: [implemented architecture and viva explanations](../architecture.md). The earlier PDF remains a dated local export.

Later pipeline verification: [Ubuntu follow-up](https://github.com/PuravDesai004/GridCast/actions/runs/38210511471) at `bf1b3dd` passed all steps (56 tests/one private-real-state skip). This is separate from the historical model evidence. [Receipt](evidence/hosted_ci_followup.json).

Optional detailed historical review queries are archived locally under `../GridCast_local/review/architecture-review/`; the public evidence above remains available without that archive.
