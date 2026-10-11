# GridCast cleanup - 11 October 2026

The cleanup removes confirmed development leftovers, preserves the completed local
release and portable demo, and leaves pre-existing code/documentation changes
intact. The GitHub cleanup commit changes repository hygiene and documentation;
it does not publish the separate uncommitted bug fixes or architecture/resume work.

## Removed after inspection and backup

| Reason | Removed paths | Retained evidence or replacement |
| --- | --- | --- |
| Repeated test workspaces | `.pytest_tmp_source`, `.pytest_tmp_source_contracts`; `state/pytest-{dashboard,final,before-release,contracts,ready}`; `state/tmp/pytest-of-purav` | Behavioral tests and every compact historical JUnit receipt |
| Superseded bug-audit workspaces | `state/bug-audit/{dashboard-manual-tests,fixture,pytest-baseline,pytest-final,pytest-full,pytest-release,pytest-serving,pytest-serving-final}` | Latest `state/bug-audit/final-fixture`, JUnit XML files and daily-validation receipt |
| Superseded synthetic fixture | `state/clean-fixture` | `state/fixture-release-check`, used by the packaging script, and its public summary |
| Duplicate public packaging | `state/public-release-check`, `state/gridcast-public-ready.zip` | Exact source in Git and the external recovery archive |
| Unreferenced demo generations | `09a174a6322a43bba54c2029ffc455bd`, `2f2e438fa3b04d5b8055b3ac5796ed27`, `b9fbe3305a394d559bf39b243ee1754e` under `demo/published/generations` | Current generation `4d42f2f106ff4fd9bf0997b9b437fee1` and its pointer/manifest |
| Regenerable caches | Project Python `__pycache__` directories, `.pytest_cache`, `.ruff_cache` | Source and existing environment |
| Completed checklist | `docs/working_plan.md` | [Completion matrix](completion_matrix.md) and [completion report](completion_report.md) |

Initial cleanup removed **2,050 files / 551,034,773 logical file bytes
(525.5 MiB)**. Verification scratch is removed after checks; small final receipts
are retained. These are logical byte measurements, not filesystem allocation or
OneDrive cloud-storage measurements. The outside-repository backup occupies
85,323,607 bytes (81.4 MiB), so the initial removal exceeds that archive by
465,711,166 bytes (444.1 MiB), before retained verification receipts.

Backup: sibling directory `GridCast-cleanup-backup-20261011T151106Z`, containing
`recoverable-files.zip` and `backup-receipt.json`. Its 2,038 payload files include
nontrivial removed content and a snapshot of pre-existing edits. Every payload
checksum was verified by reading it back from the ZIP. Credentials, virtual
environments and regenerable compiled cache files were excluded. Archive SHA-256:
`62981db942c2fd14d5edbf88a2bba66e055a50f68bc1d8d99c312e73f805e04c`.

Restore selected ZIP paths into an isolated directory first. The archive preserves
repository-relative paths; do not overwrite newer local edits with a blanket
extraction. The completed checklist is also recoverable from Git history.

## Deliberately retained

- Application/CLI, ingestion and validation, features/training/inference,
  evaluation/recovery/analysis, dependency locks, configuration placeholders,
  focused behavioral tests, CI, SQL and manual Snowflake scripts.
- README and root architecture, model card, measured findings, resume evidence,
  completion matrix/report, original proposal and concise verification receipts.
  Earlier failed/skipped results remain available.
- Genuine dashboard screenshots and the small validated current demo generation.
  The current demo payload files total 110,706 bytes, excluding manifest/pointer.
- Real source artifacts/cache and lineage, `data/db/gridcast.duckdb`, candidate
  model, MLflow SQLite/artifacts, serving bundles, selection seal, first evaluation,
  saved predictions, release metadata/history and stage/forecast receipts.
- The requested architecture guide/PDF and all pre-existing uncommitted bug fixes,
  regression tests and supporting documentation, retained locally.
- The latest reviewed release-check and bug-audit fixtures, because packaging and
  existing verification documentation still use them.

No virtual environment, runtime database, model, cache or archive was accidentally
tracked. **No files needed untracking while remaining local.** The ordinary cleanup
commit removes the completed checklist from the current Git tree; previous commits
remain unchanged and history was not purged.

## Verification and scope

Compact receipt: [cleanup_checks.json](evidence/cleanup_checks.json).

| Check | Result | Scope |
| --- | --- | --- |
| Ruff | PASS | Both current checkout and isolated cleanup tree |
| Dependency integrity | PASS | Existing environment; no dependencies changed |
| Retained suite | 135 passed, 0 failed/skipped, 61.357 seconds | Current checkout including pre-existing uncommitted fixes; not a published-code claim |
| Cleanup tree suite | 43 passed, 1 skipped, 0 failed, 26.639 seconds | Original published source plus cleanup changes; skip requires a completed private sealed real build |
| CLI import/help | PASS | Both scopes |
| Demo schema/checksums/keys/arithmetic | PASS | Existing current generation; no export or model run |
| Credential-free dashboard | PASS | AppTest covers all three views and 1-12 horizon control; HTTP/model loading forbidden, external network blocked |
| Documentation references | PASS | Retained local links and documented setup/script/config paths exist; database path corrected to `data/db/gridcast.duckdb` |
| Ignore rules | PASS | Required tests, fixtures/config, demo, screenshots, evidence, SQL and release history remain visible to Git |
| Protected runtime hashes | 14/14 unchanged | Source/features/predictions, model, selection/fit/seal/evaluation, pointers, DuckDB and MLflow SQLite |
| Existing work | Preserved | Source, Snowflake scripts, regression tests, architecture/resume documents and guide/PDF |

Tests used isolated temporary state; CLI demo validation recorded its normal
validation-stage receipt. No historical source
download, model retraining, selection/evaluation rerun, pipeline change, Snowflake
connection, infrastructure or schedule was required for cleanup. Historical
reports keep their original run paths; removed scratch workspaces are recoverable
from the backup, while compact receipts remain at their existing paths.

The isolated cleanup tree was exported from commit
`8b2137243801bada4aad48989080daa9cc5e4cdf` with only the proposed cleanup changes.
It excludes the pre-existing pipeline and test fixes. The [first hosted Ubuntu
run](https://github.com/PuravDesai004/GridCast/actions/runs/38145773653) at that source
commit failed the Windows-drive containment test and skipped its real-seal test.
The separate local fix is not included in this cleanup commit. Local Windows
checks cannot establish a passing Linux workflow; inspect the actual post-push
run before claiming hosted CI success.

Detailed inventory, deletion manifest, before/after protected checksums, JUnit
results and verification logs remain locally under `state/cleanup-review`.
