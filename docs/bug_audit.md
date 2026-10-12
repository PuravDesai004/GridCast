# Project bug audit — 11 October 2026

Reviewed every Python module in `src/gridcast`, the Streamlit app, CLI/workflows,
manual Snowflake scripts, SQL, local scripts, configuration, dependencies, and
the GitHub Actions workflow. Except for the separately published portable-path
containment fix and its focused tests, fixes remain local and uncommitted.

## Fixed behavior

| Area | Bug and correction |
| --- | --- |
| Source ingestion | Offline cache reuse previously reported success when its database delivery was absent. It now restores checksum-verified cached deliveries with their original fetch ID and collection timestamp. |
| API contracts | Invalid JSON shapes, pagination totals, source timestamps, retry budgets, and hourly bounds now fail through the source error interface. Nonretryable HTTP errors cannot expose credential-bearing request URLs; nonfinite retry delays use bounded backoff. |
| Source history | Earliest-delivery queries now work without a cutoff. Equal-timestamp revisions use delivery order consistently in storage and feature construction. |
| Publication | Invalid staged windows are rejected before raw artifacts are written. Mixed real/fixture validation rejects before replacing frozen evidence. |
| Evidence preservation | Fixture generation, source inspection, feature rebuilding, and backtesting reject sealed/evaluated workspaces before modifying protected artifacts. A missing seal cannot be recreated after viewing the holdout. |
| Configuration | Fixture generation uses the configured random seed. Invalid seed ranges and nonmidnight/duplicate chronological split boundaries reject early. |
| Predictions | Candidate predictions must contain exactly one finite value for each of the 24 horizons. |
| Evaluation | Baseline and candidate comparisons now share the same finite actual/prediction pairs, including peak cohorts. Invalid metric array dimensions reject. Selection receipts describe the configured gates. |
| Analysis | Zero actual denominators and missing matched test targets produce explicit unavailable findings instead of crashing. |
| Seals | Verification now checks the compressed feature lineage files against their sealed receipt, rather than checking only the receipt itself. |
| Forecast replay | Replay verifies persisted forecast rows against the committed checksum, detects changed/deleted rows, and distinguishes intact unavailable output from a nondeterministic new result. |
| Releases | Repeated promotion preserves the rollback target. Invalid champions and missing required checksums reject. Previously promoted manifests must match immutable promotion history, including during rollback. |
| Model cards | New cards describe the configured availability delay and quality gates. |
| Artifact paths | Windows absolute, drive-relative, rooted, UNC, and escaping paths are handled consistently on Windows and Linux. This corrects a platform-dependent failure in the existing containment test. |
| Dashboard snapshots | Readers resolve one atomic generation pointer per load. Generation mismatches, unmatched comparison denominators, malformed peak cohorts, and findings without display text reject. |
| Manual warehouse pilot | Parity receipts are bound to current input hashes; failed reruns clear stale PASS receipts. Empty/invalid identities and predictions reject. Session cleanup closes connections even if suspension fails. The latest-error view follows the selected source revision through A→B→A reversions. |
| Manual export | Export manifests include only generated input artifacts, excluding unrelated/stale client files. The sample has an explicit lower and upper time bound. |
| Tests | The seal contract test builds independent current-code evidence instead of copying the historical real-data seal. Added 91 regression cases across four test files. |

## Verification

- Final complete test suite: **135 passed, 0 failed, 0 skipped**, in 28.73 seconds.
  Receipt: `../GridCast_local/review/bug-audit/pytest-release.xml` (local historical reference).
- Ruff passed for `src app tests scripts snowflake`; `git diff --check` passed.
- `pip check`: no broken requirements; dependency pins were unchanged.
- Fresh offline fixture build completed every stage in 81.48 seconds:
  the historical `state/bug-audit/final-fixture` workspace. Its compact receipts are archived locally; the completed fixture database was removed after verified backup.
- All **18 recovery scenarios passed**, with no pending scenarios.
- Daily replay inserted **zero new forecast rows**, kept database row counts
  unchanged, and preserved the model, selection seal, first evaluation, and test
  result checksums. Receipt: `../GridCast_local/review/bug-audit/daily_validation.json` (local historical reference).
- Streamlit's test runner requires a local socket pair. The complete suite ran
  outside the desktop sandbox after the sandboxed run stalled in Windows socket
  creation; the dashboard test continues to block external network requests.

The existing real-data source, trained model, seals, evaluation receipts, and
published dashboard were preserved. Their historical code fingerprints remain
historical: reproduce changed code in a new workspace rather than replacing the
original seal.

The [first GitHub Actions run](https://github.com/PuravDesai004/GridCast/actions/runs/38145773653)
at `8b21372` failed `test_artifact_containment[C:/absolute/secret]`: 42 passed,
one failed, and one skipped. This was verified subsequently from the preserved
[hosted review](evidence/hosted_ci_review.json) and [JUnit artifact](evidence/pytest-hosted-first.xml).
The [cleanup run](https://github.com/PuravDesai004/GridCast/actions/runs/38151159704)
at `50e93f7` also failed overall. The [follow-up Ubuntu run](https://github.com/PuravDesai004/GridCast/actions/runs/38210511471) at `bf1b3dd` passed all workflow steps: 56 tests passed and one private-real-state skip. See [the follow-up receipt](evidence/hosted_ci_followup.json).
The portable-path containment correction and 13 focused tests are published separately
from the documentation consolidation. Other pipeline fixes remain local; their
historical model accuracy is not reattributed to changed source.
The [cleanup verification receipt](evidence/cleanup_checks.json) independently records
135 local passes and 43 passes/one private-state skip in an isolated published-source
tree. Its timings and code scopes differ from this audit's original receipts.

Snowflake changes were checked with offline tests, including the revised SQL view
against DuckDB; no Snowflake connection or warehouse execution was performed.
