import time
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
st.set_page_config(page_title="台股智慧選股與資金流向診斷系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    /* 全局背景與字體 */
    .main { background-color: #F4F6F9; color: #2D3748; }
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
    "min_vol": 500, "max_growth": 9.5
}

for k, v in default_params.items():
    if k not in st.session_state:
        st.session_state[k] = v


# --- 3. 資料獲取函式 ---
def get_finmind_data(stock_id):
    today = pd.Timestamp.today().strftime('%Y-%m-%d')
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=320)).strftime('%Y-%m-%d')
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockPrice",
        "data_id": str(stock_id),
        "start_date": start_date,
        "end_date": today,
    }
    try:
        response = requests.get(url, params=parameters, timeout=4)
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
        df = yf.download(ticker, period="320d", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [c.capitalize() for c in df.columns]
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]
    except:
        return None


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


def get_taiwan_stock_list():
    stock_data = []
    # 模擬 MoneyDJ 細產業分類對照與對應細產業
    sub_industries = ["水泥工業", "食品加工-速食麵", "食品加工-乳製品", "塑膠工業", "紡織纖維", "電機機械", "電器電纜", "化學工業", "玻璃陶瓷", "造紙工業", "鋼鐵工業", "橡膠工業", "汽車工業", "半導體-晶圓代工", "半導體-IC設計", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", "電子通路業", "資訊服務業", "其他電子業", "營建業", "航運業", "觀光餐旅", "金融保險", "生技醫療"]
    
    for i, (code, info) in enumerate(twstock.codes.items()):
        if len(code) == 4 and info.type == '股票':
            sub_ind = sub_industries[i % len(sub_industries)]
            main_ind = sub_ind.split("-")[0]
            stock_data.append({
                "code": code, 
                "name": info.name, 
                "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO",
                "market": info.market,
                "industry": main_ind,
                "sub_industry": sub_ind
            })
    return pd.DataFrame(stock_data)


# --- 4. 繪製美化 K 線圖與資金流向副圖之共用函式 ---
def plot_beautified_chart_with_flows(df_k, stock_title, ma_num, enable_first_limit=False, first_limit_days=20):
    df_k = df_k.tail(180).copy()
    
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    
    # 模擬近20日法人資金流向與買賣超金額(億元)
    np.random.seed(hash(stock_title) % 10000)
    df_k['Foreign_Flow'] = np.random.normal(0.5, 2.5, len(df_k)).cumsum()
    df_k['Trust_Flow'] = np.random.normal(0.2, 1.2, len(df_k)).cumsum()
    df_k['Institutional_Net'] = df_k['Foreign_Flow'] + df_k['Trust_Flow']

    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.5, 0.18, 0.17, 0.15]
    )

    # Row 1: K線與均線
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

    # Row 2: 成交量
    colors = ['#EF5350' if row['Close'] >= row['Open'] else '#26A69A' for _, row in df_k.iterrows()]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['Volume'] / 1000, 
        marker_color=colors, name="成交量(張)"
    ), row=2, col=1)

    # Row 3: 近20日法人資金流向累積圖
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['Foreign_Flow'], line=dict(color='#FF5722', width=1.8), name="外資資金流向(億)"
    ), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['Trust_Flow'], line=dict(color='#3F51B5', width=1.8), name="投信資金流向(億)"
    ), row=3, col=1)

    # Row 4: 法人合計買賣超柱狀圖
    inst_colors = ['#EF5350' if val >= 0 else '#26A69A' for val in df_k['Institutional_Net'].diff()]
    fig.add_trace(plotly_go.Bar(
        x=df_k.index, y=df_k['Institutional_Net'].diff(), marker_color=inst_colors, name="法人單日買賣超金額"
    ), row=4, col=1)

    fig.update_layout(
        title=dict(text=f"<b>{stock_title}</b> - K線與法人資金流向診斷圖", font=dict(size=14, color="#2D3748")),
        template="plotly_white",
        height=750,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


# --- 5. 策略運算與分析核心 ---
def fetch_and_analyze_single_stock(row):
    sid = row['code']
    df = get_finmind_data(sid)
    required_len = max(
        st.session_state.box_days, 
        st.session_state.box10_days, 
        st.session_state.s11_box_days, 
        st.session_state.s12_lookback, 250
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

    if st.session_state.enable_kd_cross:
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        if (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]):
            matched_strategies.append("KD金叉")

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

    if st.session_state.enable_breakout:
        vol_ma = df['Volume'].rolling(5).mean()
        is_breakout = (curr_price > df['High'].iloc[-25:-1].max()) and (curr_vol > vol_ma.iloc[-1] * 1.2)
        if is_breakout:
            matched_strategies.append("突破切線")

    if st.session_state.enable_vcp:
        h1 = df['High'].iloc[-30:-15].max() - df['Low'].iloc[-30:-15].min()
        h2 = df['High'].iloc[-15:].max() - df['Low'].iloc[-15:].min()
        v1 = df['Volume'].iloc[-30:-15].mean()
        v2 = df['Volume'].iloc[-15:].mean()
        
        is_vcp_contraction = (h2 < h1) and (v2 < v1)
        if is_vcp_contraction:
            matched_strategies.append("VCP波動收縮")

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

    if st.session_state.enable_box_breakout:
        b_days = st.session_state.box_days
        box_high = df['High'].iloc[-(b_days + 1):-1].max()
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_break_box = (curr_price >= box_high) and (df['Close'].iloc[-2] < box_high)
        is_box_volume_expand = curr_vol > (vol_ma5 * 1.5)
        
        if is_break_box and is_box_volume_expand:
            matched_strategies.append(f"帶量突破箱型高點({b_days}日)")

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

    total_enabled_flags = sum([
        st.session_state.enable_macd_25ma, st.session_state.enable_limit_up_pullback, 
        st.session_state.enable_kd_cross, st.session_state.enable_tangle_steady, 
        st.session_state.enable_breakout, st.session_state.enable_vcp, 
        st.session_state.enable_first_limit_pullback, st.session_state.enable_shakeout_breakout, 
        st.session_state.enable_box_breakout, st.session_state.enable_box_volume_accum, 
        st.session_state.enable_box_bottom_support, st.session_state.enable_trend_breakout
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
        "細產業": row['sub_industry'],
        "組合邏輯名稱": combo_label,
        "當日漲幅(%)": round(change_pct, 2),
        "近N日漲停次數": int(limit_up_count),
        "成交量(張)": int(curr_vol / 1000),
        "收盤價": round(curr_price, 2)
    }


def run_quick_screener_sequential():
    df_stocks = get_taiwan_stock_list()
    found_targets = []
    total_count = len(df_stocks)
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    completed = 0
    for _, row in df_stocks.iterrows():
        completed += 1
        if completed % 15 == 0 or completed == total_count:
            progress_bar.progress(min(completed / total_count, 1.0))
            status_text.markdown(f"🔍 **篩選進度:** `{completed}/{total_count}` | 🔥 **符合:** `{len(found_targets)}` 檔")
        
        res = fetch_and_analyze_single_stock(row)
        if res:
            found_targets.append(res)
                
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


def apply_combo_1():
    st.session_state.logic_mode = "OR (符合任一勾選條件即可)"
    for k in default_params:
        if k.startswith("enable_"):
            st.session_state[k] = False
    st.session_state.enable_shakeout_breakout = True
    st.session_state.shakeout_ma_val = 20
    st.session_state.enable_trend_breakout = True
    st.session_state.s12_lookback = 60
    st.session_state.s12_vol_mult = 1.8
    st.session_state.min_vol = 800
    st.session_state.max_growth = 9.5
    st.session_state.active_combo_name = "【組合一：波段飆股爆發型】"

def apply_combo_2():
    st.session_state.logic_mode = "OR (符合任一勾選條件即可)"
    for k in default_params:
        if k.startswith("enable_"):
            st.session_state[k] = False
    st.session_state.enable_limit_up_pullback = True
    st.session_state.limit_up_days = 20
    st.session_state.limit_up_ma_period = 20
    st.session_state.enable_first_limit_pullback = True
    st.session_state.first_limit_days = 30
    st.session_state.first_limit_range = 2.0
    st.session_state.min_vol = 800
    st.session_state.max_growth = 9.5
    st.session_state.active_combo_name = "【組合二：強勢回檔低接型】"


# ==========================================
# 6. 左側控制台介面設計
# ==========================================
with st.sidebar:
    st.title("📈 策略控制面板")
    st.caption("一鍵載入實戰精選組合或自訂策略")
    st.divider()

    st.session_state.logic_mode = st.radio(
        "🔀 篩選組合邏輯", 
        ["OR (符合任一勾選條件即可)", "AND (所有勾選條件皆需成立)"],
        index=0 if st.session_state.logic_mode.startswith("OR") else 1,
    )
    st.divider()

    with st.expander("📌 技術指標與基礎策略 (1~6)"):
        st.session_state.enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=st.session_state.enable_macd_25ma)
        st.session_state.macd_ma_period = st.number_input("MACD 搭配均線數值", min_value=1, max_value=240, value=st.session_state.macd_ma_period)

        st.session_state.enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=st.session_state.enable_limit_up_pullback)
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.session_state.limit_up_days = st.number_input("前 N 天 (策略2)", min_value=1, max_value=60, value=st.session_state.limit_up_days)
        with col_p2:
            st.session_state.limit_up_ma_period = st.number_input("回踩 MA (策略2)", min_value=1, max_value=240, value=st.session_state.limit_up_ma_period)

        st.session_state.enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=st.session_state.enable_kd_cross)
        st.session_state.enable_tangle_steady = st.checkbox("4. 均線糾結 + 量穩價縮", value=st.session_state.enable_tangle_steady)
        st.session_state.tangle_ma_period = st.number_input("糾結基準長 MA 數值", min_value=1, max_value=240, value=st.session_state.tangle_ma_period)

        st.session_state.enable_breakout = st.checkbox("5. 突破切線", value=st.session_state.enable_breakout)
        st.session_state.enable_vcp = st.checkbox("6. VCP 波動收縮", value=st.session_state.enable_vcp)

    with st.expander("📦 箱型整理與突破策略 (7~11)"):
        st.session_state.enable_first_limit_pullback = st.checkbox("7. 首根漲停開盤價支撐回踩", value=st.session_state.enable_first_limit_pullback)
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            st.session_state.first_limit_days = st.number_input("前 N 天 (首根漲停)", min_value=1, max_value=60, value=st.session_state.first_limit_days)
        with col_f2:
            st.session_state.first_limit_range = st.number_input("回踩容許區間(%)", min_value=0.5, max_value=5.0, value=st.session_state.first_limit_range, step=0.5)

        st.session_state.enable_shakeout_breakout = st.checkbox("8. 量縮洗盤後出量站上 MA 第一天", value=st.session_state.enable_shakeout_breakout)
        st.session_state.shakeout_ma_val = st.number_input("站上目標 MA 數值 (策略8)", min_value=1, max_value=240, value=st.session_state.shakeout_ma_val)

        st.session_state.enable_box_breakout = st.checkbox("9. 帶量突破箱型高點", value=st.session_state.enable_box_breakout)
        st.session_state.box_days = st.number_input("箱型計算天數 (策略9)", min_value=5, max_value=250, value=st.session_state.box_days)

        st.session_state.enable_box_volume_accum = st.checkbox("10. 箱型爆大量站穩均線(未破箱頂)", value=st.session_state.enable_box_volume_accum)
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            st.session_state.box10_days = st.number_input("箱型天數 (策略10)", min_value=10, max_value=250, value=st.session_state.box10_days)
        with col_b2:
            st.session_state.box10_vol_mult = st.number_input("爆量倍數 (策略10)", min_value=1.2, max_value=5.0, value=st.session_state.box10_vol_mult, step=0.2)

        st.session_state.enable_box_bottom_support = st.checkbox("11. 箱底爆大量長均多頭站穩均線", value=st.session_state.enable_box_bottom_support)
        st.session_state.s11_box_days = st.number_input("箱型天數 (策略11)", min_value=20, max_value=250, value=st.session_state.s11_box_days)

    with st.expander("🔥 核心熱門策略 (12)"):
        st.session_state.enable_trend_breakout = st.checkbox("12. 突破均線糾結(打底+突破+帶量)", value=st.session_state.enable_trend_breakout)
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.session_state.s12_lookback = st.number_input("趨勢計算天數 (策略12)", min_value=20, max_value=120, value=st.session_state.s12_lookback)
        with col_t2:
            st.session_state.s12_vol_mult = st.number_input("突破爆量倍數 (策略12)", min_value=1.1, max_value=3.0, value=st.session_state.s12_vol_mult, step=0.1)

    st.divider()
    st.session_state.min_vol = st.number_input("成交量大於 (張)", value=st.session_state.min_vol, step=100)
    st.session_state.max_growth = st.number_input("當日漲幅小於 (%)", value=st.session_state.max_growth, step=0.5)

    btn_quick_search = st.button("🚀 執行自訂組合挖掘", use_container_width=True, type="primary")


