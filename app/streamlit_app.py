"""Credential-free historical dashboard. Only small validated snapshot files are read."""

import os
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from gridcast.snapshots import load_demo  # noqa: E402

st.set_page_config(page_title="GridCast | Demand forecast evidence", page_icon="⚡", layout="wide")
st.markdown(
    """<style>
.block-container{padding-top:2rem;max-width:1400px}
[data-testid="stMetric"]{border:1px solid #dce4eb;border-radius:12px;padding:15px}
.eyebrow{font-size:12px;letter-spacing:2px;color:#52778e;font-weight:700}
h1{letter-spacing:-1.5px}
</style>""",
    unsafe_allow_html=True,
)

try:
    demo = load_demo(Path(os.environ.get("GRIDCAST_DEMO_ROOT", PROJECT / "demo")))
except (OSError, ValueError, KeyError) as error:
    st.error(
        f"Snapshot validation failed: {type(error).__name__}. Run export-demo / validate-demo locally."
    )
    st.stop()

manifest, health = demo["manifest"], demo["health"]
st.sidebar.title("⚡ GridCast")
st.sidebar.caption("Demand forecasts · measured evidence")
view = st.sidebar.radio("View", ["Forecast Explorer", "Evaluation", "Reliability & Model Lineage"])
st.sidebar.divider()
st.sidebar.markdown("**HISTORICAL_SNAPSHOT**")
st.sidebar.caption(f"{manifest['kind']} · LOCAL\n\nRelease {manifest['release_id']}")
st.sidebar.caption("PJM demand · megawatthours\n\nAmerica/New_York calendar · UTC identity")
st.markdown(
    '<div class="eyebrow">GRIDCAST / HISTORICAL DEMAND EVIDENCE</div>', unsafe_allow_html=True
)
st.title(view)
st.caption(
    f"HISTORICAL_SNAPSHOT · PJM · MWh (source unit: megawatthours) · release {manifest['release_id']} · "
    f"snapshot generated {manifest['generated_at'][:19]} UTC"
)
if manifest["kind"] != "REAL_EIA":
    st.warning("SYNTHETIC fixture results: engineering demonstration only.")

if view == "Forecast Explorer":
    st.markdown("Inspect one historical 24-hour forecast and its observed demand profile.")
    frame = demo["forecasts"]
    origins = sorted(frame.origin.unique())
    selected = st.selectbox(
        "Forecast origin (UTC)",
        origins,
        format_func=lambda value: pd.Timestamp(value).strftime("%Y-%m-%d 00:00 UTC"),
    )
    group = frame[frame.origin == selected].sort_values("horizon")
    valid = group.actual.notna()
    numerator = abs(group.loc[valid, "prediction"] - group.loc[valid, "actual"]).sum()
    denominator = abs(group.loc[valid, "actual"]).sum()
    st.markdown(f"**Serving policy: {group.serving_path.iloc[0]} · retrospective · 24 hours**")
    columns = st.columns(3)
    columns[0].metric("Paired targets", f"{int(valid.sum())} / 24")
    columns[1].metric(
        "Origin MAE · MWh", f"{numerator / valid.sum():,.1f}" if valid.any() else "Unavailable"
    )
    columns[2].metric(
        "Origin WAPE", f"{100 * numerator / denominator:.2f}%" if denominator else "Unavailable"
    )
    figure = go.Figure()
    for column, label, color, dash in [
        ("actual", "Observed demand", "#8da4ba", None),
        ("prediction", "Locked champion", "#00a5a8", None),
        ("baseline", "Same hour last week", "#f0a24a", "dot"),
    ]:
        figure.add_trace(
            go.Scatter(
                x=group.target,
                y=group[column],
                name=label,
                mode="lines+markers",
                line={"color": color, "width": 3, "dash": dash},
            )
        )
    figure.update_layout(
        height=420,
        margin={"l": 10, "r": 15, "t": 20, "b": 10},
        xaxis_title="Target interval end · UTC",
        yaxis_title="Demand · megawatthours",
        legend={"orientation": "h", "y": 1.1},
        template="plotly_white",
    )
    st.plotly_chart(figure, width="stretch")
    st.caption(
        "Retrospective cutoff: interval end + 3 hours. Observed demand is attached for evaluation after forecasting. Historical forecasts do not represent live service health."
    )
    with st.expander("24 horizon rows and timestamps"):
        st.dataframe(
            group[["horizon", "target", "actual", "prediction", "baseline", "serving_path"]],
            hide_index=True,
            width="stretch",
        )

