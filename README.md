# GridCast

GridCast forecasts the next 24 UTC interval ends for PJM demand and preserves the evidence needed to explain every batch. It runs natively on Windows with DuckDB, scikit-learn, local MLflow, and a credential-free Streamlit dashboard.

The completed real-data release uses EIA hourly demand for 2024–2025, with separately counted lag/label padding. Historical retrievals were collected in October 2026: **HISTORICAL_SNAPSHOT** results assume interval-end + three-hour availability and do not reconstruct historical publication vintages.

| Matched scope | Baseline WAPE | Candidate WAPE | Baseline MAE, MWh | Candidate MAE, MWh | Paired origins / scheduled | Targets |
|---|---:|---:|---:|---:|---:|---:|
| Validation, July–September 2025 | 9.7199% | 3.8259% | 10,047.56 | 3,954.88 | 89 / 92 | 2,136 |
| Frozen test, October–December 2025 | 6.9579% | 3.6149% | 6,454.39 | 3,353.31 | 92 / 92 | 2,208 |

Validation selected the candidate under the predeclared coverage, WAPE, and peak-error gates. Test results did not alter selection. See [the evidence matrix](docs/completion_matrix.md), [implemented architecture and teaching](architecture.md), and [completion report](docs/completion_report.md).

## Windows setup

Executed environment: Windows x64, PowerShell, Python **3.14.7**. The only installed interpreter was 3.14; isolated package installation, imports, and `pip check` passed. No global packages, Docker engine, WSL, or unrelated project environment was changed.

From the project directory:

```powershell
Set-Location 'C:\Users\purav\OneDrive\Desktop\Data Projects\GridCast'
python -m venv .venv
New-Item -ItemType Directory -Force -Path state\tmp,state\matplotlib | Out-Null
$env:TEMP = (Resolve-Path state\tmp).Path
$env:TMP = $env:TEMP
$env:MPLCONFIGDIR = (Resolve-Path state\matplotlib).Path
.\.venv\Scripts\python.exe -m pip install -r requirements\local.windows-py314.lock.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
```

Skip `venv` creation and installation when continuing the supplied working environment. The lock pins the actual Windows resolution. `requirements/local.lock.txt` adds a Windows marker for pywin32 for Linux CI; **Linux installation and hosted CI are pending**, not verified. Python 3.12/3.13 support is allowed by project metadata but this exact lock was resolved on 3.14 only. CPU fits use two threads, sequential folds, at most four configurations, 150 iterations, seed 42, and no early stopping.

## Launch the packaged real dashboard

No credentials, database, model, or MLflow server are needed:

```powershell
Remove-Item Env:EIA_API_KEY -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

Open [the local preview](http://127.0.0.1:8501). Three actual captured views are in `assets/screenshots`. `demo/published/current.json` names one complete generation; each artifact is verified before rendering. See [demo walkthrough](docs/demo_walkthrough.md).

## Offline fixture and checks

Use a **new** isolated root for a clean run; never overwrite real state with fixtures:

```powershell
.\.venv\Scripts\python.exe -m gridcast run --mode build --fixture --compact --offline --root state\my-clean-fixture --config config\fixture.yaml --splits config\fixture_splits.yaml
.\.venv\Scripts\python.exe -m gridcast verify-scenarios --root state\my-clean-fixture --config config\fixture.yaml
.\.venv\Scripts\python.exe -m gridcast validate-demo --root state\my-clean-fixture --config config\fixture.yaml
.\.venv\Scripts\python.exe -m ruff check src app tests scripts snowflake
.\.venv\Scripts\python.exe -m pytest -q --junitxml=state\pytest.xml
```

Fixture metrics are synthetic engineering checks. They must never be used as portfolio accuracy claims. Tests needing a completed real seal may skip on a fresh CI checkout; fixture, contracts, and snapshot/app tests have their own coverage. The local final run records exact executed counts in `docs/evidence/pytest-final.xml`.

## Real build and resume

Register privately at [EIA Open Data](https://www.eia.gov/opendata/register.php), then set a key only in the launching PowerShell process:

```powershell
$env:EIA_API_KEY = [System.Net.NetworkCredential]::new('',(Read-Host 'Enter EIA key privately' -AsSecureString)).Password
.\.venv\Scripts\python.exe -m gridcast inspect-source
.\.venv\Scripts\python.exe -m gridcast run --mode build
```

The build executes source inspection/ingestion/validation, features, four-config backtesting, final fit and seal, frozen-test evaluation, release, seven example batches, outcomes, SQL, snapshot export and validation. Whole monthly windows are staged before publication. Stage receipts in `state/stages` preserve successes and failures. Re-running a sealed build verifies/reuses the selection and first test receipt rather than tuning again:

```powershell
.\.venv\Scripts\python.exe -m gridcast run --mode build --offline
.\scripts\run_local.ps1 -Mode build -Offline
```

`--offline` requires previously validated real caches. For a fresh independent real reproduction, pass a new `--root`, `--config config/project.yaml`, and `--splits config/splits.yaml`; EIA revisions retrieved later may yield different results. Preserve the supplied seal and first-evaluation evidence. Do not delete them to bypass a fingerprint mismatch.

## Daily scoring, replay, recovery, rollback

```powershell
.\.venv\Scripts\python.exe -m gridcast forecast --origin 2025-10-01T00:00:00Z
.\.venv\Scripts\python.exe -m gridcast forecast --origin 2025-10-01T00:00:00Z
.\.venv\Scripts\python.exe -m gridcast run --mode daily --offline --origin 2025-10-01T00:00:00Z
.\.venv\Scripts\python.exe -m gridcast verify-scenarios
.\.venv\Scripts\python.exe -m gridcast export-demo
.\.venv\Scripts\python.exe -m gridcast validate-demo
.\.venv\Scripts\python.exe -m gridcast rollback --release-id 8a4cc72606d13028cbe716c4
```

Same logical identity verifies the output hash and inserts zero extra forecasts. Daily mode does not train or evaluate the holdout. Default config is retrospective; prospective collection must use an independently approved/configured collector and receipt history. No schedule is created. Rollback can only select an existing checksum-valid bundle; the current release ID above is also a safe pointer reconciliation example. Synthetic recovery creates its own fault-injection workspace.

## Inspect artifacts and troubleshoot

`python -m gridcast --help` lists every stage and argument. The main database is `state/gridcast.duckdb`; registry metadata is `state/mlflow.sqlite`, artifacts `state/mlflow_artifacts`, model `state/candidate.joblib`, serving pointer `releases/current.json`. Runtime assets are ignored by Git; compact sanitized receipts and the current snapshot are public-ready.

- Missing EIA key: set it privately in the process that performs ingestion; offline dashboard and fixtures still work.
- Temporary-directory permission error: create and point TEMP/TMP to `state/tmp` as above. If the desktop sandbox denies loopback sockets, launch the same command in your own PowerShell; do not change firewall settings.
- Source contract/authentication failure: inspect sanitized stage/source receipts, correct configuration/key, then retry the failed window. Do not promote partial pages.
- Changed seal: restore the exact sealed configuration, code, dependencies, and artifacts. A new experiment belongs in another root. The original holdout has already been viewed.
- Corrupt candidate: the scoring contract can use complete seasonal fallback without deserializing it. Missing fallback inputs yield UNAVAILABLE with zero numeric rows.
- Snapshot failure after DB success: retry `export-demo`, then `validate-demo`; committed forecasts remain immutable.
- Port 8501 busy: stop the existing preview or use another explicit local port.

Manual Snowflake work is completely **unexecuted**. Start with [the user-run guide](docs/snowflake_steps.md); local completion does not require it. No repo was pushed, service deployed, external resource created, or background schedule installed.

## Hosted CI, when you choose to publish

The prepared `.github/workflows/offline-checks.yml` runs on Linux with no keys or historical downloads. After reviewing the secret scan/evidence, create your own repository and execute:

```powershell
git remote add origin <YOUR_GITHUB_REPOSITORY_URL>
git push -u origin HEAD
gh run list --workflow offline-checks.yml
gh run view <ACTUAL_RUN_ID> --log-failed
```

These commands were not executed. Record the actual commit/run URL and downloaded evidence before claiming hosted CI passed.
