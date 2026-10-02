import time
import concurrent.futures
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
import streamlit.components.v1 as components

# --- 1. 頁面配置與現代化美化 CSS ---
st.set_page_config(
    page_title="台股智慧選股與即時 K 線診斷系統", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* 全局背景與字體 */
    .main { background-color: #F8FAFC; color: #1E293B; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    /* 側邊欄美化 */
    section[data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E2E8F0; }
    
    /* 卡片容器樣式 */
    .stCard {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        margin-bottom: 20px;
    }
    
    /* 按鈕美化 */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease-in-out;
    }
    
    .stSelectbox, .stSlider, .stNumberInput { margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

# --- 2. 初始化 Session State ---
if 'screener_results' not in st.session_state:
    st.session_state.screener_results = pd.DataFrame()

if 'selected_stock_index' not in st.session_state:
    st.session_state.selected_stock_index = 0

if 'active_combo_name' not in st.session_state:
    st.session_state.active_combo_name = "尚未執行"

if 'watchlist' not in st.session_state:
    st.session_state.watchlist = []

# 預設參數對應 State
default_params = {
    "logic_mode": "OR (符合任一勾選條件即可)",
    "enable_macd_25ma": False, "macd_ma_period": 25,
    "enable_limit_up_pullback": False, "limit_up_days": 20, "limit_up_ma_period": 20,
    "enable_kd_cross": False,
    "enable_tangle_steady": False, "tangle_ma_period": 20,
    "enable_breakout": False,
    "enable_vcp": False,
    "enable_first_limit_pullback": False, "first_limit_days": 30, "first_limit_range": 2.0,
    "enable_shakeout_breakout": False, "shakeout_ma_val": 20,
    "enable_box_breakout": False, "box_days": 20,
    "enable_box_volume_accum": False, "box10_days": 60, "box10_vol_mult": 2.0,
    "enable_box_bottom_support": False, "s11_box_days": 120, "s11_vol_mult": 2.0, "s11_target_ma": "", "s11_limit_days": 60,
    "enable_trend_breakout": True, "s12_lookback": 60, "s12_vol_mult": 1.5,
    # 新增策略 13 & 14 參數預設
    "enable_new_high_breakout": False, "s13_vol_mult": 1.8,
    "enable_suffocation_vol": False, "s14_shrink_days": 3,
    "min_vol": 500, "max_growth": 9.5
}

for k, v in default_params.items():
    if k not in st.session_state:
        st.session_state[k] = v


# --- 3. 資料獲取函式 (加強快取與異常處理) ---
@st.cache_data(ttl=3600, show_spinner=False)
def get_taiwan_stock_list():
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

@st.cache_data(ttl=1800, show_spinner=False)
def get_market_index_data():
    """獲取台股大盤加權指數 (^TWII) 資料"""
    try:
        df = yf.download("^TWII", period="320d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
    except:
        return None


def get_finmind_data(stock_id):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=360)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "end_date": today,
    }
    try:
        response = requests.get(url, params=parameters, timeout=3)
        data = response.json()
        if data.get("status") == 200 and data.get("data"):
            df = pd.DataFrame(data["data"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.rename(columns={
                'open': 'Open', 'max': 'High', 'min': 'Low', 
                'close': 'Close', 'Trading_Volume': 'Volume'
            })
            return df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
    except:
        pass
    
    ticker = f"{stock_id}.TW" if stock_id in twstock.codes and twstock.codes[stock_id].market == "上市" else f"{stock_id}.TWO"
    try:
        df = yf.download(ticker, period="360d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except:
        return None


# --- 4. 繪製美化白色 K 線圖的共用函式 ---
def plot_beautified_chart(df_k, stock_title, ma_num, enable_first_limit=False, first_limit_days=20):
    df_k = df_k.tail(180).copy()
    
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    
    year_high = df_k['High'].max()
    recent_neckline = df_k['High'].iloc[-25:-1].max()

    exp1 = df_k['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df_k['Close'].ewm(span=26, adjust=False).mean()
    df_k['DIF'] = exp1 - exp2
    df_k['MACD_Signal'] = df_k['DIF'].ewm(span=9, adjust=False).mean()
    df_k['MACD_Hist'] = df_k['DIF'] - df_k['MACD_Signal']

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.6, 0.2, 0.2]
    )

    fig.add_trace(plotly_go.Candlestick(
        x=df_k.index, open=df_k['Open'], high=df_k['High'],
        low=df_k['Low'], close=df_k['Close'], name="K線",
        increasing_line_color='#EF5350', decreasing_line_color='#26A69A'
    ), row=1, col=1)

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k[ma_col_name], 
        line=dict(color='#8A2BE2', width=2), 
        name=f"{ma_col_name} (均線)"
    ), row=1, col=1)

    trend_slice = df_k.iloc[-30:].copy()
    fig.add_trace(plotly_go.Scatter(
        x=trend_slice.index, y=trend_slice['Low'],
        line=dict(color='#FFA500', width=2),
        name="最低價趨勢線"
    ), row=1, col=1)

    fig.add_shape(
        type="line", x0=df_k.index[-25], x1=df_k.index[-1],
        y0=recent_neckline, y1=recent_neckline,
        line=dict(color="#FF0000", width=2),
        row=1, col=1
    )
    fig.add_trace(plotly_go.Scatter(
        x=[df_k.index[-1]], y=[recent_neckline],
        mode="text", text=[f" 頸線: {recent_neckline:.2f}"],
        textposition="bottom right", showlegend=False
    ), row=1, col=1)

    df_k['daily_change'] = df_k['Close'].pct_change() * 100
    check_window = df_k.iloc[-first_limit_days:]
    first_limit_idx = None
    for idx, row in check_window.iterrows():
        if row['daily_change'] >= 9.5:
            loc_in_full = df_k.index.get_loc(idx)
            prior_slice = df_k.iloc[max(0, loc_in_full-15):loc_in_full]
            if not (prior_slice['daily_change'] >= 9.5).any():
                first_limit_idx = idx
                break

    if first_limit_idx is not None:
        open_price_val = df_k.loc[first_limit_idx, 'Open']
        fig.add_shape(
            type="line", x0=first_limit_idx, x1=df_k.index[-1],
            y0=open_price_val, y1=open_price_val,
            line=dict(color="#1E90FF", width=2, dash="dash"),
            row=1, col=1
        )

    fig.add_shape(
        type="line", x0=df_k.index[0], x1=df_k.index[-1],
        y0=year_high, y1=year_high,
        line=dict(color="#000000", width=1.5, dash="dash"),
        row=1, col=1
    )

    colors = ['#EF5350' if row['Close'] >= row['Open'] else '#26A69A' for _, row in df_k.iterrows()]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['Volume'] / 1000, 
        marker_color=colors, name="成交量(張)"
    ), row=2, col=1)

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['DIF'], line=dict(color='#2196F3', width=1.5), name="DIF"
    ), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['MACD_Signal'], line=dict(color='#FF9800', width=1.5), name="MACD"
    ), row=3, col=1)
    
    macd_colors = ['#EF5350' if val >= 0 else '#26A69A' for val in df_k['MACD_Hist']]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['MACD_Hist'], marker_color=macd_colors, name="MACD Histogram"
    ), row=3, col=1)

    fig.update_layout(
        title=dict(text=f"<b>{stock_title}</b> - 180天歷史日線圖", font=dict(size=14, color="#1E293B")),
        template="plotly_white",
        height=600,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


# --- 5. 策略運算與分析核心 (支援 1~14 策略) ---
def fetch_and_analyze_single_stock(row):
    sid = row['code']
    df = get_finmind_data(sid)
    required_len = max(
        st.session_state.box_days, 
        st.session_state.box10_days, 
        st.session_state.s11_box_days, 
        st.session_state.s12_lookback, 
        260 # 52週約250交易日
    ) + 10
    
    if df is None or len(df) < required_len:
        return None
        
    df = df.dropna(subset=['Close'])
    curr_price = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2] if len(df) > 1 else curr_price
    curr_vol = df['Volume'].iloc[-1]

    if curr_vol < (st.session_state.min_vol * 1000): return None
    change_pct = ((curr_price - prev_close) / prev_close) * 100
    if change_pct > st.session_state.max_growth: return None

    df['daily_change'] = df['Close'].pct_change() * 100
    recent_df = df.iloc[-60:]
    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

    matched_strategies = []

    # 策略 1
    if st.session_state.enable_macd_25ma:
        df['ma_a'] = df['Close'].rolling(st.session_state.macd_ma_period).mean()
        ma_a_curr = df['ma_a'].iloc[-1]
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        signal = dif.ewm(span=9, adjust=False).mean()
        
        cond_ma = (df['Low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
        cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
        if cond_ma and cond_macd:
            matched_strategies.append("MACD回踩0軸")

    # 策略 2
    if st.session_state.enable_limit_up_pullback:
        df['ma_b'] = df['Close'].rolling(st.session_state.limit_up_ma_period).mean()
        ma_b_curr = df['ma_b'].iloc[-1]
        df['vol_ma5'] = df['Volume'].rolling(5).mean()
        
        check_range = df.iloc[-st.session_state.limit_up_days:]
        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['Volume'] > check_range['vol_ma5'] * 1.5)).any()
        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
        is_touch_ma = (df['Low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
        
        if had_limit_up_vol and is_vol_shrink and is_touch_ma:
            matched_strategies.append("漲停回踩MA")

    # 策略 3
    if st.session_state.enable_kd_cross:
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        if (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]):
            matched_strategies.append("KD金叉")

    # 策略 4
    if st.session_state.enable_tangle_steady:
        ma5 = df['Close'].rolling(5).mean()
        ma10 = df['Close'].rolling(10).mean()
        ma20 = df['Close'].rolling(st.session_state.tangle_ma_period).mean()
        
        ma_max = pd.concat([ma5, ma10, ma20], axis=1).max(axis=1)
        ma_min = pd.concat([ma5, ma10, ma20], axis=1).min(axis=1)
        is_tangled = ((ma_max - ma_min) / ma_min < 0.025).iloc[-5:-1].any()
        
        vol_ma = df['Volume'].rolling(5).mean()
        is_vol_steady = df['Volume'].iloc[-5:-1].mean() < vol_ma.iloc[-1] * 1.3
        is_price_shrink = df['Close'].iloc[-1] <= df['Close'].iloc[-5] * 1.05
        
        if is_tangled and is_vol_steady and is_price_shrink:
            matched_strategies.append("均線糾結+量穩價縮")

    # 策略 5
    if st.session_state.enable_breakout:
        vol_ma = df['Volume'].rolling(5).mean()
        is_breakout = (curr_price > df['High'].iloc[-25:-1].max()) and (curr_vol > vol_ma.iloc[-1] * 1.2)
        if is_breakout:
            matched_strategies.append("突破切線")

    # 策略 6
    if st.session_state.enable_vcp:
        h1 = df['High'].iloc[-30:-15].max() - df['Low'].iloc[-30:-15].min()
        h2 = df['High'].iloc[-15:].max() - df['Low'].iloc[-15:].min()
        v1 = df['Volume'].iloc[-30:-15].mean()
        v2 = df['Volume'].iloc[-15:].mean()
        
        is_vcp_contraction = (h2 < h1) and (v2 < v1)
        if is_vcp_contraction:
            matched_strategies.append("VCP波動收縮")

    # 策略 7
    if st.session_state.enable_first_limit_pullback:
        check_window = df.iloc[-st.session_state.first_limit_days:]
        first_limit_open = None
        for idx, r in check_window.iterrows():
            if r['daily_change'] >= 9.5:
                loc_in_full = df.index.get_loc(idx)
                prior_slice = df.iloc[max(0, loc_in_full-15):loc_in_full]
                if not (prior_slice['daily_change'] >= 9.5).any():
                    first_limit_open = r['Open']
                    break
        
        if first_limit_open is not None:
            vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
            is_vol_shrink = curr_vol < vol_ma5
            lower_bound = first_limit_open * (1 - st.session_state.first_limit_range / 100.0)
            upper_bound = first_limit_open * (1 + st.session_state.first_limit_range / 100.0)
            is_near_open = (df['Low'].iloc[-1] <= upper_bound) and (curr_price >= lower_bound)
            
            if is_vol_shrink and is_near_open:
                matched_strategies.append("首根漲停開盤價支撐")

    # 策略 8
    if st.session_state.enable_shakeout_breakout:
        m_val = st.session_state.shakeout_ma_val
        df[f'shk_ma'] = df['Close'].rolling(m_val).mean()
        vol_ma_20 = df['Volume'].rolling(20).mean().iloc[-1]
        is_volume_expand = curr_vol > vol_ma_20 * 1.3
        
        recent_vol_slice = df['Volume'].iloc[-15:-1]
        is_prior_shrink = (recent_vol_slice.min() < vol_ma_20 * 0.8)
        
        is_first_day_above_ma = (df['Close'].iloc[-1] >= df[f'shk_ma'].iloc[-1]) and (df['Close'].iloc[-2] <= df[f'shk_ma'].iloc[-2])
        
        if is_prior_shrink and is_volume_expand and is_first_day_above_ma:
            matched_strategies.append(f"量縮洗盤後出量站上MA{m_val}")

    # 策略 9
    if st.session_state.enable_box_breakout:
        b_days = st.session_state.box_days
        box_high = df['High'].iloc[-(b_days + 1):-1].max()
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_break_box = (curr_price >= box_high) and (df['Close'].iloc[-2] < box_high)
        is_box_volume_expand = curr_vol > (vol_ma5 * 1.5)
        
        if is_break_box and is_box_volume_expand:
            matched_strategies.append(f"帶量突破箱型高點({b_days}日)")

    # 策略 10
    if st.session_state.enable_box_volume_accum:
        b10_days = st.session_state.box10_days
        box_window = df.iloc[-(b10_days + 1):-1]
        b_high = box_window['High'].max()
        b_low = box_window['Low'].min()
        
        is_inside_box = (curr_price < b_high) and (curr_price > b_low)
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_surge_volume = curr_vol > (vol_ma5 * st.session_state.box10_vol_mult)
        
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma10 = df['Close'].rolling(10).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        is_above_all_mas = (curr_price >= ma5) and (curr_price >= ma10) and (curr_price >= ma20)
        
        if is_inside_box and is_surge_volume and is_above_all_mas:
            matched_strategies.append(f"箱型爆大量站穩均線未破頂({b10_days}日)")

    # 策略 11
    if st.session_state.enable_box_bottom_support:
        s11_d = st.session_state.s11_box_days
        s11_box_window = df.iloc[-(s11_d + 1):-1]
        s11_b_high = s11_box_window['High'].max()
        s11_b_low = s11_box_window['Low'].min()
        box_range_val = s11_b_high - s11_b_low
        
        is_at_box_bottom = (curr_price >= s11_b_low) and (curr_price <= s11_b_low + box_range_val * 0.20)
        ma120 = df['Close'].rolling(120).mean().iloc[-1]
        ma240 = df['Close'].rolling(240).mean().iloc[-1]
        is_long_bull = ma120 > ma240
        
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_s11_surge = curr_vol > (vol_ma5 * st.session_state.s11_vol_mult)
        
        standing_mas = []
        for m_val in [60, 20, 10, 5]:
            m_val_calc = df['Close'].rolling(m_val).mean().iloc[-1]
            if curr_price >= m_val_calc:
                standing_mas.append(f"MA{m_val}")
        
        target_m = st.session_state.s11_target_ma
        is_match_target_ma = target_m in standing_mas if target_m else len(standing_mas) > 0
        s11_recent_window = df.iloc[-st.session_state.s11_limit_days:]
        had_recent_limit = (s11_recent_window['daily_change'] >= 9.5).any()
        
        if is_at_box_bottom and is_long_bull and is_s11_surge and is_match_target_ma and had_recent_limit:
            ma_str_label = "+".join(standing_mas) if standing_mas else "無"
            matched_strategies.append(f"箱底爆大量站穩均線[{ma_str_label}]({s11_d}日)")

    # 策略 12
    if st.session_state.enable_trend_breakout:
        lookback_d = st.session_state.s12_lookback
        hist_df = df.iloc[-lookback_d:-1]
        if len(hist_df) >= 20:
            low_idx1 = hist_df['Low'].idxmin()
            remaining_lows = hist_df.drop(hist_df.loc[max(hist_df.index[0], low_idx1 - pd.Timedelta(days=5)):min(hist_df.index[-1], low_idx1 + pd.Timedelta(days=5))].index)
            if not remaining_lows.empty:
                low_idx2 = remaining_lows['Low'].idxmin()
                p1_x = (low_idx1 - hist_df.index[0]).days
                p1_y = df.loc[low_idx1, 'Low']
                p2_x = (low_idx2 - hist_df.index[0]).days
                p2_y = df.loc[low_idx2, 'Low']
                curr_x = (df.index[-1] - hist_df.index[0]).days
                support_line_val = (p1_y + ((p2_y - p1_y) / (p2_x - p1_x)) * (curr_x - p1_x)) if p2_x != p1_x else p1_y
                is_basing = curr_price >= support_line_val * 0.98
                
                high_idx1 = hist_df['High'].idxmax()
                remaining_highs = hist_df.drop(hist_df.loc[max(hist_df.index[0], high_idx1 - pd.Timedelta(days=5)):min(hist_df.index[-1], high_idx1 + pd.Timedelta(days=5))].index)
                if not remaining_highs.empty:
                    high_idx2 = remaining_highs['High'].idxmax()
                    hp1_x = (high_idx1 - hist_df.index[0]).days
                    hp1_y = df.loc[high_idx1, 'High']
                    hp2_x = (high_idx2 - hist_df.index[0]).days
                    hp2_y = df.loc[high_idx2, 'High']
                    resistance_line_val = (hp1_y + ((hp2_y - hp1_y) / (hp2_x - hp1_x)) * (curr_x - hp1_x)) if hp2_x != hp1_x else hp1_y
                    is_breaking = curr_price > resistance_line_val and df['Close'].iloc[-2] <= resistance_line_val
                    
                    vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
                    is_volume_surge = curr_vol > (vol_ma5 * st.session_state.s12_vol_mult)
                    
                    ma5_v = df['Close'].rolling(5).mean().iloc[-1]
                    ma20_v = df['Close'].rolling(20).mean().iloc[-1]
                    ma60_v = df['Close'].rolling(60).mean().iloc[-1]
                    is_above_all = (curr_price > ma5_v) and (curr_price > ma20_v) and (curr_price > ma60_v)
                    
                    dist_ma5 = abs(curr_price - ma5_v) / ma5_v
                    dist_ma20 = abs(curr_price - ma20_v) / ma20_v
                    dist_ma60 = abs(curr_price - ma60_v) / ma60_v
                    is_within_10pct = (dist_ma5 <= 0.10) and (dist_ma20 <= 0.10) and (dist_ma60 <= 0.10)
                    is_pct_gt_2 = change_pct >= 2.0
                    
                    if is_basing and is_breaking and is_volume_surge and is_above_all and is_within_10pct and is_pct_gt_2:
                        matched_strategies.append("12.突破均線糾結(趨勢突破+帶量)")

    # 策略 13：量能爆發且突破 52 週新高
    if st.session_state.enable_new_high_breakout:
        if len(df) >= 250:
            high_52w = df['High'].iloc[-250:-1].max()
            vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
            is_new_high = curr_price >= high_52w
            is_surge = curr_vol > (vol_ma5 * st.session_state.s13_vol_mult)
            if is_new_high and is_surge:
                matched_strategies.append("13.量能爆發突破52週新高")

    # 策略 14：連續數日量縮無賣壓（窒息量）
    if st.session_state.enable_suffocation_vol:
        shrink_d = st.session_state.s14_shrink_days
        if len(df) >= shrink_d + 10:
            vol_ma20 = df['Volume'].rolling(20).mean().iloc[-1]
            recent_vols = df['Volume'].iloc[-(shrink_d):]
            # 連續數日成交量低於月均量 60%，且股價沒大幅下跌
            is_low_vol = (recent_vols < vol_ma20 * 0.6).all()
            price_change_recent = (df['Close'].iloc[-1] - df['Close'].iloc[-shrink_d]) / df['Close'].iloc[-shrink_d] * 100
            is_stable_price = abs(price_change_recent) < 4.0 # 價格波動小於4%代表無賣壓
            if is_low_vol and is_stable_price:
                matched_strategies.append(f"14.連續{shrink_d}日量縮無賣壓(窒息量)")

    total_enabled_flags = sum([
        st.session_state.enable_macd_25ma, st.session_state.enable_limit_up_pullback, 
        st.session_state.enable_kd_cross, st.session_state.enable_tangle_steady, 
        st.session_state.enable_breakout, st.session_state.enable_vcp, 
        st.session_state.enable_first_limit_pullback, st.session_state.enable_shakeout_breakout, 
        st.session_state.enable_box_breakout, st.session_state.enable_box_volume_accum, 
        st.session_state.enable_box_bottom_support, st.session_state.enable_trend_breakout,
        st.session_state.enable_new_high_breakout, st.session_state.enable_suffocation_vol
    ])
    if total_enabled_flags == 0:
        return None

    if st.session_state.logic_mode == "AND (所有勾選條件皆需成立)":
        if len(matched_strategies) < total_enabled_flags: return None
    else: 
        if len(matched_strategies) == 0: return None

    combo_label = " + ".join(matched_strategies)
    return {
        "股票代號": sid,
        "股票名稱": row['name'],
        "組合邏輯名稱": combo_label,
        "當日漲幅(%)": round(change_pct, 2),
        "近N日漲停次數": int(limit_up_count),
        "成交量(張)": int(curr_vol / 1000),
        "收盤價": round(curr_price, 2)
    }


# --- 6. 具備多執行緒加速的掃描函式 ---
def run_quick_screener_concurrent():
    df_stocks = get_taiwan_stock_list()
    found_targets = []
    total_count = len(df_stocks)
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    completed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fetch_and_analyze_single_stock, row): row for _, row in df_stocks.iterrows()}
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 20 == 0 or completed == total_count:
                progress_bar.progress(min(completed / total_count, 1.0))
                status_text.markdown(f"🔍 **平行掃描進度:** `{completed}/{total_count}` | 🔥 **符合:** `{len(found_targets)}` 檔")
            
            res = future.result()
            if res:
                found_targets.append(res)
                
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# --- 7. 快捷組合設定函式 ---
def apply_combo_1():
    st.session_state.logic_mode = "OR (符合任一勾選條件即可)"
    for k in default_params:
        if k.startswith("enable_"):
            st.session_state[k] = False
    st.session_state.enable_new_high_breakout = True
    st.session_state.s13_vol_mult = 1.8
    st.session_state.enable_trend_breakout = True
    st.session_state.min_vol = 800
    st.session_state.max_growth = 9.5
    st.session_state.active_combo_name = "【組合一：52週新高與飆股爆發型】"

