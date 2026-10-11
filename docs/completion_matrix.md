# Requirement/evidence matrix

Status terms: **V** = implemented and verified by executed local checks; **U** = implemented but unverified externally; **D** = deferred/out of authorized scope. Artifact existence alone is not a check. Paths below are repository-relative; `docs/evidence/index.json` supplies compact artifact SHA-256/size mappings. Runtime seal files preserve exact original hashes. Checks are local Windows unless explicitly labeled otherwise.

| Requirement | Implementation | Executed check / evidence | Status and limitations |
|---|---|---|---|
| Environment inspection, isolated packages, CPU bounds | requirements, pyproject, environment_receipt.py, config | Imports/pip check; `evidence/environment.json`; actual interpreter/OS/RAM/disk receipt | V — Windows3.14; Linux/older interpreters unverified |
| EIA route/facets/unit/interval-end/UTC and calendar | source.py, source_contract.json | Official metadata, two-hour bounds probe, EIA-930 source references in `evidence/source_contract.json` | V — PJM/D/hourly/megawatthours; shift0h |
| Monthly half-open extraction, padding, pagination, totals, retries/auth/facets/bounds/cache | source.py, storage.py | 26 real published windows; source receipt; source contract tests; 429/partial/conflict recovery | V — real2024–2025 plus336+48 valid padding hours |
| Sanitized canonical artifacts; secret-free request logging | util.py, source.py | Redaction tests, hashes stored at publication; `evidence/secret_scan.json` | V — checksums identify sanitized persisted content |
| Typed invalid/zero/extreme/gap handling; no fills | storage.py | `evidence/source_validation.json`, gaps/rejections/revisions.csv, typed contract tests | V —22 invalid gaps retained,0zero/extreme/revision identities observed |
| Separate immutable versions and delivery receipts, A→B→A | storage.py, feature builder | Repeated-delivery/reversion tests and `evidence/recovery.json`, receipt counts | V — prospective correctness is synthetic; real snapshot has0observed revisions |
| Shared26features, timestamp joins, windows/ddof, UTC/DST/offset/fold | features.py, feature_contract.yaml | Contract tests, `worked_origin.csv`, real feature/schema receipt | V — no target lag1/lag24 or target labels in scoring |
| Per-feature/per-horizon availability lineage | features.py, forecasting.py |731training gzip lineage files/index sealed;162,288stored lineage contributions; availability tests | V — compact arrays expand to exact relational grain |
| Strong unavailable-input leakage | features.py, scenarios.py, final_audit.py | `trained_candidate_leakage.json`: actual model mutate/append/delete/reorder; `leakage.json`: after-C revisions/retrospective+prospective | V — full-source hash differs from eligible-input hash |
| Ordinary/gap/DST/stale/revision boundaries | tests, scenarios | Contract pytest and recovery receipts | V — fault injection synthetic, separate from accuracy |
| Global histogram candidate, bounded sequential search and baseline | training.py |12finishedfoldfits,4configs; chosenparams and actual runIDs `selection.json` | V — seed 42, noearlystopping,150iters,2threads |
| Origin membership/label availability/guard/purges | training.py | Fit/fold receipts, `membership_summary.json`, label-purge tests, sealed membershiphash | V — three validation-end origins purged; missinglabels explicit |
| Matched/native coverage, MAE/WAPE/bias/horizon/peak/zero denominator | evaluation.py, training.py, sql | `selection.json`, `test_result.json`, CSVs, metrics tests, independent NumPy reconciliation | V — correlated horizons; no statistical interval claim |
| Fixed validation champion gates | evaluation.py |60.6384%relativeWAPEreduction, peak gate,89/92coverage; zero-denominator/coverage tests | V — candidate selected before test |
| Final fixed pre-test fit; seal/reject change/first receipt | training.py | Seal verified; missing/changed config/artifact tests; originalreceipt retained; dailyhashcheck | V — holdout viewed once; no post-test prediction repair |
| Local SQLite MLflow tracking and actual candidate registry | training.py, releases.py | `evidence/mlflow.json`:13 finished+2failedruns retained, candidateversion1READY; aliasmirrorreceipt | V — local only; baseline has no registryversion |
| Immutable bundle, current pointer, resolve once, rollback | releases.py | Real release validated; failedpromotion/explicitrollback fault checks; pointerhash receipt | V — authoritative release8a4cc72606d13028cbe716c4 |
| Atomic features/lineage/24forecasts/success, attempts/replay/conflicts | forecasting.py, storage.py | Real dailyreplay168 rows unchanged; horizon 12 rollback; changedsource newidentity; recoverycounts | V — UNAVAILABLE zero numericrows |
| Gates, complete seasonal fallback, corrupt-model safe fallback | forecasting.py | Staleanchor/missinglag/corruptbundle cases, tests, `recovery.json` | V — rawcandidate metrics never includefallback |
| Delayed actuals/revisions/error vintages/key+unit/policy | evaluation.py |168realerrors,2actual-revisionerrorvintages inisolatedcase; forecastchecksum unchanged | V — realprospective accuracy collection notrun |
| CLI/config validation/nonzero exits/stage graph/PS runner | cli.py, workflow.py, run_local.ps1 | Realbuild graph, cleanisolatedfixture graph, daily graph, receipts/errors; invalidconfig tests | V — no schedules created |
| Four parameterized SQL analyses/queryhash/scopes/NumPy | sql/, analysis.py | `evidence/analysis.json`, `evidence/sql/*.csv`, reconciliationsPASS | V — measured historical findings, no business savings claims |
| Three credential-free historical views/correct filters | app/, snapshots.py | Browserallviews/screenshots; network/modelblockedAppTest; 1–12filter1,104permodel | V — historical snapshot clearlylabeled |
| Demo manifest containment/checksum/size/schema/key/horizon/unit/time/math | snapshots.py | `demo_validation.json`, tamper/arithmetic/naiveUTC/nonfiniteactualtests; generationvalidated | V — previousgenerationpreserved onfailure |
| Every required recovery and release/source reversion | scenarios.py |18PASS,0pending `recovery.json`; expected/actual/count/hash/identity fields | V — explicitlysyntheticengineering evidence |
| Clean isolated offline workflow | fixture config/splits, workflow | `clean_fixture.json`, freshrootstate/fixture-release-check, fullgraph151.84s | V — syntheticonly, separate real state |
| Dependency checks/Ruff/behavioralpytest | locks, tests, scripts | `pytest-final.xml`, `checks.json`, environmentpipcheck | V — exact localcounts in receipts |
| Linux offline CI | .github/workflows/offline-checks.yml, portablemarkerlock | Workflow prepared; no Linuxinstallation/hostedexecution | U — exact userpush/runverification stepsREADME |
| README/implementedarchitecture/modelcard/findings/teaching | README, architecture.md, docs/*.md | Files inspected against realreceipts; workedrealorigin and definitions | V — proposal preserved separately |
| Resume evidence and honest completionreport | docs/resume_evidence.md, completion_report.md | Claims reconciled with source/fit/validation/test/recovery grains | V — no cloud/prospective/hostedclaim |
| Manual Snowflake setup/load/replay/features/parity | snowflake01–04, user_session.py, export-snowflake | Localexports inspected; PythonASTparse; offlinecomparison logic tests | U — no account/SQL/upload/Snowparkexecution |
| Trusted warehouse registration/batch inference/persistence/outcomes/export/cleanup | snowflake05–07, keyed_candidate.py, guide | Official API references reviewed; ASTparsed; runtimegate/predictionparityprepared | U —3.14/packagecompatibility and usercostpermission checks pending |
| Publication/deployment/backgroundschedules | README instructions only | No push/deploy/scheduler actions | D — requires explicitauthorization |
| Weather/multiauthority/deepmodels/Kafka/Spark/Kubernetes/paidLLMs/Cortex/FastAPI | intentionally outsidecore | No such serviceimplemented orstarted | D — MLflow's installed SDK dependencies do not imply serviceuse |

Real local completion gates are fulfilled. Snowflake, hosted CI, publication, and live prospective evaluation remain explicit separate pending work. Source credentials and runtime databases are excluded from the public-ready Git set.