elif view == "Evaluation":
    a, b = st.columns([1, 3])
    split = a.selectbox("Evaluation period", ["test", "validation"])
    horizon_range = b.slider("Horizon scope (hours)", 1, 24, (1, 24))
    metrics = demo["metrics"]
    scoped = metrics[(metrics.split == split) & metrics.horizon.between(*horizon_range)]
    start, end = (
        (health["test"]["test_start"], health["test"]["test_end_exclusive"])
        if split == "test"
        else (
            health["validation"]["search"][0]["folds"][0]["validation_start"],
            health["validation"]["final_fit_cutoff"],
        )
    )
    st.caption(
        f"Origins {start[:10]} through {end[:10]} exclusive · matched comparisons · horizons {horizon_range[0]}–{horizon_range[1]}"
    )
    for model in ["baseline", "candidate"]:
        rows = scoped[scoped.model == model]
        count = int(rows.paired_targets.sum())
        numerator, denominator = rows.absolute_error_sum.sum(), rows.actual_abs_sum.sum()
        st.markdown(f"**{model.title()} · matched comparison**")
        cols = st.columns(3)
        cols[0].metric("MAE · MWh", f"{numerator / count:,.2f}" if count else "Unavailable")
        cols[1].metric(
            "WAPE", f"{100 * numerator / denominator:.4f}%" if denominator else "Unavailable"
        )
        cols[2].metric("Paired targets", f"{count:,}")
    figure = go.Figure()
    for model, color in [("baseline", "#f0a24a"), ("candidate", "#00a5a8")]:
        rows = scoped[scoped.model == model]
        figure.add_trace(go.Bar(x=rows.horizon, y=rows.mae, name=model, marker_color=color))
    figure.update_layout(
        height=320,
        xaxis_title="Forecast horizon · hours",
        yaxis_title="Matched MAE · MWh",
        template="plotly_white",
        margin={"t": 10, "b": 10},
    )
    st.plotly_chart(figure, width="stretch")
    decision = health["validation"]["decision"]
    st.info(
        f"Validation locked the {decision['champion']} champion. Final-test results do not change that decision. "
        f"Fixed validation paired-origin coverage: {decision['paired_origin_coverage']:.2%}."
    )
    st.caption(
        "MAE and WAPE above recompute from the selected horizon sums. Origin coverage remains the labeled fixed global scope. Raw candidate comparisons contain no fallback predictions."
    )
    with st.expander("Peak demand cohorts by local hour and weekday"):
        peaks = demo["peaks"]
        st.dataframe(peaks[peaks.split == split], hide_index=True)
        st.caption(
            "Fixed training-label 90th percentile defines each fold's peak cohort; final test uses the final fit's threshold. This table keeps its full horizon scope."
        )

else:
    source, fit = health["source"], health["fit"]
    st.caption(
        f"Core source: {source['core_start'][:10]} through {source['core_end'][:10]} exclusive · MWh"
    )
    cols = st.columns(2)
    cols[0].metric("Valid source observations", f"{source['source_rows_current']:,}")
    cols[1].metric("Missing/rejected hours", f"{source['gap_count']:,}")
    cols = st.columns(2)
    cols[0].metric("Candidate registry version", fit["mlflow"]["registry_version"])
    recovery = health["recovery"]
    cols[1].metric("Recovery checks passed", recovery.get("passed", "Pending"))
    st.markdown("**Historical lineage**")
    st.json(
        {
            "core_period": [source["core_start"], source["core_end"]],
            "padded_period": [source["start"], source["end_exclusive"]],
            "source_validated_at": source["at"],
            "source_snapshot": manifest["source_snapshot"],
            "final_fit_cutoff": fit["fit_cutoff"],
            "candidate_run": fit["mlflow"]["run_id"],
            "candidate_model_checksum": fit["model_checksum"],
            "serving_release": manifest["release_id"],
        },
        expanded=False,
    )
    st.caption(
        "MLflow records the trained candidate; releases/current.json selects serving. A baseline champion has no invented MLflow registry version. Recovery fault injections are synthetic engineering evidence."
    )
    if recovery.get("records"):
        st.dataframe(
            pd.DataFrame(recovery["records"])[["scenario", "status"]],
            hide_index=True,
            width="stretch",
        )
    with st.expander("Model card and limitations"):
        st.markdown(demo["model_card"])
    with st.expander("Measured analyst findings"):
        for finding in demo["findings"]["findings"]:
            st.write(finding["text"])
    st.caption(
        "Historical snapshot · no live outages · no API credentials, registry access, model loading, or cloud connection required."
    )