def apply_combo_2():
    st.session_state.logic_mode = "OR (符合任一勾選條件即可)"
    for k in default_params:
        if k.startswith("enable_"):
            st.session_state[k] = False
    st.session_state.enable_suffocation_vol = True
    st.session_state.s14_shrink_days = 3
    st.session_state.enable_limit_up_pullback = True
    st.session_state.min_vol = 800
    st.session_state.max_growth = 9.5
    st.session_state.active_combo_name = "【組合二：窒息量縮與回檔低接型】"


# ==========================================
# 8. 左側控制台介面設計
# ==========================================
with st.sidebar:
    st.title("📈 策略控制面板")
    st.caption("多執行緒高速平行掃描引擎")
    st.divider()

    st.session_state.logic_mode = st.radio(
        "🔀 篩選組合邏輯", 
        ["OR (符合任一勾選條件即可)", "AND (所有勾選條件皆需成立)"],
        index=0 if st.session_state.logic_mode.startswith("OR") else 1,
    )
    st.divider()

    with st.expander("📌 技術指標與基礎策略 (1~6)"):
        st.session_state.enable_macd_25ma = st.checkbox("1. MACD回踩0軸+MA支援", value=st.session_state.enable_macd_25ma)
        st.session_state.macd_ma_period = st.number_input("MACD搭配均線數值", min_value=1, max_value=240, value=st.session_state.macd_ma_period)

        st.session_state.enable_limit_up_pullback = st.checkbox("2. 漲停回踩MA", value=st.session_state.enable_limit_up_pullback)
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.session_state.limit_up_days = st.number_input("前N天 (策略2)", min_value=1, max_value=60, value=st.session_state.limit_up_days)
        with col_p2:
            st.session_state.limit_up_ma_period = st.number_input("回踩MA (策略2)", min_value=1, max_value=240, value=st.session_state.limit_up_ma_period)

        st.session_state.enable_kd_cross = st.checkbox("3. KD金叉", value=st.session_state.enable_kd_cross)
        st.session_state.enable_tangle_steady = st.checkbox("4. 均線糾結+量穩價縮", value=st.session_state.enable_tangle_steady)
        st.session_state.enable_breakout = st.checkbox("5. 突破切線", value=st.session_state.enable_breakout)
        st.session_state.enable_vcp = st.checkbox("6. VCP波動收縮", value=st.session_state.enable_vcp)

    with st.expander("📦 箱型與量價突破策略 (7~11)"):
        st.session_state.enable_first_limit_pullback = st.checkbox("7. 首根漲停開盤價支撐", value=st.session_state.enable_first_limit_pullback)
        st.session_state.enable_shakeout_breakout = st.checkbox("8. 量縮洗盤後出量站上MA", value=st.session_state.enable_shakeout_breakout)
        st.session_state.enable_box_breakout = st.checkbox("9. 帶量突破箱型高點", value=st.session_state.enable_box_breakout)
        st.session_state.enable_box_volume_accum = st.checkbox("10. 箱型爆大量站穩均線", value=st.session_state.enable_box_volume_accum)
        st.session_state.enable_box_bottom_support = st.checkbox("11. 箱底爆大量長均多頭", value=st.session_state.enable_box_bottom_support)

    with st.expander("🔥 核心熱門與新版實戰策略 (12~14)"):
        st.session_state.enable_trend_breakout = st.checkbox("12. 突破均線糾結(趨勢突破)", value=st.session_state.enable_trend_breakout)
        st.session_state.enable_new_high_breakout = st.checkbox("13. 量能爆發突破52週新高", value=st.session_state.enable_new_high_breakout)
        st.session_state.s13_vol_mult = st.number_input("52週新高爆量倍數", min_value=1.1, max_value=5.0, value=st.session_state.s13_vol_mult, step=0.1)

        st.session_state.enable_suffocation_vol = st.checkbox("14. 連續數日量縮無賣壓(窒息量)", value=st.session_state.enable_suffocation_vol)
        st.session_state.s14_shrink_days = st.number_input("窒息量持續天數", min_value=2, max_value=10, value=st.session_state.s14_shrink_days)

    st.divider()
    st.session_state.min_vol = st.number_input("成交量大於 (張)", value=st.session_state.min_vol, step=100)
    st.session_state.max_growth = st.number_input("當日漲幅小於 (%)", value=st.session_state.max_growth, step=0.5)

    btn_quick_search = st.button("🚀 執行多執行緒自訂挖掘", use_container_width=True, type="primary")


