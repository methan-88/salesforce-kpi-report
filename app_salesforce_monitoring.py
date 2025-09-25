# app.py
import io
import math
import datetime as dt
import pandas as pd
import plotly.express as px
import streamlit as st

# ========== PAGE CONFIG ==========
st.set_page_config(
    page_title="Salesforce KPI Report",
    page_icon="📊",
    layout="wide"
)

# 🔹 Make sidebar wider with CSS
st.markdown(
    """
    <style>
    [data-testid="stSidebar"] {
        min-width: 350px;
        max-width: 400px;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ========== KPI LABELS (friendly names) ==========
KPI_LABELS = {
    "dq30_pct_unit": "DQ-30 % (Units)",
    "dq30_pct_$": "DQ-30 % (Balance)",
    "dq29_pot30_payment_rate_unit_per_day": "Potential 30DPD Pay Rate (Units · Daily)",
    "dq29_pot30_payment_rate_unit_up_to_day": "Potential 30DPD Pay Rate (Units · Up To Day)",
    "dq29_pot30_payment_rate_$_up_to_day": "Potential 30DPD Pay Rate ($ · Up To Day)",
    "LPE": "Loans per Employee",
    "avg_loan_size": "Average Loan Size",
}
# inverse map for lookups
KPI_LABELS_INV = {v: k for k, v in KPI_LABELS.items()}

# ========== HELPERS ==========
@st.cache_data
def load_excel(path: str) -> pd.DataFrame:
    return pd.read_excel(path)

def bytes_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")

def bytes_xlsx(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="data")
    bio.seek(0)
    return bio.getvalue()

def ensure_datetime(series: pd.Series) -> pd.Series:
    try:
        return pd.to_datetime(series)
    except Exception:
        return series

def fmt_percent(x):
    if pd.isna(x):
        return ""
    return f"{x:.2%}" if (abs(x) < 10) else f"{x:,.2f}%"

def fmt_number(x):
    if pd.isna(x):
        return ""
    return f"{x:,.2f}"

def multiselect_with_select_all(label: str, options, key: str, default_all=True):
    """
    A multi-select UI with 'Select All' and 'Clear' buttons.
    """
    # Normalize to list (sorted for consistency)
    options = list(pd.unique(pd.Series(options)))
    try:
        options.sort()
    except Exception:
        pass

    if key not in st.session_state:
        st.session_state[key] = options if default_all else []

    # Dropdown first
    selected = st.multiselect(
        label,
        options=options,
        default=st.session_state[key],
        key=f"{key}_multi"
    )

    # Buttons stacked under dropdown
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Select All", key=f"{key}_all"):
            st.session_state[key] = options
            selected = options
    with col2:
        if st.button("Clear", key=f"{key}_clear"):
            st.session_state[key] = []
            selected = []

    st.session_state[key] = selected
    return selected

def section_header(title: str, subtitle: str = None):
    st.markdown(f"### {title}")
    if subtitle:
        st.caption(subtitle)

# ========== DATA LOAD ==========
# ========== DATA LOAD ==========
st.title("📊 Salesforce KPI Report")
st.markdown("Performance comparison of **Pre vs Post Go-Live**, with Test vs Control context. Use the filters to explore KPIs across branches and districts.")

with st.sidebar:
    st.header("📁 Data")
    kpi_file = st.file_uploader("KPI Summary (Excel)", type=["xlsx"], key="kpi_file")
    branch_file = st.file_uploader("Branch Summary (Excel)", type=["xlsx"], key="branch_file")
    st.caption("If you don't upload files, the app will look for **KPI_Summary.xlsx**, **Branch_Summary.xlsx**, and **Daily_KPI.xlsx** in the current folder.")

try:
    # Look in current folder if no upload
    kpi_summary = load_excel(kpi_file) if kpi_file else load_excel("KPI_Summary.xlsx")
    branch_summary = load_excel(branch_file) if branch_file else load_excel("Branch_Summary.xlsx")
except Exception as e:
    st.error(f"Could not load data. Please upload the Excel files or place KPI_Summary.xlsx and Branch_Summary.xlsx in this folder.\n\nError: {e}")
    st.stop()

try:
    daily_kpi = load_excel("Daily_KPI.xlsx")
    daily_kpi["CalendarDate"] = pd.to_datetime(daily_kpi["CalendarDate"])
except Exception:
    daily_kpi = pd.DataFrame()
    st.warning("⚠️ No Daily_KPI.xlsx found. KPI-over-time tracking will be disabled.")

# Basic hygiene
for col in ["KPI", "Branch", "District", "Group", "Golive"]:
    if col not in branch_summary.columns:
        st.error(f"`Branch_Summary.xlsx` is missing required column: **{col}**")
        st.stop()
for col in ["KPI", "pval"]:
    if col not in kpi_summary.columns:
        st.warning("`KPI_Summary.xlsx` may not contain all recommended columns (e.g., `pval`). The app will still load.")

# Friendly KPI labels
branch_summary["KPI_Label"] = branch_summary["KPI"].map(KPI_LABELS).fillna(branch_summary["KPI"])
kpi_summary["KPI_Label"] = kpi_summary["KPI"].map(KPI_LABELS).fillna(kpi_summary["KPI"])

# Parse dates
branch_summary["Golive"] = ensure_datetime(branch_summary["Golive"])
branch_summary["Golive_str"] = branch_summary["Golive"].dt.strftime("%Y-%m-%d").fillna("")



def prettify_columns(cols):
    """Return a mapping that replaces underscores with spaces + fixes a few labels."""
    mapping = {}
    for c in cols:
        if c == "KPI_Label":
            mapping[c] = "KPI"
        elif c == "pval":
            mapping[c] = "p-value"
        elif c == "tstat":
            mapping[c] = "t-statistic"
        elif c == "Diff_in_Change":
            mapping[c] = "Difference in Change"
        else:
            mapping[c] = c.replace("_", " ")
    return mapping


# ========== FILTERS ==========
with st.sidebar:
    st.header("🔎 Filters")

    # KPI filter (single select with search; also add a "Top Overview" option)
    all_kpi_labels = sorted(branch_summary["KPI_Label"].unique().tolist())
    kpi_label_choice = st.selectbox("KPI", options=all_kpi_labels, index=0)

    # Build a working frame for the selected KPI
    working = branch_summary.loc[branch_summary["KPI_Label"] == kpi_label_choice].copy()

    # Branch filter
    branches_selected = multiselect_with_select_all(
        "Branch", options=working["Branch"].unique(), key="f_branch"
    )
    # District filter
    districts_selected = multiselect_with_select_all(
        "District", options=working["District"].unique(), key="f_district"
    )
    # Group filter
    groups_selected = multiselect_with_select_all(
        "Group", options=working["Group"].unique(), key="f_group"
    )
    # Go-live filter (use string rep to make selection clearer)
    golive_opts = [g for g in working["Golive_str"].unique() if g != ""]
    golive_selected = multiselect_with_select_all(
        "Go-live Date", options=golive_opts, key="f_golive"
    )

    st.markdown("---")
    st.caption("Tip: Use **Select All** to quickly include everything, or **Clear** to start narrow.")
    st.markdown("---")
    st.caption("Download current views in each section.")

# Apply filters
if len(branches_selected) > 0:
    working = working[working["Branch"].isin(branches_selected)]
if len(districts_selected) > 0:
    working = working[working["District"].isin(districts_selected)]
if len(groups_selected) > 0:
    working = working[working["Group"].isin(groups_selected)]
if len(golive_selected) > 0:
    working = working[working["Golive_str"].isin(golive_selected)]
else:
    # If user clears go-live, include rows with empty golive as well
    pass


import numpy as np
import plotly.graph_objects as go

def plot_kpi_overtime(
    daily_kpi, 
    kpi_label_choice, 
    branches_selected, 
    districts_selected, 
    groups_selected, 
    golive_selected, 
    tab_id=""
):
    """Plots KPI over time (Branch vs Group level) with unique widget keys per tab, now with confidence intervals for group view."""

    # Map exec-friendly label back to internal KPI
    kpi_internal = KPI_LABELS_INV.get(kpi_label_choice, kpi_label_choice)
    daily_filtered = daily_kpi[daily_kpi["KPI"] == kpi_internal].copy()

    # Apply sidebar filters
    if len(branches_selected) > 0:
        daily_filtered = daily_filtered[daily_filtered["Branch"].isin(branches_selected)]
    if len(districts_selected) > 0:
        daily_filtered = daily_filtered[daily_filtered["District"].isin(districts_selected)]
    if len(groups_selected) > 0:
        daily_filtered = daily_filtered[daily_filtered["Group"].isin(groups_selected)]
    if len(golive_selected) > 0:
        daily_filtered = daily_filtered[daily_filtered["Golive"].astype(str).isin(golive_selected)]

    if daily_filtered.empty:
        st.info("No daily data available for this KPI and filter combination.")
        return

    # Sort for rolling
    daily_filtered = daily_filtered.sort_values(["Branch", "CalendarDate"])

    # Compute 7-day rolling average per Branch
    daily_filtered["Rolling7"] = (
        daily_filtered.groupby("Branch")["Value"]
        .transform(lambda x: x.rolling(7, min_periods=1).mean())
    )

    # Toggle: Raw vs Smoothed
    view_choice = st.radio(
        "View Mode",
        options=["7-Day Rolling Average", "Daily Raw Values"],
        index=1,
        horizontal=True,
        key=f"view_mode_{tab_id}_{kpi_label_choice}"
    )
    y_col = "Rolling7" if view_choice == "7-Day Rolling Average" else "Value"

    # Toggle: Branch-level vs Group-level
    view_level = st.radio(
        "Display Mode",
        options=["Branch-Level (many lines)", "Group-Level (Test vs Control only)"],
        index=1,
        horizontal=True,
        key=f"display_mode_{tab_id}_{kpi_label_choice}"
    )

    if view_level == "Branch-Level (many lines)":
        fig = px.line(
            daily_filtered,
            x="CalendarDate",
            y=y_col,
            color="Group",
            line_group="Branch",
            hover_data=["Branch","District","Golive","Value","Rolling7"],
            title=f"{kpi_label_choice} Over Time — Branch-Level ({view_choice})"
        )
    else:
        # --- Compute group mean + CI ---
        daily_grouped = (
            daily_filtered.groupby(["CalendarDate","Group"])
            .agg(
                mean_val=(y_col, "mean"),
                std_val=(y_col, "std"),
                n=("Branch", "nunique")
            )
            .reset_index()
        )
        daily_grouped["stderr"] = daily_grouped["std_val"] / np.sqrt(daily_grouped["n"])
        daily_grouped["ci95"] = 1.96 * daily_grouped["stderr"]
        daily_grouped["y_lower"] = daily_grouped["mean_val"] - daily_grouped["ci95"]
        daily_grouped["y_upper"] = daily_grouped["mean_val"] + daily_grouped["ci95"]

        fig = go.Figure()
        for grp in daily_grouped["Group"].unique():
            sub = daily_grouped[daily_grouped["Group"] == grp]
            # Mean line
            fig.add_trace(go.Scatter(
                x=sub["CalendarDate"], y=sub["mean_val"],
                mode="lines", name=f"{grp} Mean"
            ))
            # Confidence interval band
            fig.add_trace(go.Scatter(
                x=pd.concat([sub["CalendarDate"], sub["CalendarDate"][::-1]]),
                y=pd.concat([sub["y_upper"], sub["y_lower"][::-1]]),
                fill="toself",
                fillcolor="rgba(0,0,255,0.2)" if grp=="Control" else "rgba(255,0,0,0.2)",  # 👈 match line color
                line=dict(color="rgba(255,255,255,0)"),
                hoverinfo="skip",
                showlegend=True,   # 👈 now it appears in legend
                name=f"{grp} 95% CI"
            ))


        fig.update_layout(title=f"{kpi_label_choice} Over Time — Group Average ({view_choice})")

    # Add go-live markers
    for gdate in daily_filtered["Golive"].dropna().unique():
        try:
            gdate_py = pd.to_datetime(gdate).to_pydatetime()
            fig.add_shape(
                type="line",
                x0=gdate_py, x1=gdate_py,
                y0=0, y1=1,
                xref="x", yref="paper",
                line=dict(color="black", dash="dash")
            )
            fig.add_annotation(
                x=gdate_py, y=1, xref="x", yref="paper",
                text=f"Go-live {gdate_py.date()}",
                showarrow=False, yshift=10,
                font=dict(color="black", size=10)
            )
        except Exception as e:
            st.warning(f"⚠️ Could not plot go-live marker for {gdate}: {e}")

    # Finalize and show
    st.plotly_chart(fig, use_container_width=True, key=f"plot_{tab_id}_{kpi_label_choice}")


    # st.plotly_chart(fig, use_container_width=True)

# ========== TABS ==========
tab_overview, tab_kpi, tab_district = st.tabs(["Overview", "KPI Explorer", "District View"])



# ---------- OVERVIEW TAB ----------

# ---------- OVERVIEW TAB ----------
with tab_overview:
    section_header(
        "KPI Overview",
        "How did each KPI move overall? Showing Pre/Post averages, % changes, and statistical tests."
    )

    # Include new percent change columns
    overview_cols = [
        "KPI_Label",
        "Pre_Test_Mean", "Pre_Control_Mean",
        "Post_Test_Mean", "Post_Control_Mean",
        "Change_Test_Mean", "Change_Control_Mean",
        "Diff_in_Change", "%Change_Test", "%Change_Control", "%Change_Diff",
        "Direction",  # 👈 optional, if you want the ↑ / ↓ indicator
        "tstat", "pval", "Significant"
    ]
    present_cols = [c for c in overview_cols if c in kpi_summary.columns]
    overview = kpi_summary[present_cols].copy()

    # Inline rename mapping
    col_map = {
        "KPI_Label": "KPI",
        "Pre_Test_Mean": "Pre Test Mean",
        "Pre_Control_Mean": "Pre Control Mean",
        "Post_Test_Mean": "Post Test Mean",
        "Post_Control_Mean": "Post Control Mean",
        "Change_Test_Mean": "Change Test Mean",
        "Change_Control_Mean": "Change Control Mean",
        "Diff_in_Change": "Difference in Change",
        "%Change_Test": "% Change (Test)",
        "%Change_Control": "% Change (Control)",
        "%Change_Diff": "% Change Difference",
        "Direction": "Direction",
        "tstat": "t-Statistic",
        "pval": "p-Value",
        "Significant": "Statistically Significant?"
    }
    overview_display = overview.rename(columns=col_map)

    # Custom order: LPE and Avg Loan Size first, then others sorted
    priority_kpis = ["Loans per Employee", "Average Loan Size"]
    overview_display["KPI_order"] = overview_display["KPI"].apply(
        lambda x: 0 if x == "Loans per Employee" else (1 if x == "Average Loan Size" else 2)
    )

    if "p-Value" in overview_display.columns:
        overview_display = overview_display.sort_values(
            by=["KPI_order", "p-Value"], ascending=[True, True]
        )
    else:
        overview_display = overview_display.sort_values(by="KPI_order", ascending=True)

    overview_display = overview_display.drop(columns="KPI_order")

    # Display
    st.dataframe(overview_display.reset_index(drop=True), use_container_width=True)


    # Download buttons
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📥 Download KPI Overview (CSV)",
            data=bytes_csv(overview_display),
            file_name="kpi_overview.csv",
            mime="text/csv",
            use_container_width=True
        )
    with c2:
        st.download_button(
            "📥 Download KPI Overview (Excel)",
            data=bytes_xlsx(overview_display),
            file_name="kpi_overview.xlsx",
            use_container_width=True
        )

    # KPI over time (if daily data is available)
    st.markdown("---")
    section_header(f"{kpi_label_choice} Over Time", "Daily KPI values split by Test vs Control (with 7-day rolling average).")

    if not daily_kpi.empty:
        plot_kpi_overtime(
            daily_kpi, 
            kpi_label_choice, 
            branches_selected, 
            districts_selected, 
            groups_selected, 
            golive_selected,
            tab_id="overview"   # 👈 makes widget keys unique
        )

   
# ---------- KPI EXPLORER TAB ----------
with tab_kpi:
    section_header(f"KPI Explorer — {kpi_label_choice}",
                   "Compare Pre vs Post across branches with current filters applied.")

    # Show filtered branch table
    show_cols = [
        "KPI_Label", "Branch", "District", "Group", "Golive",
        "Pre_Mean", "Post_Mean", "Change", "Pre_days", "Post_days", "Pre_N", "Post_N"
    ]
    present_show_cols = [c for c in show_cols if c in working.columns]
    st.dataframe(working[present_show_cols], use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "📥 Download Branch-Level (CSV)",
            data=bytes_csv(working[present_show_cols]),
            file_name=f"branch_{KPI_LABELS_INV.get(kpi_label_choice, kpi_label_choice)}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with c2:
        st.download_button(
            "📥 Download Branch-Level (Excel)",
            data=bytes_xlsx(working[present_show_cols]),
            file_name=f"branch_{KPI_LABELS_INV.get(kpi_label_choice, kpi_label_choice)}.xlsx",
            use_container_width=True
        )

    st.markdown("---")
    section_header(f"{kpi_label_choice} Over Time", "Daily KPI values split by Test vs Control (with 7-day rolling average).")

    if not daily_kpi.empty:
        plot_kpi_overtime(
            daily_kpi, 
            kpi_label_choice, 
            branches_selected, 
            districts_selected, 
            groups_selected, 
            golive_selected,
            tab_id="explorer"   # 👈 unique keys for this tab
        )
   
# ---------- DISTRICT VIEW TAB ----------
with tab_district:
    section_header(f"District View — {kpi_label_choice}",
                   "Aggregated by District x Group, with average Pre/Post and Change.")

    if working.empty:
        st.warning("No rows after filters. Adjust filters to see district view.")
    else:
        group_cols = ["District", "Group", "Golive"]
        agg_map = {
            "Pre_Mean": "mean",
            "Post_Mean": "mean",
            "Change": "mean",
            "Pre_days": "sum",
            "Post_days": "sum",
            "Pre_N": "sum",
            "Post_N": "sum",
        }
        agg_present = {k: v for k, v in agg_map.items() if k in working.columns}
        district_view = working.groupby(group_cols, dropna=False).agg(agg_present).reset_index()

        st.dataframe(district_view, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "📥 Download District View (CSV)",
                data=bytes_csv(district_view),
                file_name=f"district_{KPI_LABELS_INV.get(kpi_label_choice, kpi_label_choice)}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with c2:
            st.download_button(
                "📥 Download District View (Excel)",
                data=bytes_xlsx(district_view),
                file_name=f"district_{KPI_LABELS_INV.get(kpi_label_choice, kpi_label_choice)}.xlsx",
                use_container_width=True
            )

        if "Change" in district_view.columns:
            st.markdown("---")
            section_header("Average Change by District")
            fig3 = px.bar(
                district_view.sort_values(["District", "Group"]),
                x="District", y="Change",
                color="Group",
                hover_data=["Golive", "Pre_days", "Post_days", "Pre_N", "Post_N"],
                title=f"Average Change by District — {kpi_label_choice}"
            )
            st.plotly_chart(fig3, use_container_width=True)

# ---------- FOOTER / DEFINITIONS ----------
with st.expander("ℹ️ Methodology & Definitions"):
    st.markdown("""
- **Pre vs Post**: Compares performance before and after each branch's **Go-live** date.
- **Change**: `Post_Mean − Pre_Mean` at the branch level, then aggregated for district view.
- **Days / N**: `Pre_days` / `Post_days` are unique business days used; `Pre_N` / `Post_N` are total observations included.
- **KPI Labels**: names mapped from internal KPI codes.  
- **Significance (p-value, DiD)**: Provided in *KPI_Summary.xlsx*; lower p-values indicate stronger evidence of a change associated with Go-live, and DiD isolates Test vs Control shifts.
""")

st.caption("© Salesforce KPI Report • Built with Streamlit + Plotly")

