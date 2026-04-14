import streamlit as st
import pandas as pd
import io
import sys, os
from datetime import datetime

# Handle pathing for custom utils
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from utils import inject_theme, check_login, init_connection, page_header
except ImportError:
    # Fallback for local testing
    def inject_theme(): pass
    def check_login(): pass
    def init_connection(): return None
    def page_header(i, t, s): st.title(f"{i} {t}"); st.write(s)

st.set_page_config(page_title="Search & Export — BuzNet", page_icon="🔍", layout="wide")
inject_theme()
check_login()

supabase = init_connection()

# ── DATA LOADING (PAGINATED FOR 26K+ RECORDS) ────────────────────────────────
def load_data():
    """
    Fetches all records for the user by bypassing the 1000-row Supabase limit 
    using recursive range-based pagination.
    """
    all_data = []
    page_size = 5000
    start = 0
    user = st.session_state.get("username", "demo_user")
    
    try:
        with st.spinner(f"📥 Searching Cloud Database"):
            while True:
                res = supabase.table("buznet_data").select("*") \
                    .eq("client_id", user) \
                    .range(start, start + page_size - 1) \
                    .execute()
                
                if not res.data:
                    break
                
                all_data.extend(res.data)
                
                if len(res.data) < page_size:
                    break
                
                start += page_size
        
        if all_data:
            df = pd.DataFrame(all_data)
            df['Date'] = pd.to_datetime(df['Date'])
            for c in ['Production','Sold','Revenue']:
                if c in df.columns: 
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading full dataset: {e}")
        return pd.DataFrame()

def to_excel(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='BuzNet Data')
    return buf.getvalue()

# ── HEADER ───────────────────────────────────────────────────────────────────
page_header("🔍", "Search & Export Data",
            "Advanced filters • Smart search • Full-scale Export to Excel & CSV")

df = load_data()

if df.empty:
    st.markdown("""<div class="bz-card" style="text-align:center;padding:3rem;">
        <div style="font-size:4rem;">🔍</div>
        <h2>No Data Found</h2>
        <p>Add records via Data Intake first to enable search and export.</p>
    </div>""", unsafe_allow_html=True)
    st.stop()

# ── SMART SEARCH ──────────────────────────────────────────────────────────────
st.markdown('<div class="bz-section-title">🔎 Smart Search</div>', unsafe_allow_html=True)

all_products = sorted(df['Product'].unique().tolist())

sc1, sc2 = st.columns([3, 1])
with sc1:
    search_q = st.text_input("Search Products (partial match supported)",
                              placeholder="e.g. 'Alpha', 'Widget', 'Gadget'...")
with sc2:
    if search_q:
        suggestions = [p for p in all_products if search_q.lower() in p.lower()]
        if suggestions:
            st.markdown(f"""
            <div class="bz-card" style="padding:.7rem 1rem;margin-top:.5rem;">
                <div style="font-size:.75rem;color:#2563EB;font-weight:600;margin-bottom:.25rem;">💡 Suggestions</div>
                <div style="font-size:.82rem;color:#374151;">{'  •  '.join(suggestions[:5])}</div>
            </div>""", unsafe_allow_html=True)

# ── ADVANCED FILTERS ──────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="bz-section-title">🎛️ Advanced Filters</div>', unsafe_allow_html=True)

with st.expander("Show / Hide Filters", expanded=True):
    fc1, fc2, fc3 = st.columns(3)

    min_date = df['Date'].min().date()
    max_date = df['Date'].max().date()
    date_range = fc1.date_input("📅 Date Range", value=(min_date, max_date))

    sel_prods = fc2.multiselect("📦 Products", all_products,
                                default=[])

    sort_col = fc3.selectbox("🔃 Sort By", ["Date","Revenue","Sold","Production"])

    min_rev = float(df['Revenue'].min())
    max_rev = float(df['Revenue'].max())
    if min_rev == max_rev: max_rev = min_rev + 1
    rev_range = st.slider("💰 Revenue Range (₹)", min_rev, max_rev,
                          (min_rev, max_rev), format="₹%.0f")

# ── APPLY FILTERS ─────────────────────────────────────────────────────────────
fdf = df.copy()

if isinstance(date_range, tuple) and len(date_range) == 2:
    fdf = fdf[(fdf['Date'].dt.date >= date_range[0]) & (fdf['Date'].dt.date <= date_range[1])]

