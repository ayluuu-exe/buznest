import streamlit as st
import pandas as pd
import numpy as np
from datetime import timedelta
import plotly.graph_objects as go
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

# High-Performance ML Engines
from xgboost import XGBRegressor
from catboost import CatBoostRegressor
from lightgbm import LGBMRegressor

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
try:
    from utils import inject_theme, check_login, init_connection, page_header
except ImportError:
    def inject_theme(): pass
    def check_login(): pass
    def init_connection(): return None
    def page_header(i, t, s): st.title(f"{i} {t}"); st.write(s)

st.set_page_config(page_title="BI Predictions — BuzNet", page_icon="🔮", layout="wide")
inject_theme()
check_login()

supabase = init_connection()

# Theme Colors
BLUE, GREEN, AMBER, INDIGO = "#2563EB", "#10B981", "#F59E0B", "#6366F1"

# ── DATA LOADING (OPTIMIZED WITH CACHING) ────────────────────────────────
# Caches the data for 1 hour (3600 seconds) so it doesn't hit Supabase on every slider move
@st.cache_data(ttl=3600, show_spinner=False)
def load_data(user):
    """
    Fetches all records for the user by bypassing the 1000-row Supabase limit 
    using recursive range-based pagination.
    """
    all_data = []
    page_size = 1000 
    start = 0
    
    try:
        # Get total count first
        count_res = supabase.table("buznet_data").select("count", count="exact").eq("client_id", user).execute()
        total_count = count_res.count if count_res.count else 0
        
        if total_count == 0: return pd.DataFrame()

        for start in range(0, total_count, page_size):
            res = supabase.table("buznet_data").select("*") \
                .eq("client_id", user) \
                .range(start, start + page_size - 1) \
                .execute()
            if not res.data: break
            all_data.extend(res.data)
        
        if all_data:
            df = pd.DataFrame(all_data)
            df['Date'] = pd.to_datetime(df['Date'])
            for c in ['Production', 'Sold', 'Revenue']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)
            return df
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame() # Return empty DF on error to avoid breaking UI

# ── ADVANCED FEATURE ENGINEERING ────────────────────────────────────────────
def make_features(df, target_col=None):
    df = df.copy().sort_values('Date')
    df['dayofweek']  = df['Date'].dt.dayofweek
    df['month']      = df['Date'].dt.month
    df['quarter']    = df['Date'].dt.quarter
    df['dayofyear']  = df['Date'].dt.dayofyear
    df['dayofmonth'] = df['Date'].dt.day
    df['is_weekend'] = df['dayofweek'].apply(lambda x: 1 if x >= 5 else 0)
    
    if target_col:
        df['lag_1'] = df[target_col].shift(1)
        df['lag_7'] = df[target_col].shift(7)
        df['rolling_mean_7'] = df[target_col].shift(1).rolling(window=7).mean()
        df = df.bfill()
    return df

FEATURES = ['dayofweek', 'month', 'quarter', 'dayofyear', 'dayofmonth', 'is_weekend', 'lag_1', 'lag_7', 'rolling_mean_7']

page_header("🔮", "High-Accuracy BI Predictions", 
            "Powered by XGBoost, CatBoost, and LightGBM Engines")

# Fetch User Data using the Cached Function
current_user = st.session_state.get("username", "demo_user")
with st.spinner("📥 Synchronising historical data..."):
    df = load_data(current_user)

if df.empty:
    st.warning("No data available. Please add records in Data Intake first.")
    st.stop()

products = sorted(df['Product'].unique())
if not products:
    st.stop()

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
st.markdown('<div class="bz-section-title">📦 Configure Forecast</div>', unsafe_allow_html=True)
sc1, sc2, sc3 = st.columns(3)

selected_product = sc1.selectbox("Select Product", products)
forecast_period  = sc2.selectbox("Time Duration", ["1 Week", "1 Month", "1 Quarter", "1 Year"])

# These sliders are now decoupled from the ML Engine!
safety_pct       = sc3.slider("Safety Stock % (Buffer)", 0, 50, 10)
profit_margin    = st.slider("Profit Margin %", 1, 100, 20)