# ==========================================
# 9. 右側主畫面區塊
# ==========================================
st.title("📈 台股智慧選股與即時 K 線診斷系統")
st.markdown(f"**目前方案模式：** `{st.session_state.active_combo_name}`")
st.caption("支援多執行緒高速平行運算、52週新高突破、窒息量縮無賣壓與自選股追蹤管理。")
st.divider()

# --- 9.1 大盤即時監測 ---
st.subheader("📊 盤勢即時監測（加權指數 ^TWII）")
with st.spinner("正在獲取台股大盤最新行情..."):
    df_market = get_market_index_data()
    if df_market is not None and not df_market.empty:
        m_curr_close = df_market['Close'].iloc[-1]
        df_market['MA20'] = df_market['Close'].rolling(20).mean()
        df_market['MA120'] = df_market['Close'].rolling(120).mean()
        m_ma20 = df_market['MA20'].iloc[-1]
        m_ma120 = df_market['MA120'].iloc[-1]
        
        if m_curr_close >= m_ma20:
            st.success("🟢 **大盤狀態：月線之上（多頭偏多）** -> 適合積極執行 52週新高突破與強勢追價策略。")
        elif m_curr_close < m_ma120:
            st.warning("🔴 **大盤狀態：季線之下（弱勢盤勢）** -> 建議縮手，或僅關注窒息量縮與箱底低接標的。")
        else:
            st.info("🟡 **大盤狀態：月線與季線之間（震盪盤整）** -> 建議精選個股，嚴設停損。")
            
        fig_market = plot_beautified_chart(df_market, "台股大盤加權指數 (^TWII)", 20, enable_first_limit=False)
        st.plotly_chart(fig_market, use_container_width=True)
    else:
        st.warning("⚠️ 無法取得大盤指數數據。")

