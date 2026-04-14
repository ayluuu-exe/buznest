import streamlit as st
import pandas as pd
from datetime import datetime
import sys, os

# Handle pathing for custom utils
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from utils import inject_theme, check_login, init_connection, page_header
except ImportError:
    # Fallbacks for local environment testing
    def inject_theme(): pass
    def check_login(): pass
    def init_connection(): return None
    def page_header(i, t, s): st.title(f"{i} {t}"); st.write(s)

st.set_page_config(page_title="Data Intake — BuzNet", page_icon="📝", layout="wide")
inject_theme()
check_login()

supabase = init_connection()

# ── GLOBAL DATA LOADER (PAGINATED FOR 26K+ RECORDS) ───────────────────────────
def load_all_data():
    """
    Fetches every record for the current client by iterating through 1,000-row 
    pages to bypass standard cloud API limits.
    """
    all_data = []
    page_size = 1000 
    start = 0
    user = st.session_state.get("username", "demo_user")
    try:
        # Get total count first for progress tracking
        count_res = supabase.table("buznet_data").select("count", count="exact").eq("client_id", user).execute()
        total_count = count_res.count if count_res.count else 0
        
        if total_count == 0:
            return pd.DataFrame()

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
            return df
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error loading records: {e}")
        return pd.DataFrame()

page_header("📝", "Smart Data Intake", "Add, upload, and manage your full dataset (26k+ records)")