period_map = {"1 Week": 7, "1 Month": 30, "1 Quarter": 90, "1 Year": 365}
horizon_days = period_map[forecast_period]

p_df = df[df['Product'] == selected_product].sort_values('Date').copy()

if len(p_df) < 15:
    st.warning(f"⚠️ High-accuracy models require a minimum history (15+ records). Current: {len(p_df)}")
    st.stop()

# ── ML PIPELINE (CACHED) ──────────────────────────────────────────────────────

def get_optimized_model(model_type):
    if model_type == "xgb":
        return XGBRegressor(n_estimators=300, learning_rate=0.05, max_depth=6, random_state=42)
    elif model_type == "cat":
        return CatBoostRegressor(iterations=500, learning_rate=0.05, depth=6, verbose=0, random_state=42)
    else:
        return LGBMRegressor(n_estimators=300, learning_rate=0.05, max_depth=6, verbose=-1, random_state=42)

def train_and_forecast(data, target_col, model_type, horizon):
    feat_df = make_features(data, target_col=target_col)
    X = feat_df[FEATURES]
    y = feat_df[target_col]
    use_log = (target_col == 'Revenue')
    if use_log: y = np.log1p(y)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    v_model = get_optimized_model(model_type)
    v_model.fit(X_train, y_train)
    
    preds_v = v_model.predict(X_test)
    y_test_orig = np.expm1(y_test) if use_log else y_test
    preds_orig  = np.expm1(preds_v) if use_log else preds_v
    
    mae = mean_absolute_error(y_test_orig, preds_orig)
    r2  = r2_score(y_test_orig, preds_orig)

    f_model = get_optimized_model(model_type)
    f_model.fit(X, y)

    forecasts = []
    curr_hist = feat_df.copy()
    for _ in range(horizon):
        next_dt = curr_hist['Date'].max() + timedelta(days=1)
        nr = pd.DataFrame({'Date': [next_dt]})
        nr['dayofweek'] = nr['Date'].dt.dayofweek
        nr['month'], nr['quarter'], nr['dayofyear'], nr['dayofmonth'] = nr['Date'].dt.month, nr['Date'].dt.quarter, nr['Date'].dt.dayofyear, nr['Date'].dt.day
        nr['is_weekend'] = nr['dayofweek'].apply(lambda x: 1 if x >= 5 else 0)
        nr['lag_1'] = curr_hist[target_col].iloc[-1]
        nr['lag_7'] = curr_hist[target_col].iloc[-7] if len(curr_hist)>=7 else curr_hist[target_col].iloc[-1]
        nr['rolling_mean_7'] = curr_hist[target_col].tail(7).mean()
        
        p = f_model.predict(nr[FEATURES])[0]
        p_val = max(0, np.expm1(p) if use_log else p)
        forecasts.append(p_val)
        
        nr[target_col] = np.log1p(p_val) if use_log else p_val
        curr_hist = pd.concat([curr_hist, nr], ignore_index=True)

    return np.array(forecasts), {"mae": mae, "r2": r2}

# CACHE THE MASTER PREDICTION FUNCTION
@st.cache_data(show_spinner=False)
def generate_baseline_forecasts(data, horizon):
    """Caches the heavy model training. Only re-runs if data or horizon changes."""
    pred_s, acc_s = train_and_forecast(data, 'Sold', 'xgb', horizon)
    pred_r, acc_r = train_and_forecast(data, 'Revenue', 'cat', horizon)
    pred_p_base, acc_p = train_and_forecast(data, 'Production', 'lgbm', horizon)
    return pred_s, pred_r, pred_p_base, acc_s, acc_r, acc_p

with st.spinner(f"🤖 Processing AI Forecasts for {selected_product}..."):
    # Fetch baseline predictions from cache
    pred_s, pred_r, pred_p_base, acc_s, acc_r, acc_p = generate_baseline_forecasts(p_df, horizon_days)