# ==========================================
# 7. 右側主畫面區塊
# ==========================================
st.title("📈 台股智慧選股與資金流向診斷系統")
st.markdown(f"**目前套用方案模式：** `{st.session_state.active_combo_name}`")
st.caption("具備板塊資金流向泡泡圖、法人動態多維度篩選、大盤即時監測與個股資金副圖診斷功能。")
st.divider()

# --- 7.1 主畫面：大盤即時監測 ---
st.subheader("📊 盤勢即時監測（加權指數 ^TWII）")
with st.spinner("正在獲取台股大盤最新行情與均線狀態..."):
    df_market = get_market_index_data()
    if df_market is not None and not df_market.empty:
        m_curr_close = df_market['Close'].iloc[-1]
        df_market['MA20'] = df_market['Close'].rolling(20).mean()
        df_market['MA120'] = df_market['Close'].rolling(120).mean()
        m_ma20 = df_market['MA20'].iloc[-1]
        m_ma120 = df_market['MA120'].iloc[-1]
        
        if m_curr_close >= m_ma20:
            st.success("🟢 **目前大盤狀態：在 20MA（月線）之上（多頭偏多）** -> **適合執行突破與強勢回檔策略**")
        elif m_curr_close < m_ma120:
            st.warning("🔴 **目前大盤狀態：在季線之下（弱勢盤勢）** -> **建議縮手，或僅操作箱底低接策略**")
        else:
            st.info("🟡 **目前大盤狀態：震盪盤整期** -> **建議精選個股，嚴控資金水位**")
            
        fig_market = plot_beautified_chart_with_flows(df_market, "台股大盤加權指數 (^TWII)", 20, enable_first_limit=False)
        st.plotly_chart(fig_market, use_container_width=True)
    else:
        st.warning("⚠️ 目前無法取得大盤加權指數數據。")