if sel_prods:
    fdf = fdf[fdf['Product'].isin(sel_prods)]

fdf = fdf[(fdf['Revenue'] >= rev_range[0]) & (fdf['Revenue'] <= rev_range[1])]

if search_q:
    fdf = fdf[fdf['Product'].str.contains(search_q, case=False, na=False)]

fdf = fdf.sort_values(sort_col, ascending=False)

# ── SUMMARY METRICS ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="bz-section-title">📊 Results Summary</div>', unsafe_allow_html=True)

m1, m2, m3, m4 = st.columns(4)
m1.metric("Records Found",   f"{len(fdf):,}")
m2.metric("Total Revenue",   f"₹{fdf['Revenue'].sum():,.0f}")
m3.metric("Units Sold",      f"{fdf['Sold'].sum():,.0f}")
m4.metric("Unique Products", fdf['Product'].nunique())

# ── EXPORT ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="bz-section-title">📥 Export Filtered Data</div>', unsafe_allow_html=True)

export_df = fdf.drop(columns=['client_id','id'], errors='ignore').copy()
export_df['Date'] = export_df['Date'].dt.strftime('%Y-%m-%d')

ec1, ec2, ec3 = st.columns([1, 1, 2])
with ec1:
    st.download_button(
        "⬇️ Download Excel (.xlsx)",
        data=to_excel(export_df),
        file_name="buznet_filtered_export.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True)
with ec2:
    st.download_button(
        "⬇️ Download CSV",
        data=export_df.to_csv(index=False).encode(),
        file_name="buznet_filtered_export.csv",
        mime="text/csv",
        use_container_width=True)
with ec3:
    st.markdown(f"""
    <div class="bz-card" style="padding:.9rem 1.2rem;">
        <span style="color:#6B7280;font-size:.85rem;">
            💡 Ready to export <strong>{len(fdf):,} records</strong> from the total 
            <strong>{len(df):,} entries</strong> currently in your cloud database.
        </span>
    </div>""", unsafe_allow_html=True)

# ── DATA TABLE ────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="bz-section-title">📋 Filtered Records Table</div>', unsafe_allow_html=True)

if fdf.empty:
    st.markdown("""<div class="bz-card" style="text-align:center;padding:2rem;">
        <div style="font-size:2.5rem;">🔍</div>
        <p style="color:#6B7280;">No records match your current filters. Try widening the date or revenue range.</p>
    </div>""", unsafe_allow_html=True)
else:
    st.dataframe(export_df, hide_index=True, use_container_width=True,
                column_config={
                    "Date":       st.column_config.TextColumn("📅 Date"),
                    "Product":    st.column_config.TextColumn("📦 Product"),
                    "Production": st.column_config.NumberColumn("🏭 Produced",  format="%d"),
                    "Sold":       st.column_config.NumberColumn("📊 Sold",      format="%d"),
                    "Revenue":    st.column_config.NumberColumn("💰 Revenue (₹)", format="₹%.2f"),
                })

    st.markdown("---")
    ic1, ic2 = st.columns(2)
    
    # Simple insights based on filtered results
    if not fdf.empty:
        top_p_id = fdf.groupby('Product')['Revenue'].sum().idxmax()
        top_r_val = fdf.groupby('Product')['Revenue'].sum().max()
        ic1.success(f"🏆 **Top Result Product:** {top_p_id} (₹{top_r_val:,.0f})")
        ic2.info(f"📈 **Avg. Value of Filtered Entries:** ₹{fdf['Revenue'].mean():,.2f}")

st.markdown("<br>", unsafe_allow_html=True)
st.markdown("""
<div class="bz-card" style="border-left:4px solid #2563EB;">
    <strong>💡 Search & Export Tips</strong>
    <ul style="margin:.5rem 0 0 1rem;color:#374151;font-size:.88rem;">
        <li>Partial text search — "cof" will match "Premium Coffee" and "Coffee Beans"</li>
        <li>Excel exports include all columns except internal IDs for cleaner reporting</li>
        <li>Combine multiselect and date range for specific month-end comparisons</li>
        <li>The system automatically fetches all 26k+ records from Supabase before filtering</li>
    </ul>
</div>""", unsafe_allow_html=True)

st.caption(f"BuzNet Intelligence Module • Full dataset search enabled ({len(df):,} records)")