# ── INSTANT MATH (DECOUPLED FROM UI SLIDERS) ──────────────────────────────────
# Sliders now instantly multiply the cached baseline, avoiding heavy re-training
pred_p = pred_p_base * (1 + safety_pct / 100)

# ── SUMMARY KPIs ──────────────────────────────────────────────────────────────
st.markdown("---")
kc1, kc2, kc3, kc4 = st.columns(4)
total_rev = pred_r.sum()
total_prof = total_rev * (profit_margin / 100)

stats = [
    (kc1, "📈", "Projected Sales", f"{pred_s.sum():,.0f} units", "XGBoost", BLUE),
    (kc2, "💰", "Projected Revenue", f"₹{total_rev:,.0f}", "CatBoost", GREEN),
    (kc3, "🏭", "Prod. Required", f"{pred_p.sum():,.0f} units", f"+{safety_pct}% Buffer", INDIGO),
    (kc4, "💵", "Projected Profit", f"₹{total_prof:,.0f}", f"{profit_margin}% Margin", AMBER)
]

for col, icon, lab, val, tag, clr in stats:
    col.markdown(f"""
    <div style="text-align:center; border-top:4px solid {clr}; padding:15px; background:#f9f9f9; border-radius:10px; height:100%;">
        <div style="font-size:1.8rem;">{icon}</div>
        <div style="color:#666; font-size:0.8rem; text-transform:uppercase;">{lab}</div>
        <div style="font-size:1.2rem; font-weight:bold; color:{clr}; margin:5px 0;">{val}</div>
        <div style="font-size:0.7rem; background:{clr}20; color:{clr}; padding:2px 8px; border-radius:10px; display:inline-block;">{tag}</div>
    </div>""", unsafe_allow_html=True)

# ── TREND CHARTS (SHORT TIMELINE) ─────────────────────────────────────────────
st.markdown("---")
future_dates = [p_df['Date'].max() + timedelta(days=x) for x in range(1, horizon_days + 1)]
hist_d = p_df.sort_values('Date')
short_hist = hist_d.tail(45)

col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.markdown('<div class="bz-section-title">📉 Revenue Forecast (Short-Term view)</div>', unsafe_allow_html=True)
    fig_r = go.Figure()
    fig_r.add_trace(go.Scatter(x=short_hist['Date'], y=short_hist['Revenue'], name='Past Revenue', line=dict(color=GREEN, width=2)))
    fig_r.add_trace(go.Scatter(x=future_dates, y=pred_r, name='Forecasted Revenue', line=dict(color=GREEN, dash='dot', width=3)))
    fig_r.update_layout(hovermode='x unified', height=350, plot_bgcolor='white', margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_r, use_container_width=True)

with col_chart2:
    st.markdown('<div class="bz-section-title">🏭 Production Plan (Short-Term view)</div>', unsafe_allow_html=True)
    fig_p = go.Figure()
    fig_p.add_trace(go.Scatter(x=short_hist['Date'], y=short_hist['Production'], name='Past Production', line=dict(color=INDIGO, width=2)))
    fig_p.add_trace(go.Scatter(x=future_dates, y=pred_p, name='Buffered Plan', line=dict(color=INDIGO, dash='dot', width=3)))
    fig_p.update_layout(hovermode='x unified', height=350, plot_bgcolor='white', margin=dict(l=0, r=0, t=30, b=0))
    st.plotly_chart(fig_p, use_container_width=True)

# ── DETAILED FORECAST TABLE ───────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="bz-section-title">📋 Detailed Forecast Data Table</div>', unsafe_allow_html=True)

f_table = pd.DataFrame({
    "Date": [d.strftime('%Y-%m-%d (%a)') for d in future_dates],
    "Sales Forecast (Units)": [int(x) for x in pred_s],
    "Revenue Forecast (₹)": [f"₹{x:,.2f}" for x in pred_r],
    "Planned Production (Buffered)": [int(x) for x in pred_p],
    "Est. Daily Profit (₹)": [f"₹{x * (profit_margin/100):,.2f}" for x in pred_r]
})

st.dataframe(f_table, use_container_width=True, hide_index=True)
