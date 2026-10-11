# Manual Snowflake pilot — unexecuted

**Purav runs every warehouse command.** Codex prepared and AST-parsed Python locally, checked official API documentation, and exported local portable inputs. It did not authenticate, inspect an account, run diagnostics, execute SQL, upload, register, or infer in Snowflake. SQL syntax and runtime/account compatibility remain unverified. The entire integration remains **implemented but unverified** until sanitized execution evidence is supplied.

The authoritative project is the local release. Warehouse inference demonstrates the exact fitted candidate, without retraining. If a later release selects baseline, this candidate demonstration must still be labeled separately.

## 1. Account, permission, runtime, and cost checks

Purpose: establish a bounded, disposable pilot. Prerequisites: your own Snowflake account, MFA/SSO, billing/trial balance, role allowed to create the dedicated database/schema/stage/tables/model, and warehouse USAGE/OPERATE. In your own account UI review Python runtime and package availability, especially **Python 3.14, scikit-learn 1.9.1, NumPy 2.5.4, SciPy and pandas 3.0.6**. Do not assume these are supported because local installation passed.

The local trained artifact uses Python 3.14. If the account cannot run this exact supported dependency set in WAREHOUSE, stop the registry path and record the limitation. Do not downgrade silently, retrain, or substitute a different model. Loading/parity/export work may continue independently. [Registry runtime/dependency documentation](https://docs.snowflake.com/en/developer-guide/snowflake-ml/model-registry/overview) describes explicit WAREHOUSE targeting and dependency failure behavior.

Choose your own credit budget. Have an administrator attach a project resource monitor if permitted, understanding it does not cover every storage/serverless charge. The scripts use an XSMALL warehouse, 60-second auto-suspend, five-minute statement timeout, UTC session, and query tag. No tasks, schedules, containers, or serverless inference are created. Check cost after each step and explicitly suspend when finished.

## 2. Local export and separate client environment

Purpose: create bounded, checksum-described inputs before any upload. In GridCast's verified local environment run:

```powershell
.\.venv\Scripts\python.exe -m gridcast export-snowflake
$exportDir = (Resolve-Path reports\snowflake).Path
```

Inspect `export_manifest.json`: observation versions, receipts, a 336-row loading sample, 120 real feature/prediction parity rows over five origins, and separate **synthetic** A→B→A inputs. The real origins include ordinary hours, the real March 2024 gaps, and both DST transitions. The sample checks loading only; it is not sufficient by itself for a 336-hour feature forecast.

Use a separate pilot environment, never modify `.venv`. With a compatible interpreter you have chosen and installed yourself:

```powershell
python -m venv .snowflake-venv
.\.snowflake-venv\Scripts\python.exe -m pip install -r requirements\snowflake.in
.\.snowflake-venv\Scripts\python.exe -m pip check
.\.snowflake-venv\Scripts\python.exe -m pip freeze > reports\snowflake\user_client_lock.txt
$env:SNOWFLAKE_ACCOUNT = '<YOUR_ACCOUNT_IDENTIFIER>'
$env:SNOWFLAKE_USER = '<YOUR_USER>'
$env:SNOWFLAKE_ROLE = '<YOUR_PILOT_ROLE>'
```

The pilot input requirements are **unresolved/uninstalled**. Check their solver output before continuing. External-browser authentication in `snowflake/user_session.py` opens your own SSO flow. No passwords are stored. Do not export account/user identifiers or authentication logs publicly. If client packages cannot coexist with exact model dependencies, record the compatibility block rather than altering the trained model.

## 3. Setup and smoke test

Purpose: isolated schemas and cost controls. Prerequisites: step 1 role approval and chosen budget. Open `snowflake/01_setup.sql` in your Snowflake SQL worksheet or execute it in your configured SnowSQL client:

```powershell
snowsql -c <YOUR_PRIVATE_CONNECTION_NAME> -f snowflake\01_setup.sql
```

Expected: GRIDCAST_PILOT database; RAW, RAW_FIXTURE, FEATURES, ANALYTICS schemas; stage/file format; typed version/receipt and immutable forecast/error tables; actual account/role/warehouse/version smoke output; warehouse suspended. The account output is for your private inspection. Save only a sanitized pass/fail receipt. If a permission fails, request the exact missing privilege and retry idempotent setup. Never use a production/shared database in place of the pilot.

## 4. Sample, full load, replay, synthetic revision load

Purpose: enforce data contract and duplicate-safe persistence. Use the gated Python loader as the executable path (`02_load.sql` is a worksheet reference for the same sample pattern):

```powershell
.\.snowflake-venv\Scripts\python.exe snowflake\02_load.py --export-dir $exportDir
# Review sample manifest/counts first; only then load full real versions and receipts.
.\.snowflake-venv\Scripts\python.exe snowflake\02_load.py --export-dir $exportDir --full
.\.snowflake-venv\Scripts\python.exe snowflake\02_load.py --export-dir $exportDir --fixture
```

Expected: uploaded counts equal local file counts; PJM/D/megawatthours and timestamps valid; invalid/null source values retained as invalid versions; no valid negative/nonfinite values; no unknown receipt versions; immutable existing identities match. MERGE is rerun and total rows must remain unchanged. `warehouse_load.json`/`warehouse_fixture_load.json` record before/after/replay counts. Standard Snowflake uniqueness constraints are not enforcement; the scripts explicitly check conflicts.

If a gate fails, preserve destination, fix/re-export the input or investigate the identity conflict. Do not force an overwrite of an immutable version. Staging data is temporary; replay is safe. RAW_FIXTURE is clearly separated from real evidence. Every Python script suspends the warehouse in `finally`.

## 5. Snowpark feature construction and parity

Purpose: compute timestamp-joined features from typed warehouse observations and preserve receipt chronology. Obtain the exact `snapshot_cutoff` from your local export manifest:

```powershell
$snapshotCutoff = (Get-Content reports\snowflake\export_manifest.json -Raw | ConvertFrom-Json).snapshot_cutoff
.\.snowflake-venv\Scripts\python.exe snowflake\03_features.py --export-dir $exportDir --snapshot-cutoff $snapshotCutoff
.\.venv\Scripts\python.exe snowflake\04_compare.py --export-dir $exportDir
.\.snowflake-venv\Scripts\python.exe snowflake\03_features.py --export-dir $exportDir --snapshot-cutoff $snapshotCutoff --mode prospective --fixture
.\.venv\Scripts\python.exe snowflake\04_compare.py --export-dir $exportDir --fixture
```

Expected: 120 real rows with ordinary/gap/DST origins, plus 48 separate prospective synthetic revision rows. Exact origin/horizon keys and calendar/count/offset/fold features must match. Numeric values use rtol 1e-9, atol 1e-8 and equal-NaN checks; population stddev and window endpoints match local code. Receipt order picks B at 2025-01-19 and reverted A at 2025-01-20 in the synthetic case. Retrospective selection uses a frozen actual collection cutoff then simulated +3h availability. Historical receipts never pretend they were collected in 2024/2025.

Expected offline receipts: `feature_parity.json`, `fixture_parity.json`, both PASS. If any feature differs, inspect the exact named feature, source version, timezone, window endpoint, or receipt ordering. **Do not proceed to model registration.** Re-run the small parity origin set after repair. SQL/runtime execution remains a user validation requirement.

## 6. Trusted model registration and explicit warehouse batch inference

Purpose: register the actual fitted candidate and compare predictions, using row identity throughout a batch. Prerequisites: both parity gates PASS, reviewed exact Python/dependencies available in your account and client, source model checksum matching the manifest. The keyed custom-model adapter contains the same trained scikit-learn candidate; it adds row identity and the same nonnegative clipping policy, with no fitting.

```powershell
.\.snowflake-venv\Scripts\python.exe snowflake\05_registry_inference.py --export-dir $exportDir --model state\candidate.joblib --python-version 3.14
.\.venv\Scripts\python.exe snowflake\04_compare.py --export-dir $exportDir --predictions
```

`Registry.log_model` explicitly requests `target_platforms=['WAREHOUSE']`; `ModelVersion.run` executes one bounded 120-row warehouse batch. Returned row IDs, finite nonnegative predictions, complete keys, and local numerical parity are mandatory. Only after parity passes are forecasts MERGEd; replay count is checked. An existing checksum-derived registry version is reused. No duplicate version or new forecast is invented for a retry. The output mode is HISTORICAL_SNAPSHOT_CANDIDATE_PARITY, not prospective production.

Expected: `warehouse_registry.json`, `prediction_parity.json`, and `warehouse_predictions.csv`, with actual account execution facts. Dependency/platform failures leave this integration incomplete. [Custom model context and batch API](https://docs.snowflake.com/en/developer-guide/snowflake-ml/model-registry/bring-your-own-model-types) support wrapping the fitted object with a multirow method.

## 7. Outcomes and analyses

Purpose: attach actual versions without changing forecast values. Replace `<EXPORTED_SNAPSHOT_CUTOFF_UTC>` in a private working copy of `snowflake/06_outcomes.sql`, then execute:

```powershell
snowsql -c <YOUR_PRIVATE_CONNECTION_NAME> -f <YOUR_FILLED_06_OUTCOMES_SQL_PATH>
```

Expected: authority/metric/UTC-target/unit joins; explicit retrospective_frozen error vintages; repeated MERGE inserts zero rows; unchanged forecasts; horizon metrics with summed WAPE denominator; fixed local training peak threshold 118,411.4 MWh; seasonality and model/source health outputs. These five-origin pilot metrics are **not** the full local held-out test. Do not mix actual revision vintages in one metric. New valid actual version creates a new error identity. Review counts before exporting.

## 8. Portable evidence

Purpose: inspect and share small sanitized execution proof:

```powershell
.\.snowflake-venv\Scripts\python.exe snowflake\07_export_cleanup.py --export-dir $exportDir
```

Expected: bounded forecast/error/metric CSVs, parity and load receipts, actual runtime/dependency details and query IDs you privately review. Compare common keys and metric numerators with local parity files, rather than claiming the pilot equals the full 2,208-target test. Remove identifiers/URLs/token echoes and credential-bearing logs before sharing. Add checked hashes and real execution status to the completion matrix only after these operations pass.

## 9. Cost cleanup and recovery

After every failure or successful batch, independently verify in your own worksheet:

```sql
ALTER WAREHOUSE GRIDCAST_WH SUSPEND;
SHOW WAREHOUSES LIKE 'GRIDCAST_WH';
```

If you choose to discard this dedicated pilot **after exporting required evidence**, execute these destructive cleanup commands yourself:

```sql
DROP DATABASE GRIDCAST_PILOT;
DROP WAREHOUSE GRIDCAST_WH;
```

Review billing/storage after cleanup; suspension stops warehouse compute but retained tables/models/stage files may incur storage charges. Clear private client environment variables and preserve only sanitized evidence. A failure is recovered at the failed step; do not rerun local training/test or change the serving champion to make a warehouse demonstration succeed.