st.divider()

# --- 9.2 快捷一鍵掃描按鈕 ---
st.subheader("🔥 實戰策略一鍵快速生成方案")
col_b1, col_b2 = st.columns(2)
with col_b1:
    if st.button("🚀 組合一：【52週新高與飆股爆發型】", use_container_width=True, type="primary"):
        apply_combo_1()
        with st.spinner("⚡ 多執行緒高速掃描中..."):
            st.session_state.screener_results = run_quick_screener_concurrent()
            st.session_state.selected_stock_index = 0
        st.rerun()
with col_b2:
    if st.button("🛡️ 組合二：【窒息量縮與回檔低接型】", use_container_width=True, type="secondary"):
        apply_combo_2()
        with st.spinner("⚡ 多執行緒高速掃描中..."):
            st.session_state.screener_results = run_quick_screener_concurrent()
            st.session_state.selected_stock_index = 0
        st.rerun()

st.divider()

if btn_quick_search:
    st.session_state.active_combo_name = "【自訂策略組合】"
    with st.spinner("⚡ 多執行緒高速掃描全市場..."):
        st.session_state.screener_results = run_quick_screener_concurrent()
        st.session_state.selected_stock_index = 0

res_table = st.session_state.screener_results

# --- 9.3 標籤頁導覽 (增加自選股追蹤清單) ---
tab1, tab2, tab3, tab4 = st.tabs(["📋 篩選結果清單", "📈 K 線圖互動瀏覽", "⭐ 自選股追蹤清單", "🩺 個股技術即時診斷"])