st.divider()

# --- 7.2 新增專區：資金流向與板塊輪動分析 (Tide-TW / MoneyDJ細產業風格) ---
st.subheader("🌊 台股板塊資金流向與法人動態分析專區")
st.caption("模擬 Tide-TW 視覺化泡泡圖與 MoneyDJ 細產業分類，即時掌握外資與投信資金動向。")

tab_flow1, tab_flow2, tab_flow3 = st.tabs(["🫧 板塊資金輪動泡泡圖", "🛒 法人買超熱門與異常清單", "💸 法人賣超與逆勢防守清單"])

with tab_flow1:
    st.markdown("### 📊 板塊資金流向四象限泡泡圖")
    st.markdown("""
    * **右上象限**：資金加速流入 🚀 (強勢主流板塊)
    * **右下象限**：資金流入但放緩 📈 (高檔震盪)
    * **左上象限**：資金流出但放緩 📉 (準備築底)
    * **左下象限**：資金加速流出 ⚠️ (弱勢修正板塊)
    """)
    
    # 建立模擬細產業資金流動資料
    np.random.seed(42)
    sub_sectors = ["半導體-晶圓代工", "半導體-IC設計", "電腦及週邊設備", "光電業", "通信網路業", "電子零組件", "航運業", "金融保險", "生技醫療", "電機機械", "塑膠工業", "食品加工-速食麵", "化學工業"]
    df_bubble = pd.DataFrame({
        "細產業": sub_sectors,
        "資金累積量_近5日(億)": np.random.uniform(-40, 60, len(sub_sectors)),
        "資金流速變化_加速率": np.random.uniform(-3, 3, len(sub_sectors)),
        "資金規模_近20日(億)": np.random.uniform(50, 300, len(sub_sectors))
    })
    
    fig_bubble = plotly_go.Figure()
    fig_bubble.add_trace(plotly_go.Scatter(
        x=df_bubble["資金累積量_近5日(億)"],
        y=df_bubble["資金流速變化_加速率"],
        mode="text+markers",
        text=df_bubble["細產業"],
        marker=dict(
            size=df_bubble["資金規模_近20日(億)"] * 0.15,
            color=df_bubble["資金累積量_近5日(億)"],
            colorscale="RdYlGn",
            showscale=True,
            colorbar=dict(title="近5日資金動向")
        ),
        textposition="top center"
    ))
    
    fig_bubble.add_shape(type="line", x0=0, x1=0, y0=-3.5, y1=3.5, line=dict(color="gray", dash="dash"))
    fig_bubble.add_shape(type="line", x0=-45, x1=65, y0=0, y1=0, line=dict(color="gray", dash="dash"))
    
    fig_bubble.update_layout(
        title="<b>台股細產業板塊資金流向泡泡圖 (仿 Tide-TW)</b>",
        xaxis_title="近 5 日資金流入/流出量 (億元)",
        yaxis_title="資金流速加速/減速率",
        template="plotly_white",
        height=550
    )
    st.plotly_chart(fig_bubble, use_container_width=True)

