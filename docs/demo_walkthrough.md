# Five-minute demo

Launch with the exact command in README; EIA credentials can be absent. The packaged artifacts are historical PJM hourly demand in MWh, not live health alerts.

1. **Forecast Explorer:** choose 2025-10-01 00:00 UTC. Its 24 targets run 01:00 UTC to the next midnight. Compare locked candidate, observed demand attached afterwards, and same-hour-last-week baseline. Read the origin-specific 24-target MAE/WAPE and expand the timestamp rows.
2. **Evaluation:** test period is October–December 2025. Full scope contains 2,208 matched targets for each model; candidate WAPE is 3.6149%. Set horizon scope to 1–12: both paired counts must become 1,104 and metrics recompute from selected error/actual sums. Restore 1–24, then select validation: 89/92 paired origins, 2,136 matched targets. Peak cohort table remains explicitly full scope.
3. **Reliability & Model Lineage:** inspect 17,906 valid padded observations, 22 missing/rejected hours, local candidate registry version 1 and 18 synthetic recovery checks. Expand historical lineage and model limitations. The source period, collection date, fit cutoff, release, snapshot, and checksum are different concepts.

Evidence: `docs/evidence/browser_checks.json`, AppTest in `tests/test_contracts.py`, and three actual images in `assets/screenshots`. AppTest removes EIA credentials, rejects all HTTP requests/external sockets and model deserialization, then renders each view and checks the filter. Loopback IPC remains available to Streamlit's test harness. A server response alone was not used as rendering evidence.

The current published generation is checksum validated. An interrupted export preserves the prior pointer; retry export after database success without re-scoring. All recovery injections are isolated and labeled synthetic.