with tab1:
    st.subheader(f"📋 篩選結果清單 — {st.session_state.active_combo_name}")
    if not res_table.empty:
        st.success(f"🎉 掃描完成！共找到 `{len(res_table)}` 檔符合條件的優質標的：")
        
        display_df = res_table.copy()
        display_df['WantGoo連結'] = display_df.apply(
            lambda r: f"https://www.wantgoo.com/stock/{r['股票代號']}/technical-chart", axis=1
        )
        cols_to_show = ["股票代號", "股票名稱", "WantGoo連結", "組合邏輯名稱", "當日漲幅(%)", "近N日漲停次數", "成交量(張)", "收盤價"]
        st.dataframe(
            display_df[cols_to_show],
            column_config={
                "WantGoo連結": st.column_config.LinkColumn("技術分析圖表", display_text="點擊開啟")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("👈 點擊上方主畫面的 **【🚀 組合一】** 或 **【🛡️ 組合二】** 按鈕，即可快速啟動多執行緒掃描！")

with tab2:
    st.subheader("📈 詳細美化 K 線圖與快速瀏覽 (支援左右按鈕與自選股加入)")
    if not res_table.empty:
        stock_list = res_table["股票代號"].tolist()
        total_stocks = len(stock_list)

        if st.session_state.selected_stock_index >= total_stocks:
            st.session_state.selected_stock_index = total_stocks - 1
        if st.session_state.selected_stock_index < 0:
            st.session_state.selected_stock_index = 0

        col_btn1, col_sel, col_btn2 = st.columns([1, 4, 1])
        with col_btn1:
            if st.button("⬅️ 上一檔", use_container_width=True, key="btn_prev_stock"):
                if st.session_state.selected_stock_index > 0:
                    st.session_state.selected_stock_index -= 1
                    st.rerun()

        with col_btn2:
            if st.button("下一檔 ➡️", use_container_width=True, key="btn_next_stock"):
                if st.session_state.selected_stock_index < total_stocks - 1:
                    st.session_state.selected_stock_index += 1
                    st.rerun()

        with col_sel:
            selected_stock = st.selectbox(
                "請選擇欲檢視的股票代號",
                options=stock_list,
                index=st.session_state.selected_stock_index,
                format_func=lambda x: f"({stock_list.index(x)+1}/{total_stocks}) {x} - {res_table[res_table['股票代號']==x]['股票名稱'].values[0]}",
                key="selectbox_stock_changer"
            )
            if selected_stock in stock_list:
                new_idx = stock_list.index(selected_stock)
                if new_idx != st.session_state.selected_stock_index:
                    st.session_state.selected_stock_index = new_idx
                    st.rerun()

        if selected_stock:
            r_row = res_table[res_table['股票代號']==selected_stock].iloc[0]
            
            # 自選股加入/移除按鈕區
            c_w1, c_w2 = st.columns([2, 5])
            with c_w1:
                is_in_watchlist = selected_stock in st.session_state.watchlist
                if not is_in_watchlist:
                    if st.button("⭐ 加入我的自選股追蹤", use_container_width=True):
                        st.session_state.watchlist.append(selected_stock)
                        st.success(f"已成功將 {selected_stock} 加入自選股！")
                        st.rerun()
                else:
                    if st.button("❌ 從自選股移除", use_container_width=True):
                        st.session_state.watchlist.remove(selected_stock)
                        st.warning(f"已將 {selected_stock} 移出自選股。")
                        st.rerun()

            with st.spinner(f"正在載入 {selected_stock} 歷史數據..."):
                df_k = get_finmind_data(selected_stock)
                if df_k is not None and not df_k.empty:
                    fig_res = plot_beautified_chart(
                        df_k, 
                        f"({st.session_state.selected_stock_index+1}/{total_stocks}) {selected_stock} {r_row['股票名稱']} [{r_row['組合邏輯名稱']}]", 
                        20, 
                        enable_first_limit=True, 
                        first_limit_days=30
                    )
                    st.plotly_chart(fig_res, use_container_width=True)
                else:
                    st.warning("⚠️ 無法獲取該標的的歷史數據。")
    else:
        st.info("💡 請先執行策略篩選，以在此處瀏覽圖表。")

with tab3:
    st.subheader("⭐ 我的自選股追蹤清單")
    if st.session_state.watchlist:
        st.markdown(f"目前追蹤中的自選股共 `{len(st.session_state.watchlist)}` 檔：")
        
        # 顯示自選股摘要表格
        watch_data = []
        stock_list_df = get_taiwan_stock_list()
        for w_code in st.session_state.watchlist:
            matched = stock_list_df[stock_list_df['code'] == w_code]
            w_name = matched['name'].values[0] if not matched.empty else "未知"
            df_w = get_finmind_data(w_code)
            if df_w is not None and not df_w.empty:
                c_price = df_w['Close'].iloc[-1]
                p_close = df_w['Close'].iloc[-2] if len(df_w) > 1 else c_price
                chg = round((c_price - p_close)/p_close*100, 2)
                vol = int(df_w['Volume'].iloc[-1] / 1000)
                watch_data.append({"股票代號": w_code, "股票名稱": w_name, "收盤價": round(c_price, 2), "當日漲幅(%)": chg, "成交量(張)": vol})
        
        if watch_data:
            df_watch_res = pd.DataFrame(watch_data)
            st.dataframe(df_watch_res, use_container_width=True, hide_index=True)
            
            # 清除自選股按鈕
            if st.button("🗑️ 清空所有自選股"):
                st.session_state.watchlist = []
                st.rerun()
    else:
        st.info("📌 您尚未加入任何自選股。可在 **「K 線圖互動瀏覽」** 分頁中點擊按鈕將喜愛的標的加入追蹤！")

with tab4:
    st.subheader("🩺 個股即時技術診斷中心")
    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        diag_code = st.text_input("輸入 4 位數台股代號進行獨立診斷", placeholder="例如: 2330", key="input_diag_code")
    with col_d2:
        st.write("")
        st.write("")
        diag_btn = st.button("🔎 產出即時 K 線圖與技術診斷", use_container_width=True)

    if diag_btn and diag_code:
        with st.spinner(f"正在擷取 {diag_code} 180天歷史數據與技術指標..."):
            df_diag = get_finmind_data(diag_code)
            if df_diag is not None and not df_diag.empty:
                stock_list_df = get_taiwan_stock_list()
                matched_row = stock_list_df[stock_list_df['code'] == str(diag_code)]
                s_name = matched_row['name'].values[0] if not matched_row.empty else "未知公司"
                
                st.success(f"📊 股票代號 {diag_code} - {s_name} 技術診斷報告")
                fig_diag = plot_beautified_chart(df_diag, f"{diag_code} {s_name} 獨立診斷", 20, enable_first_limit=True, first_limit_days=30)
                st.plotly_chart(fig_diag, use_container_width=True)
            else:
                st.error(f"❌ 查無代號 {diag_code} 的歷史數據或輸入錯誤。")
    elif not diag_btn:
        st.info("💡 輸入任意台股代號即可獨立檢視其技術分析 K 線圖與均線、MACD 等技術診斷。")