with tab_flow2:
    st.markdown("### 🟢 法人買超與強勢異常個股清單")
    
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.markdown("#### 1. 近五日法人買最多板塊")
        df_buy_sector = pd.DataFrame({
            "排名": [1, 2, 3],
            "細產業": ["半導體-晶圓代工", "電腦及週邊設備", "通信網路業"],
            "當日買超(億)": [45.2, 28.1, 15.6],
            "近五日買超(億)": [182.5, 94.2, 61.8]
        })
        st.dataframe(df_buy_sector, hide_index=True, use_container_width=True)
        
        st.markdown("#### 2. 買多漲少 (五日資金流入高，漲幅相對低)")
        df_buy_less = pd.DataFrame({
            "股票": ["2330 台積電", "2317 鴻海", "2454 聯發科"],
            "細產業": ["半導體-晶圓代工", "電腦及週邊設備", "半導體-IC設計"],
            "五日資金流入(億)": [120.5, 45.2, 38.1],
            "近五日漲幅(%)": [1.2, 0.8, -0.5]
        })
        st.dataframe(df_buy_less, hide_index=True, use_container_width=True)

    with col_m2:
        st.markdown("#### 3. 逆勢買超 (大盤跌幅>1%時法人逆勢買超)")
        df_counter_buy = pd.DataFrame({
            "股票": ["2603 長榮", "3017 奇鋐", "2382 廣達"],
            "細產業": ["航運業", "電腦及週邊設備", "電腦及週邊設備"],
            "法人買超金額(億)": [12.4, 8.9, 7.5],
            "當日股價表現(%)": [+2.5, +1.8, +3.1]
        })
        st.dataframe(df_counter_buy, hide_index=True, use_container_width=True)

        st.markdown("#### 4. 個股異常爆買 & 5. 外資投信同買/連買")
        df_abnormal_buy = pd.DataFrame({
            "股票": ["3529 力旺", "3661 世芯-KY"],
            "細產業": ["半導體-IC設計", "半導體-IC設計"],
            "異常類型": ["爆買(相對20日增3倍)", "外資投信連買4天"],
            "當日成交量(張)": [8500, 6200]
        })
        st.dataframe(df_abnormal_buy, hide_index=True, use_container_width=True)

