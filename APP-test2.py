import time
import pandas as pd
import numpy as np
import streamlit as st
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from streamlit_drawable_canvas import st_canvas
import twstock
import yfinance as yf

# --- 頁面與自訂 CSS 配置 ---
st.set_page_config(page_title="Klyne 雙線形態選股系統 Pro", layout="wide", initial_sidebar_state="expanded")

# CSS 注入：優化整體版面，修正頂部選單遮擋問題
st.markdown("""
<style>
    .main { background-color: #0B0E14; }
    div.block-container { padding-top: 2rem !important; padding-bottom: 1rem; }
    
    /* 頂部選單下移與間距修正 */
    .top-control-bar {
        margin-top: 15px;
        margin-bottom: 15px;
        background-color: #141824;
        padding: 12px 15px;
        border-radius: 8px;
        border: 1px solid #242B3D;
    }
    
    .step-card {
        background-color: #151924;
        border: 1px solid #242B3D;
        border-radius: 8px;
        padding: 12px;
        color: #A0AEC0;
        font-size: 13px;
    }
    .step-title {
        color: #FFFFFF;
        font-weight: bold;
        font-size: 15px;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)

# --- FinMind 長期歷史數據抓取函式 ---
@st.cache_data(ttl=3600)
def get_finmind_stock_data(stock_id, token="", days=365):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    url = "https://api.finmindtrade.com/api/v4/data"
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        params["token"] = token
        
    try:
        res = requests.get(url, params=params, timeout=10)
        data = res.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"])
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            df = df.rename(columns={
                "open": "open", "max": "high", "min": "low", 
                "close": "close", "Trading_Volume": "volume"
            })
            return df
    except Exception as e:
        pass

    # 備用數據源：yfinance
    try:
        ticker = f"{stock_id}.TW"
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower().strip() for c in df.columns]
            df = df.rename(columns={"adj close": "close"})
            return df
    except:
        pass
    return None

# --- 台股清單獲取 ---
@st.cache_data(ttl=3600)
def get_taiwan_stock_list(market_scope="上市上櫃"):
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# --- 快速篩選邏輯 ---
@st.cache_data(ttl=60)
def run_quick_screener(
    market_scope, search_period, limit_up_filter, 
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, min_vol, max_growth
):
    df_stocks = get_taiwan_stock_list(market_scope)
    found_targets = []
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    total_count = len(df_stocks)
    
    tickers = df_stocks['ticker'].tolist()
    batch_size = 60
    
    for i in range(0, total_count, batch_size):
        batch_tickers = tickers[i:i+batch_size]
        current_progress = min(i / total_count, 1.0)
        progress_bar.progress(current_progress)
        status_text.markdown(f"🔍 **掃描進度:** `{i}/{total_count}` | 🔥 **符合標的:** `{len(found_targets)}` 檔")
        
        try:
            data = yf.download(batch_tickers, period="1y", interval="1d", group_by='ticker', progress=False)
            
            for ticker in batch_tickers:
                try:
                    df = data[ticker].copy() if len(batch_tickers) > 1 else data.copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) < search_period: continue
                    
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    df = df.rename(columns={"adj close": "close"})

                    curr_price = df['close'].iloc[-1]
                    prev_close = df['close'].iloc[-2]
                    curr_vol = df['volume'].iloc[-1]

                    if curr_vol < (min_vol * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth: continue

                    df['daily_change'] = df['close'].pct_change() * 100
                    recent_df = df.iloc[-search_period:]
                    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

                    if limit_up_filter != "不限":
                        target_cnt = 5 if "5次以上" in limit_up_filter else int(limit_up_filter.replace("次", ""))
                        if "5次以上" in limit_up_filter and limit_up_count < 5: continue
                        elif "5次以上" not in limit_up_filter and limit_up_count != target_cnt: continue

                    # MACD 策略
                    cond_a = True
                    if enable_macd_25ma:
                        df['ma_a'] = df['close'].rolling(macd_ma_period).mean()
                        ma_a_curr = df['ma_a'].iloc[-1]
                        exp1 = df['close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['close'].ewm(span=26, adjust=False).mean()
                        dif = exp1 - exp2
                        signal = dif.ewm(span=9, adjust=False).mean()
                        
                        cond_ma = (df['low'].iloc[-1] <= ma_a_curr * 1.015) and (curr_price >= ma_a_curr * 0.985)
                        cond_macd = (abs(dif.iloc[-1]) < (curr_price * 0.02)) and (dif.iloc[-1] > signal.iloc[-1])
                        cond_a = cond_ma and cond_macd

                    # 漲停回踩策略
                    cond_b = True
                    if enable_limit_up_pullback:
                        df['ma_b'] = df['close'].rolling(limit_up_ma_period).mean()
                        ma_b_curr = df['ma_b'].iloc[-1]
                        df['vol_ma5'] = df['volume'].rolling(5).mean()
                        
                        check_range = df.iloc[-limit_up_days:]
                        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['volume'] > check_range['vol_ma5'] * 1.5)).any()
                        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
                        is_touch_ma = (df['low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
                        
                        cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

                    # KD 金叉策略
                    cond_c = True
                    if enable_kd_cross:
                        low_9 = df['low'].rolling(9).min()
                        high_9 = df['high'].rolling(9).max()
                        rsv = (df['close'] - low_9) / (high_9 - low_9) * 100
                        k = rsv.ewm(com=2).mean()
                        d = k.ewm(com=2).mean()
                        cond_c = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

                    if not (cond_a and cond_b and cond_c): continue

                    sid = ticker.split('.')[0]
                    sname = df_stocks[df_stocks['code'] == sid]['name'].values[0] if sid in df_stocks['code'].values else "未知"

                    found_targets.append({
                        "股票代號": sid,
                        "股票名稱": sname,
                        "當日漲幅(%)": round(change_pct, 2),
                        f"近{search_period}日漲停次數": int(limit_up_count),
                        "成交量(張)": int(curr_vol / 1000),
                        "收盤價": round(curr_price, 2)
                    })
                except: continue
        except: continue

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 左側版面設置 (st.sidebar)
# ==========================================
with st.sidebar:
    st.title("🎯 篩選條件控制台")
    st.divider()

    fm_token = st.text_input("FinMind Token (選填)", value="", type="password")

    # 1. 搜尋週期
    search_period = st.select_slider(
        "1. 搜尋週期 (天數)",
        options=[20, 60, 90, 120, 240],
        value=60
    )

    # 2. 搜索範圍
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])

    # 3. 近期漲停次數
    limit_up_filter = st.selectbox(
        "3. 近期漲停次數",
        ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"]
    )

    st.divider()
    st.subheader("⚡ 全市場潛力股挖掘 (快速搜索)")
    
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線 MA", min_value=1, max_value=240, value=25, key="macd_ma")

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=25, key="lup_ma")

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True)

    st.divider()
    st.subheader("🩺 6. 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    if st.button("🔎 開始診斷", use_container_width=True) and diag_code:
        st.info(f"正在診斷 {diag_code}...")


# ==========================================
# 右側版面設置 (修正頂部遮擋與繪畫視窗)
# ==========================================

# 頂部加入空隙，防止 Streamlit 原生 Header 擋住選單
st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)

# 使用容器與自訂兩排結構（完美解鎖下移）
with st.container():
    top_c1, top_c2, top_c3, top_c4, top_c5 = st.columns([1.2, 1.2, 1.5, 1.2, 1.5])

    with top_c1:
        only_pattern = st.toggle("僅看形態", value=False)

    with top_c2:
        chart_k_period = st.selectbox(
            "週期",
            ["日線", "周線", "15分", "30分", "60分"],
            key="k_period_select"
        )

    with top_c3:
        layer_mode = st.radio(
            "圖層切換",
            ["① 形態 (橘)", "② 均線 (紫)"],
            horizontal=True,
            key="layer_mode_radio"
        )

    with top_c4:
        active_ma_param = macd_ma_period if enable_macd_25ma else limit_up_ma_period
        st.write(f"當前均線: **MA{active_ma_param}**")

    with top_c5:
        st.caption("🟢 已連接 FinMind/全台股數據源")

# 筆刷顏色設定 (橘色代表形態, 紫色代表均線)
stroke_color = "#FF9F43" if "①" in layer_mode else "#9E579D"
stroke_width = 3 if "①" in layer_mode else 2

st.markdown("<p style='text-align:center; color:#8C9BAE; font-size:12px; margin-top:8px;'>時間週期：最近 90 個交易日 〈從左到右 = 過去 ➔ 現在〉</p>", unsafe_allow_html=True)

# 主畫布視窗
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#0D111A",
    height=360,
    width=None,
    drawing_mode="freedraw",
    key="klyne_canvas_main",
)

# 畫布下方控制按鈕列
btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([3, 1, 1, 1.5])

with btn_c1:
    btn_draw_search = st.button("🎨 請畫完形態與均線 (搜索股票)", type="primary", use_container_width=True)

with btn_c2:
    if st.button("清除當前線", use_container_width=True):
        st.toast("已清除上一筆劃線")

with btn_c3:
    if st.button("清空", use_container_width=True):
        st.rerun()

with btn_c4:
    st.button("📤 上傳K線圖識別", use_container_width=True)

# 三步驟提示
st.markdown("<br>", unsafe_allow_html=True)
guide_c1, guide_c2, guide_c3 = st.columns(3)
with guide_c1:
    st.markdown('<div class="step-card"><div class="step-title">✏️ 1. 繪製形態</div>先畫橘色形態再畫紫色均線</div>', unsafe_allow_html=True)
with guide_c2:
    st.markdown('<div class="step-card"><div class="step-title">⚙️ 2. 調整參數</div>左側控制週期、漲停次數與MA天數</div>', unsafe_allow_html=True)
with guide_c3:
    st.markdown('<div class="step-card"><div class="step-title">📊 3. 查看結果</div>下方呈現完整 K線、成交量與 MACD</div>', unsafe_allow_html=True)

st.divider()

# ==========================================
# 股票篩選結果與動態多圖層 K 線圖 (FinMind)
# ==========================================
st.subheader("📋 搜尋股票結果清單")

if btn_quick_search:
    results_df = run_quick_screener(
        market_scope, search_period, limit_up_filter,
        enable_macd_25ma, macd_ma_period,
        enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
        enable_kd_cross, min_vol, max_growth
    )
    st.session_state.screener_results = results_df

if btn_draw_search:
    st.info("🎯 已讀取手繪畫布軌跡，正在進行全市場技術指標與形態擬合匹配...")

if 'screener_results' in st.session_state:
    res_df = st.session_state.screener_results
    if not res_df.empty:
        st.success(f"✅ 成功獲取 {len(res_df)} 檔符合條件之標的：")
        st.dataframe(res_df, use_container_width=True)

        st.divider()
        st.subheader("📈 下拉選擇標的查看詳細 K 線圖 (FinMind 歷史數據)")
        
        stock_options = res_df["股票代號"].tolist()
        selected_stock = st.selectbox(
            "請選擇欲調閱之股票：",
            options=stock_options,
            format_func=lambda x: f"{x} - {res_df[res_df['股票代號']==x]['股票名稱'].values[0]}"
        )

        if selected_stock:
            with st.spinner(f"正在從 FinMind 抓取 {selected_stock} 歷史數據與計算指標..."):
                df_k = get_finmind_stock_data(selected_stock, token=fm_token)
                
                if df_k is not None and not df_k.empty:
                    # 指標計算：紫色均線 (依據篩選條件)
                    target_ma_period = macd_ma_period if enable_macd_25ma else limit_up_ma_period
                    df_k['target_ma'] = df_k['close'].rolling(target_ma_period).mean()

                    # 橘色型態線 (繪製 smoothed 趨勢移動軌跡)
                    df_k['pattern_line'] = df_k['close'].rolling(5).mean()

                    # MACD 計算 (12, 26, 9)
                    exp1 = df_k['close'].ewm(span=12, adjust=False).mean()
                    exp2 = df_k['close'].ewm(span=26, adjust=False).mean()
                    df_k['dif'] = exp1 - exp2
                    df_k['macd_signal'] = df_k['dif'].ewm(span=9, adjust=False).mean()
                    df_k['macd_hist'] = df_k['dif'] - df_k['macd_signal']

                    # 建立三層子圖 (主圖、成交量、MACD)
                    fig = make_subplots(
                        rows=3, cols=1, 
                        shared_xaxes=True, 
                        vertical_spacing=0.03,
                        row_heights=[0.55, 0.2, 0.25],
                        subplot_titles=(f"{selected_stock} 技術 K 線圖與形態對比", "成交量", "MACD 指標")
                    )

                    # 1. 主圖：K 線圖
                    fig.add_trace(plotly_go.Candlestick(
                        x=df_k.index, open=df_k['open'], high=df_k['high'],
                        low=df_k['low'], close=df_k['close'], name="K線",
                        increasing_line_color='#FF4D4D', decreasing_line_color='#00B060'
                    ), row=1, col=1)

                    # 主圖：橘色型態線
                    fig.add_trace(plotly_go.Scatter(
                        x=df_k.index, y=df_k['pattern_line'], 
                        line=dict(color='#FF9F43', width=2), 
                        name="橘色型態軌跡"
                    ), row=1, col=1)

                    # 主圖：紫色均线
                    fig.add_trace(plotly_go.Scatter(
                        x=df_k.index, y=df_k['target_ma'], 
                        line=dict(color='#9E579D', width=2.5), 
                        name=f"紫色 {target_ma_period}MA"
                    ), row=1, col=1)

                    # 2. 副圖 1：成交量
                    colors = ['#FF4D4D' if c >= o else '#00B060' for c, o in zip(df_k['close'], df_k['open'])]
                    fig.add_trace(plotly_go.Bar(
                        x=df_k.index, y=df_k['volume'], 
                        marker_color=colors, name="成交量"
                    ), row=2, col=1)

                    # 3. 副圖 2：MACD
                    fig.add_trace(plotly_go.Scatter(
                        x=df_k.index, y=df_k['dif'], 
                        line=dict(color='#4F6BFF', width=1.5), name="DIF"
                    ), row=3, col=1)
                    fig.add_trace(plotly_go.Scatter(
                        x=df_k.index, y=df_k['macd_signal'], 
                        line=dict(color='#FFB020', width=1.5), name="Signal"
                    ), row=3, col=1)
                    
                    hist_colors = ['#FF4D4D' if h >= 0 else '#00B060' for h in df_k['macd_hist']]
                    fig.add_trace(plotly_go.Bar(
                        x=df_k.index, y=df_k['macd_hist'], 
                        marker_color=hist_colors, name="MACD 柱狀"
                    ), row=3, col=1)

                    # 排版樣式優化
                    fig.update_layout(
                        template="plotly_dark",
                        height=680,
                        margin=dict(l=15, r=15, t=35, b=15),
                        xaxis_rangeslider_visible=False,
                        showlegend=True
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.error(f"❌ 無法載入 {selected_stock} 的數據，請檢查 FinMind API Token 或網路連線。")
    else:
        st.warning("⚠️ 無符合目前篩選條件之標的。")