tab1, tab2, tab3 = st.tabs(["✍️ Manual Entry", "📁 Bulk CSV Upload", "📋 View & Edit Records"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: MANUAL ENTRY
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.markdown('<div style="font-size:1.25rem; font-weight:bold; margin-bottom:15px;">✍️ Add Single Record</div>', unsafe_allow_html=True)

    with st.form("entry_form", clear_on_submit=True):
        c1, c2 = st.columns(2, gap="large")
        with c1:
            st.markdown("**📅 Record Details**")
            date      = st.date_input("Date", value=datetime.today())
            prod_name = st.text_input("Product Name", placeholder="e.g. Premium Coffee")
            prod_qty  = st.number_input("Production Quantity", min_value=0, step=1)
        with c2:
            st.markdown("**📊 Sales & Revenue**")
            st.markdown("<br>", unsafe_allow_html=True)
            sold_qty = st.number_input("Units Sold", min_value=0, step=1)
            revenue  = st.number_input("Total Revenue (₹)", min_value=0.0, step=0.01, format="%.2f")

        st.markdown("---")
        _, col2, _ = st.columns([1, 2, 1])
        submitted = col2.form_submit_button("💾 Save Record to Cloud", use_container_width=True)

        if submitted:
            if not prod_name:
                st.error("❌ Product Name is required.")
            elif sold_qty > prod_qty and prod_qty > 0:
                st.error("❌ Units Sold cannot exceed Production Quantity.")
            else:
                try:
                    supabase.table("buznet_data").insert({
                        "client_id":  st.session_state.get("username", "demo_user"),
                        "Date":       date.strftime("%Y-%m-%d"),
                        "Product":    prod_name.strip(),
                        "Production": int(prod_qty),
                        "Sold":       int(sold_qty),
                        "Revenue":    float(revenue),
                    }).execute()
                    st.success(f"✅ Record for **{prod_name}** saved successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error saving: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: BULK CSV UPLOAD
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.markdown('<div style="font-size:1.25rem; font-weight:bold; margin-bottom:15px;">📁 Bulk CSV Upload</div>', unsafe_allow_html=True)
    
    template_df = pd.DataFrame({
        "Date": ["2024-01-01"], "Product": ["Widget A"], 
        "Production": [100], "Sold": [80], "Revenue": [8000.00]
    })
    st.download_button("⬇️ Download CSV Template", data=template_df.to_csv(index=False).encode(),
                     file_name="buznet_template.csv", mime="text/csv")

    uploaded = st.file_uploader("📤 Upload your CSV file", type=["csv"])

    if uploaded:
        try:
            df = pd.read_csv(uploaded)
            required = ["Date", "Product", "Production", "Sold", "Revenue"]
            missing = [c for c in required if c not in df.columns]

            if missing:
                st.error(f"❌ Missing columns: {', '.join(missing)}")
            else:
                df = df.drop_duplicates()
                df['Product'] = df['Product'].fillna("Unknown")
                for c in ['Production','Sold','Revenue']:
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df = df.dropna(subset=['Date'])

                st.success(f"✅ Cleaned {len(df)} records.")
                st.dataframe(df.head(5), use_container_width=True)

                if st.button("🚀 Upload All to Cloud", use_container_width=True):
                    with st.spinner("Uploading..."):
                        up_data = df.copy()
                        up_data['Date'] = up_data['Date'].dt.strftime('%Y-%m-%d')
                        up_data['client_id'] = st.session_state.get("username", "demo_user")
                        supabase.table("buznet_data").insert(up_data.to_dict(orient="records")).execute()
                        st.success("✅ Bulk upload complete!")
                        st.rerun()
        except Exception as e:
            st.error(f"❌ Error: {e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: VIEW, EDIT & DELETE
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.markdown('<div style="font-size:1.25rem; font-weight:bold; margin-bottom:15px;">📋 Manage Records</div>', unsafe_allow_html=True)
    
    # 1. Load data recursively
    df = load_all_data()
    
    if df.empty:
        st.info("📭 No records found in your database.")
    else:
        st.markdown(f"**Total Records Synced:** {len(df):,}")
        
        # 2. Date Filtering
        c_filter1, c_filter2 = st.columns([1, 2])
        filter_date = c_filter1.date_input("Step 1: Select Date", value=df['Date'].max())
        date_str = filter_date.strftime("%Y-%m-%d")
        
        # Filter local dataframe
        rdf = df[df['Date'].dt.strftime('%Y-%m-%d') == date_str]

        if rdf.empty:
            st.info(f"No records found for {filter_date.strftime('%d %B %Y')}.")
        else:
            st.dataframe(rdf[['Product', 'Production', 'Sold', 'Revenue']], use_container_width=True)
            st.divider()
            
            # 3. Entry Selection
            st.markdown("### ⚙️ Step 2: Edit or Delete Entry")
            selected_idx = st.selectbox(
                "Select which product entry to modify", 
                options=rdf.index, 
                format_func=lambda x: f"{rdf.loc[x, 'Product']} | Sold: {rdf.loc[x, 'Sold']} | ₹{rdf.loc[x, 'Revenue']:,.0f}"
            )
            
            selected_row = rdf.loc[selected_idx]
            orig_product = selected_row['Product']
            orig_date    = selected_row['Date'].strftime('%Y-%m-%d')
            user_id      = st.session_state.get("username", "demo_user")

            # 4. Action Buttons and Forms
            edit_col, del_col = st.columns([3, 1])
            
            with edit_col:
                st.markdown("**📝 Update Record Details**")
                with st.form("edit_entry_form", clear_on_submit=False):
                    e_c1, e_c2 = st.columns(2)
                    new_p_name = e_c1.text_input("Product Name", value=selected_row['Product'])
                    new_p_date = e_c1.date_input("Date", value=selected_row['Date'])
                    new_p_prod = e_c2.number_input("Production", value=int(selected_row['Production']))
                    new_p_sold = e_c2.number_input("Sold", value=int(selected_row['Sold']))
                    new_p_rev  = st.number_input("Revenue (₹)", value=float(selected_row['Revenue']))
                    
                    if st.form_submit_button("💾 Save Changes", use_container_width=True):
                        try:
                            supabase.table("buznet_data").update({
                                "Product": new_p_name.strip(),
                                "Date": new_p_date.strftime("%Y-%m-%d"),
                                "Production": int(new_p_prod),
                                "Sold": int(new_p_sold),
                                "Revenue": float(new_p_rev)
                            }).eq("client_id", user_id).eq("Date", orig_date).eq("Product", orig_product).execute()
                            
                            st.success("✅ Update successful!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Update failed: {e}")

            with del_col:
                st.markdown("**⚠️ Danger Zone**")
                st.write("Deleting is irreversible.")
                if st.button("🗑️ Delete Record", type="primary", use_container_width=True):
                    try:
                        supabase.table("buznet_data").delete() \
                            .eq("client_id", user_id) \
                            .eq("Date", orig_date) \
                            .eq("Product", orig_product) \
                            .execute()
                        st.warning("✅ Record deleted successfully.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Deletion failed: {e}")

st.markdown("---")
st.caption("BuzNet Intelligence System • Management Module")