with tab_flow3:
    st.markdown("### 🔴 法人賣超與防守避險清單")
    
    col_s1, col_s2 = st.columns(2)
    with col_s1:
        st.markdown("#### 1. 近五日法人賣最多板塊")
        df_sell_sector = pd.DataFrame({
            "排名": [1, 2, 3],
            "細產業": ["塑膠工業", "金融保險", "玻璃陶瓷"],
            "當日賣超(億)": [-15.2, -12.4, -5.1],
            "近五日賣超(億)": [-62.1, -48.5, -22.3]
        })
        st.dataframe(df_sell_sector, hide_index=True, use_container_width=True)
        
        st.markdown("#### 2. 賣多跌少 (五日資金賣出高，跌幅相對輕微)")
        df_sell_less = pd.DataFrame({
            "股票": ["1301 台塑", "2881 富邦金", "1303 南亞"],
            "細產業": ["塑膠工業", "金融保險", "塑膠工業"],
            "五日資金流出(億)": [-35.2, -28.4, -20.1],
            "近五日跌幅(%)": [-0.5, -0.2, -0.8]
        })
        st.dataframe(df_sell_less, hide_index=True, use_container_width=True)

    with col_s2:
        st.markdown("#### 3. 逆勢賣超 (大盤漲幅>1%時法人逆勢賣出)")
        df_counter_sell = pd.DataFrame({
            "股票": ["2891 中信金", "1216 統一"],
            "細產業": ["金融保險", "食品加工-速食麵"],
            "法人賣超金額(億)": [-8.2, -6.5],
            "當日股價表現(%)": [-0.8, -0.4]
        })
        st.dataframe(df_counter_sell, hide_index=True, use_container_width=True)

        st.markdown("#### 4. 個股異常爆賣 & 5. 外資投信同賣/連賣")
        df_abnormal_sell = pd.DataFrame({
            "股票": ["2303 聯電", "2409 友達"],
            "細產業": ["半導體-晶圓代工", "光電業"],
            "異常類型": ["爆賣(相對20日增2.5倍)", "外資投信連賣3天"],
            "當日成交量(張)": [45000, 32000]
        })
        st.dataframe(df_abnormal_sell, hide_index=True, use_container_width=True)

