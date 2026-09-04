import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit.components.v1 as components

# --- 1. 頁面配置與簡潔美化 CSS ---
st.set_page_config(page_title="台股快速潛力股挖掘與 K 線診斷系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #F8F9FA; }
    div.block-container { padding-top: 2rem; padding-bottom: 2rem; }
    .stSelectbox, .stSlider, .stNumberInput { margin-bottom: 4px; }
</style>
""", unsafe_allow_html=True)

if 'screener_results' not in st.session_state:
    st.session_state.screener_results = pd.DataFrame()

if 'selected_stock_index' not in st.session_state:
    st.session_state.selected_stock_index = 0

# --- 2. 資料獲取函式 (FinMind 280天數據確保足夠算 240MA + yfinance 備份) ---
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
        response = requests.get(url, params=parameters, timeout=5)
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

def get_taiwan_stock_list():
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# --- 3. 繪製美化白色 K 線圖的共用函式 ---
def plot_beautified_chart(df_k, stock_title, ma_num, enable_first_limit=False, first_limit_days=20):
    df_k = df_k.tail(200).copy()
    
    ma_col_name = f'MA{ma_num}'
    df_k[ma_col_name] = df_k['Close'].rolling(ma_num).mean()
    df_k['MA60'] = df_k['Close'].rolling(60).mean()
    df_k['MA120'] = df_k['Close'].rolling(120).mean()
    
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

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['MA60'], 
        line=dict(color='#FFA500', width=1.5), 
        name="MA60"
    ), row=1, col=1)

    fig.add_trace(plotly_go.Scatter(
        x=df_k.index, y=df_k['MA120'], 
        line=dict(color='#1E90FF', width=1.5), 
        name="MA120"
    ), row=1, col=1)

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
        title=dict(text=f"<b>{stock_title}</b> - 歷史日線圖與均線診斷", font=dict(size=14, color="#2D3748")),
        template="plotly_white",
        height=600,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# --- 4. 高效多執行緒全市場掃描函式 ---
def fetch_and_analyze_single_stock(row, enable_macd_25ma, macd_ma_period,
                                    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                                    enable_kd_cross, enable_tangle_steady, tangle_ma_period,
                                    enable_breakout, enable_vcp,
                                    enable_first_limit_pullback, first_limit_days, first_limit_range,
                                    enable_shakeout_breakout, shakeout_ma_val,
                                    enable_box_breakout, box_days,
                                    enable_box_volume_accum, box10_days, box10_vol_mult,
                                    enable_box_bottom_surge, b11_days, b11_vol_mult, b11_limit_days,
                                    logic_mode, min_vol, max_growth):
    sid = row['code']
    df = get_finmind_data(sid)
    if df is None or len(df) < 250:
        return None
        
    df = df.dropna(subset=['Close'])
    curr_price = df['Close'].iloc[-1]
    prev_close = df['Close'].iloc[-2] if len(df) > 1 else curr_price
    curr_vol = df['Volume'].iloc[-1]

    if curr_vol < (min_vol * 1000): return None
    change_pct = ((curr_price - prev_close) / prev_close) * 100
    if change_pct > max_growth: return None

    df['daily_change'] = df['Close'].pct_change() * 100
    recent_df = df.iloc[-60:]
    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

    matched_strategies = []
    extra_note = ""

    if enable_macd_25ma:
        df['ma_a'] = df['Close'].rolling(macd_ma_period).mean()
        ma_a_curr = df['ma_a'].iloc[-1]
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        dif = exp1 - exp2
        signal = dif.ewm(span=9, adjust=False).mean()
        
        cond_ma = (df['Low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
        cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
        if cond_ma and cond_macd:
            matched_strategies.append("MACD回踩0軸")

    if enable_limit_up_pullback:
        df['ma_b'] = df['Close'].rolling(limit_up_ma_period).mean()
        ma_b_curr = df['ma_b'].iloc[-1]
        df['vol_ma5'] = df['Volume'].rolling(5).mean()
        
        check_range = df.iloc[-limit_up_days:]
        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['Volume'] > check_range['vol_ma5'] * 1.5)).any()
        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
        is_touch_ma = (df['Low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
        
        if had_limit_up_vol and is_vol_shrink and is_touch_ma:
            matched_strategies.append("漲停回踩MA")

    if enable_kd_cross:
        low_9 = df['Low'].rolling(9).min()
        high_9 = df['High'].rolling(9).max()
        rsv = (df['Close'] - low_9) / (high_9 - low_9) * 100
        k = rsv.ewm(com=2).mean()
        d = k.ewm(com=2).mean()
        if (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1]):
            matched_strategies.append("KD金叉")

    if enable_tangle_steady:
        ma5 = df['Close'].rolling(5).mean()
        ma10 = df['Close'].rolling(10).mean()
        ma20 = df['Close'].rolling(tangle_ma_period).mean()
        
        ma_max = pd.concat([ma5, ma10, ma20], axis=1).max(axis=1)
        ma_min = pd.concat([ma5, ma10, ma20], axis=1).min(axis=1)
        is_tangled = ((ma_max - ma_min) / ma_min < 0.025).iloc[-5:-1].any()
        
        vol_ma = df['Volume'].rolling(5).mean()
        is_vol_steady = df['Volume'].iloc[-5:-1].mean() < vol_ma.iloc[-1] * 1.3
        is_price_shrink = df['Close'].iloc[-1] <= df['Close'].iloc[-5] * 1.05
        
        if is_tangled and is_vol_steady and is_price_shrink:
            matched_strategies.append("均線糾結+量穩價縮")

    if enable_breakout:
        vol_ma = df['Volume'].rolling(5).mean()
        is_breakout = (curr_price > df['High'].iloc[-25:-1].max()) and (curr_vol > vol_ma.iloc[-1] * 1.2)
        if is_breakout:
            matched_strategies.append("突破切線")

    if enable_vcp:
        h1 = df['High'].iloc[-30:-15].max() - df['Low'].iloc[-30:-15].min()
        h2 = df['High'].iloc[-15:].max() - df['Low'].iloc[-15:].min()
        v1 = df['Volume'].iloc[-30:-15].mean()
        v2 = df['Volume'].iloc[-15:].mean()
        
        is_vcp_contraction = (h2 < h1) and (v2 < v1)
        if is_vcp_contraction:
            matched_strategies.append("VCP波動收縮")

    if enable_first_limit_pullback:
        check_window = df.iloc[-first_limit_days:]
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
            lower_bound = first_limit_open * (1 - first_limit_range / 100.0)
            upper_bound = first_limit_open * (1 + first_limit_range / 100.0)
            is_near_open = (df['Low'].iloc[-1] <= upper_bound) and (curr_price >= lower_bound)
            
            if is_vol_shrink and is_near_open:
                matched_strategies.append("首根漲停開盤價支撐")

    if enable_shakeout_breakout:
        df[f'shk_ma'] = df['Close'].rolling(shakeout_ma_val).mean()
        vol_ma_20 = df['Volume'].rolling(20).mean().iloc[-1]
        is_volume_expand = curr_vol > vol_ma_20 * 1.3
        
        recent_vol_slice = df['Volume'].iloc[-15:-1]
        is_prior_shrink = (recent_vol_slice.min() < vol_ma_20 * 0.8)
        
        is_first_day_above_ma = (df['Close'].iloc[-1] >= df[f'shk_ma'].iloc[-1]) and (df['Close'].iloc[-2] <= df[f'shk_ma'].iloc[-2])
        
        if is_prior_shrink and is_volume_expand and is_first_day_above_ma:
            matched_strategies.append(f"量縮洗盤後出量站上MA{shakeout_ma_val}")

    if enable_box_breakout:
        box_high = df['High'].iloc[-(box_days + 1):-1].max()
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_break_box = (curr_price >= box_high) and (df['Close'].iloc[-2] < box_high)
        is_box_volume_expand = curr_vol > (vol_ma5 * 1.5)
        
        if is_break_box and is_box_volume_expand:
            matched_strategies.append(f"帶量突破箱型高點({box_days}日)")

    if enable_box_volume_accum:
        box_window = df.iloc[-(box10_days + 1):-1]
        b_high = box_window['High'].max()
        b_low = box_window['Low'].min()
        is_inside_box = (curr_price < b_high) and (curr_price > b_low)
        
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_surge_volume = curr_vol > (vol_ma5 * box10_vol_mult)
        
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma10 = df['Close'].rolling(10).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        is_above_all_mas = (curr_price >= ma5) and (curr_price >= ma10) and (curr_price >= ma20)
        
        if is_inside_box and is_surge_volume and is_above_all_mas:
            matched_strategies.append(f"箱型爆大量站穩均線未破頂({box10_days}日)")

    if enable_box_bottom_surge:
        # 計算箱型 (預設120天)
        box_window = df.iloc[-(b11_days + 1):-1]
        b_high = box_window['High'].max()
        b_low = box_window['Low'].min()
        box_range = b_high - b_low
        
        # 條件 1：股價位於箱型底部支撐處附近 (距離箱底在箱高 25% 以內)
        is_near_bottom = curr_price <= (b_low + box_range * 0.25) and curr_price >= b_low * 0.98
        
        # 條件 2：長期均線多頭排列 (60 > 120 > 240)
        ma60 = df['Close'].rolling(60).mean().iloc[-1]
        ma120 = df['Close'].rolling(120).mean().iloc[-1]
        ma240 = df['Close'].rolling(240).mean().iloc[-1]
        is_long_term_bull = (ma60 > ma120) and (ma120 > ma240)
        
        # 條件 3：突然爆大量 (當日成交量大於 5 日均量的一定倍數)
        vol_ma5 = df['Volume'].rolling(5).mean().iloc[-1]
        is_surge = curr_vol > (vol_ma5 * b11_vol_mult)
        
        # 條件 4：曾經在 N 天內（例如 60 天）出現漲停
        recent_limit_window = df.iloc[-b11_limit_days:]
        had_recent_limit = (recent_limit_window['daily_change'] >= 9.5).any()
        
        # 條件 5：站穩均線檢測 (60, 20, 10, 5) 並標示最高站穩哪條
        ma5 = df['Close'].rolling(5).mean().iloc[-1]
        ma10 = df['Close'].rolling(10).mean().iloc[-1]
        ma20 = df['Close'].rolling(20).mean().iloc[-1]
        
        stood_mas = []
        if curr_price >= ma60: stood_mas.append("MA60")
        if curr_price >= ma20: stood_mas.append("MA20")
        if curr_price >= ma10: stood_mas.append("MA10")
        if curr_price >= ma5: stood_mas.append("MA5")
        
        is_above_any_ma = len(stood_mas) > 0
        
        if is_near_bottom and is_long_term_bull and is_surge and had_recent_limit and is_above_any_ma:
            highest_ma = stood_mas[0] # 因為順序是 60, 20, 10, 5
            matched_strategies.append(f"第11策略:箱底爆大量長多起漲(站穩最高:{highest_ma})")
            extra_note = f"站穩均線:{'/'.join(stood_mas)}"

    total_enabled_flags = sum([
        enable_macd_25ma, enable_limit_up_pullback, enable_kd_cross, 
        enable_tangle_steady, enable_breakout, enable_vcp, enable_first_limit_pullback,
        enable_shakeout_breakout, enable_box_breakout, enable_box_volume_accum,
        enable_box_bottom_surge
    ])
    if total_enabled_flags == 0:
        return None

    if logic_mode == "AND (所有勾選條件皆需成立)":
        if len(matched_strategies) < total_enabled_flags: 
            return None
    else: 
        if len(matched_strategies) == 0: 
            return None

    combo_label = " + ".join(matched_strategies)

    return {
        "股票代號": sid,
        "股票名稱": row['name'],
        "組合邏輯名稱": combo_label,
        "站穩均線狀態": extra_note if extra_note else "符合",
        "當日漲幅(%)": round(change_pct, 2),
        "近N日漲停次數": int(limit_up_count),
        "成交量(張)": int(curr_vol / 1000),
        "收盤價": round(curr_price, 2)
    }

def run_quick_screener_parallel(
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, enable_tangle_steady, tangle_ma_period,
    enable_breakout, enable_vcp,
    enable_first_limit_pullback, first_limit_days, first_limit_range,
    enable_shakeout_breakout, shakeout_ma_val,
    enable_box_breakout, box_days,
    enable_box_volume_accum, box10_days, box10_vol_mult,
    enable_box_bottom_surge, b11_days, b11_vol_mult, b11_limit_days,
    logic_mode, min_vol, max_growth
):
    df_stocks = get_taiwan_stock_list()
    found_targets = []
    total_count = len(df_stocks)
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    
    completed = 0
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(
                fetch_and_analyze_single_stock, 
                row, enable_macd_25ma, macd_ma_period,
                enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
                enable_kd_cross, enable_tangle_steady, tangle_ma_period,
                enable_breakout, enable_vcp,
                enable_first_limit_pullback, first_limit_days, first_limit_range,
                enable_shakeout_breakout, shakeout_ma_val,
                enable_box_breakout, box_days,
                enable_box_volume_accum, box10_days, box10_vol_mult,
                enable_box_bottom_surge, b11_days, b11_vol_mult, b11_limit_days,
                logic_mode, min_vol, max_growth
            ): row for _, row in df_stocks.iterrows()
        }
        
        for future in as_completed(futures):
            completed += 1
            if completed % 15 == 0 or completed == total_count:
                progress_bar.progress(min(completed / total_count, 1.0))
                status_text.markdown(f"🔍 **篩選進度:** `{completed}/{total_count}` | 🔥 **符合:** `{len(found_targets)}` 檔")
            
            res = future.result()
            if res:
                found_targets.append(res)
                
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 5. 左側控制台 (11大策略模組與組合選擇)
# ==========================================
with st.sidebar:
    st.title("⚡ 快速潛力股挖掘 (策略組合)")
    st.divider()

    logic_mode = st.radio(
        "🔀 篩選組合邏輯", 
        ["OR (符合任一勾選條件即可)", "AND (所有勾選條件皆需成立)"],
        index=0,
    )
    st.divider()

    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=False)
    macd_ma_period = st.number_input("MACD 搭配均線數值", min_value=1, max_value=240, value=25)

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天 (策略2)", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA (策略2)", min_value=1, max_value=240, value=25)

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    enable_tangle_steady = st.checkbox("4. 均線糾結 + 量穩價縮", value=False)
    tangle_ma_period = st.number_input("糾結基準長 MA 數值", min_value=1, max_value=240, value=20)

    enable_breakout = st.checkbox("5. 突破切線 (注意追高風險)", value=False)

    enable_vcp = st.checkbox("6. VCP 波動收縮 (量價與振幅漸縮)", value=False)

    enable_first_limit_pullback = st.checkbox("7. 首根漲停開盤價支撐回踩", value=False)
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        first_limit_days = st.number_input("前 N 天 (首根漲停)", min_value=1, max_value=60, value=30)
    with col_f2:
        first_limit_range = st.number_input("回踩容許區間(%)", min_value=0.5, max_value=5.0, value=2.0, step=0.5)

    enable_shakeout_breakout = st.checkbox("8. 量縮洗盤後出量站上 MA 第一天", value=False)
    shakeout_ma_val = st.number_input("站上目標 MA 數值 (策略8)", min_value=1, max_value=240, value=20)

    enable_box_breakout = st.checkbox("9. 帶量突破箱型高點", value=False)
    box_days = st.number_input("箱型計算天數 (策略9)", min_value=5, max_value=250, value=20)

    enable_box_volume_accum = st.checkbox("10. 箱型爆大量站穩均線(未破箱頂)", value=False)
    col_b1, col_b2 = st.columns(2)
    with col_b1:
        box10_days = st.number_input("箱型天數 (策略10)", min_value=10, max_value=250, value=60)
    with col_b2:
        box10_vol_mult = st.number_input("爆量倍數 (策略10)", min_value=1.2, max_value=5.0, value=2.0, step=0.2)

    enable_box_bottom_surge = st.checkbox("11. 箱底爆大量長多起漲(含漲停基因+均線標示)", value=True)
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        b11_days = st.number_input("箱型天數 (策略11)", min_value=30, max_value=250, value=120)
        b11_vol_mult = st.number_input("爆量倍數 (策略11)", min_value=1.2, max_value=5.0, value=2.0, step=0.2)
    with col_n2:
        b11_limit_days = st.number_input("幾天內有漲停", min_value=10, max_value=120, value=60)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=9.5, step=0.5)

    btn_quick_search = st.button("🚀 執行組合潛力股挖掘", use_container_width=True, type="primary")

    st.divider()
    st.subheader("🩺 個股即時 K 線圖診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 3231")
    diag_btn = st.button("🔎 產出即時 K 線圖", use_container_width=True)


# ==========================================
# 6. 右側主畫面區塊
# ==========================================
st.title("📈 台股智慧選股與即時 K 線診斷系統")
st.caption("支援 11 大模組組合篩選、箱底爆大量長多起漲點挖掘與即時 K 線診斷。")
st.divider()

if diag_btn and diag_code:
    with st.spinner(f"正在從 FinMind 擷取 {diag_code} 歷史數據並繪製即時 K 線圖..."):
        df_diag = get_finmind_data(diag_code)
        if df_diag is not None and not df_diag.empty:
            stock_list_df = get_taiwan_stock_list()
            matched_row = stock_list_df[stock_list_df['code'] == str(diag_code)]
            s_name = matched_row['name'].values[0] if not matched_row.empty else "未知公司"
            
            st.success(f"📊 股票代號 {diag_code} - {s_name} 即時 K 線圖診斷報告")
            fig_diag = plot_beautified_chart(df_diag, f"{diag_code} {s_name} 即時診斷", 20, enable_first_limit=True, first_limit_days=30)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 查無 {diag_code} 的歷史數據，請確認代號是否正確。")

st.subheader("📋 搜尋股票結果清單")

if btn_quick_search:
    with st.spinner("⚡ 正在透過多執行緒高速掃描全市場..."):
        res_df = run_quick_screener_parallel(
            enable_macd_25ma, macd_ma_period,
            enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
            enable_kd_cross, enable_tangle_steady, tangle_ma_period,
            enable_breakout, enable_vcp,
            enable_first_limit_pullback, first_limit_days, first_limit_range,
            enable_shakeout_breakout, shakeout_ma_val,
            enable_box_breakout, box_days,
            enable_box_volume_accum, box10_days, box10_vol_mult,
            enable_box_bottom_surge, b11_days, b11_vol_mult, b11_limit_days,
            logic_mode, min_vol, max_growth
        )
        st.session_state.screener_results = res_df
        st.session_state.selected_stock_index = 0

res_table = st.session_state.screener_results
if not res_table.empty:
    st.success(f"🎉 掃描完成！共找到 `{len(res_table)}` 檔符合條件的優質標的：")
    
    display_df = res_table.copy()
    display_df['股票名稱連結'] = display_df.apply(
        lambda r: f"https://www.wantgoo.com/stock/{r['股票代號']}/technical-chart", axis=1
    )
    cols_to_show = ["股票代號", "股票名稱", "股票名稱連結", "組合邏輯名稱", "站穩均線狀態", "當日漲幅(%)", "近N日漲停次數", "成交量(張)", "收盤價"]
    st.dataframe(
        display_df[cols_to_show],
        column_config={
            "股票名稱連結": st.column_config.LinkColumn("WantGoo 技術分析連結", display_text="點擊開啟圖表")
        },
        use_container_width=True,
        hide_index=True
    )

    st.divider()
    st.subheader("📈 詳細美化 K 線圖與快速瀏覽 (支援左右按鈕與鍵盤方向鍵)")

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
            format_func=lambda x: f"({stock_list.index(x)+1}/{total_stocks}) {x} - {res_table[res_table['股票代號']==x]['股票名稱'].values[0]} ({res_table[res_table['股票代號']==x]['組合邏輯名稱'].values[0]})",
            key="selectbox_stock_changer"
        )
        if selected_stock in stock_list:
            new_idx = stock_list.index(selected_stock)
            if new_idx != st.session_state.selected_stock_index:
                st.session_state.selected_stock_index = new_idx
                st.rerun()

    components.html("""
        <script>
        const doc = window.parent.document;
        
        const buttons = Array.from(doc.querySelectorAll('button'));
        buttons.forEach(btn => {
            if (btn.innerText.includes('上一檔')) btn.setAttribute('data-hotkey', 'prev');
            if (btn.innerText.includes('下一檔')) btn.setAttribute('data-hotkey', 'next');
        });

        if (!doc.dataset.keydownInitialized) {
            doc.dataset.keydownInitialized = "true";
            doc.addEventListener('keydown', function(e) {
                if (['input', 'textarea', 'select'].includes(e.target.tagName.toLowerCase())) {
                    return;
                }
                
                if (e.key === 'ArrowLeft') {
                    const prevBtn = doc.querySelector('button[data-hotkey="prev"]');
                    if (prevBtn) {
                        prevBtn.click();
                        e.preventDefault();
                    }
                } else if (e.key === 'ArrowRight') {
                    const nextBtn = doc.querySelector('button[data-hotkey="next"]');
                    if (nextBtn) {
                        nextBtn.click();
                        e.preventDefault();
                    }
                }
            });
        }
        </script>
    """, height=0)

    if selected_stock:
        with st.spinner(f"正在從 FinMind 載入 {selected_stock} 的歷史日線數據與指標..."):
            df_k = get_finmind_data(selected_stock)
            if df_k is not None and not df_k.empty:
                r_row = res_table[res_table['股票代號']==selected_stock].iloc[0]
                stock_name = r_row['股票名稱']
                combo_tag = r_row['組合邏輯名稱']
                
                fig_res = plot_beautified_chart(df_k, f"({st.session_state.selected_stock_index+1}/{total_stocks}) {selected_stock} {stock_name} [{combo_tag}]", 20, enable_first_limit=True, first_limit_days=30)
                st.plotly_chart(fig_res, use_container_width=True)
            else:
                st.warning("⚠️ 無法獲取該標的的歷史數據。")
else:
    st.info("👈 請於左側勾選策略模組、設定參數，並點擊「執行組合潛力股挖掘」。")