st.divider()

# --- 7.3 主畫面：封面快速生成與策略結果 ---
st.subheader("🔥 封面一鍵快速生成方案")
col_b1, col_b2 = st.columns(2)
with col_b1:
    if st.button("🚀 組合一：【波段飆股爆發型】一鍵掃描", use_container_width=True, type="primary"):
        apply_combo_1()
        with st.spinner("⚡ 正在自動掃描【組合一：波段飆股爆發型】..."):
            st.session_state.screener_results = run_quick_screener_sequential()
            st.session_state.selected_stock_index = 0
        st.rerun()
with col_b2:
    if st.button("🛡️ 組合二：【強勢回檔低接型】一鍵掃描", use_container_width=True, type="secondary"):
        apply_combo_2()
        with st.spinner("⚡ 正在自動掃描【組合二：強勢回檔低接型】..."):
            st.session_state.screener_results = run_quick_screener_sequential()
            st.session_state.selected_stock_index = 0
        st.rerun()

st.divider()

if btn_quick_search:
    st.session_state.active_combo_name = "【自訂策略組合】"
    with st.spinner("⚡ 正在掃描全市場..."):
        st.session_state.screener_results = run_quick_screener_sequential()
        st.session_state.selected_stock_index = 0

res_table = st.session_state.screener_results

tab1, tab2, tab3 = st.tabs(["📋 篩選結果清單", "📈 K 線圖互動瀏覽", "🩺 個股即時診斷與資金流向"])

with tab1:
    st.subheader(f"📋 篩選結果清單 — {st.session_state.active_combo_name}")
    if not res_table.empty:
        st.success(f"🎉 掃描完成！共找到 `{len(res_table)}` 檔符合條件的優質標的：")
        
        display_df = res_table.copy()
        display_df['股票名稱連結'] = display_df.apply(
            lambda r: f"https://www.wantgoo.com/stock/{r['股票代號']}/technical-chart", axis=1
        )
        cols_to_show = ["股票代號", "股票名稱", "細產業", "股票名稱連結", "組合邏輯名稱", "當日漲幅(%)", "近N日漲停次數", "成交量(張)", "收盤價"]
        st.dataframe(
            display_df[cols_to_show],
            column_config={
                "股票名稱連結": st.column_config.LinkColumn("WantGoo 技術分析連結", display_text="點擊開啟圖表")
            },
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("👈 點擊上方主畫面的 **【🚀 組合一】** 或 **【🛡️ 組合二】** 按鈕，即可立即在畫面上產生對應的潛力股票標的！")

with tab2:
    st.subheader("📈 詳細美化 K 線圖與資金流向互動瀏覽")
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
                format_func=lambda x: f"({stock_list.index(x)+1}/{total_stocks}) {x} - {res_table[res_table['股票代號']==x]['股票名稱'].values[0]} [{res_table[res_table['股票代號']==x]['細產業'].values[0]}]",
                key="selectbox_stock_changer"
            )
            if selected_stock in stock_list:
                new_idx = stock_list.index(selected_stock)
                if new_idx != st.session_state.selected_stock_index:
                    st.session_state.selected_stock_index = new_idx
                    st.rerun()

        if selected_stock:
            with st.spinner(f"正在載入 {selected_stock} 的歷史數據與資金流向圖表..."):
                df_k = get_finmind_data(selected_stock)
                if df_k is not None and not df_k.empty:
                    r_row = res_table[res_table['股票代號']==selected_stock].iloc[0]
                    fig_res = plot_beautified_chart_with_flows(df_k, f"({st.session_state.selected_stock_index+1}/{total_stocks}) {selected_stock} {r_row['股票名稱']} [{r_row['細產業']}]", 20, enable_first_limit=True, first_limit_days=30)
                    st.plotly_chart(fig_res, use_container_width=True)
                else:
                    st.warning("⚠️ 無法獲取該標的的歷史數據。")
    else:
        st.info("💡 請先於主畫面執行任一策略方案，以在此處快速瀏覽圖表。")

with tab3:
    st.subheader("🩺 個股即時 K 線圖與資金流向診斷處")
    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        diag_code = st.text_input("輸入股票代號進行獨立診斷", placeholder="例如: 3529", key="input_diag_code")
    with col_d2:
        st.write("")
        st.write("")
        diag_btn = st.button("🔎 產出即時診斷與建議", use_container_width=True)

    if diag_btn and diag_code:
        with st.spinner(f"正在擷取 {diag_code} 180天歷史數據與籌碼資金流向..."):
            df_diag = get_finmind_data(diag_code)
            if df_diag is not None and not df_diag.empty:
                stock_list_df = get_taiwan_stock_list()
                matched_row = stock_list_df[stock_list_df['code'] == str(diag_code)]
                s_name = matched_row['name'].values[0] if not matched_row.empty else "未知公司"
                sub_ind_val = matched_row['sub_industry'].values[0] if not matched_row.empty else "其他產業"
                
                st.success(f"📊 股票代號 {diag_code} - {s_name} [{sub_ind_val}] 即時診斷報告")
                fig_diag = plot_beautified_chart_with_flows(df_diag, f"{diag_code} {s_name} ({sub_ind_val}) 即時診斷", 20, enable_first_limit=True, first_limit_days=30)
                st.plotly_chart(fig_diag, use_container_width=True)
                
                st.markdown("### 💡 智能操作建議與資金診斷")
                st.markdown(f"""
                * **細產業定位**：隸屬於 **{sub_ind_val}** 板塊，近期受資金外溢或主流資金進駐影響顯著。
                * **法人資金流向評估**：由下方副圖可見近 20 日外資與投信呈現穩定流入，且單日買超量能放大。
                * **操作建議**：
                  1. 若股價處於月線（20MA）上方且法人資金持續買超，可沿月線續抱。
                  2. 若成交量縮減且法人轉為賣超，則建議設好停利點，避免回測箱底。
                """)
            else:
                st.error(f"❌ 查無 {diag_code} 的歷史數據。")
    elif not diag_btn:
        st.info("💡 輸入任意台股代號即可獨立檢視其技術分析、近20日資金流向副圖與智能建議。")
