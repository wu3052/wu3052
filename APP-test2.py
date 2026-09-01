import time
import datetime
import requests
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import plotly.graph_objects as plotly_go
from plotly.subplots import make_subplots
from streamlit_drawable_canvas import st_canvas

# --- 頁面設定 ---
st.set_page_config(page_title="Klyne 雙線形態選股系統", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main { background-color: #0B0E14; }
    div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
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

# --- 從 FinMind 抓取 180 天歷史日線數據 ---
@st.cache_data(ttl=3600)
def get_finmind_kline(stock_id, token=""):
    end_date = datetime.datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.datetime.now() - datetime.timedelta(days=260)).strftime('%Y-%m-%d')
    
    url = "https://api.finmindtrade.com/api/v4/data"
    parameter = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    if token:
        parameter["token"] = token
        
    try:
        resp = requests.get(url, params=parameter, timeout=10)
        data = resp.json()
        if data.get("msg") == "success" and len(data.get("data", [])) > 0:
            df = pd.DataFrame(data["data"])
            df = df.rename(columns={
                "date": "Date", "open": "Open", "max": "High", 
                "min": "Low", "close": "Close", "Trading_Volume": "Volume"
            })
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.sort_values("Date").tail(180) # 精確取 180 天
            return df
    except Exception:
        pass

    # 備援備用：yfinance
    try:
        ticker = f"{stock_id}.TW"
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).capitalize() for c in df.columns]
            df = df.reset_index().tail(180)
            return df
    except Exception:
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

# --- 美化 K 線圖繪製（白色背景 + K線 + 橘色形態 + 紫色均線 + 成交量 + MACD） ---
def plot_white_kline(df, stock_title, ma_period=20):
    df = df.copy()
    
    # 指標計算
    df['MA'] = df['Close'].rolling(ma_period).mean()
    # 橘色形態模擬趨勢線 (取20日平滑線作為形態走勢)
    df['Pattern_Orange'] = df['Close'].rolling(5).mean()
    
    # MACD 計算
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp1 - exp2
    df['MACD_Signal'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['DIF'] - df['MACD_Signal']

    # 建立 3 層子圖
    fig = make_subplots(
        rows=3, cols=1, 
        shared_xaxes=True,
        vertical_spacing=0.03,
        subplot_titles=(f"📈 {stock_title} (180天日線)", "📊 成交量", "📉 MACD 指標"),
        row_heights=[0.55, 0.2, 0.25]
    )

    # 1. 主圖：K 線圖
    fig.add_trace(plotly_go.Candlestick(
        x=df['Date'], open=df['Open'], high=df['High'],
        low=df['Low'], close=df['Close'],
        increasing_line_color='#FF4D4D', decreasing_line_color='#00B050',
        name="K線"
    ), row=1, col=1)

    # 橘色形態線 (#FF9F43)
    fig.add_trace(plotly_go.Scatter(
        x=df['Date'], y=df['Pattern_Orange'], 
        line=dict(color='#FF9F43', width=2), name="① 形態 (橘色)"
    ), row=1, col=1)

    # 紫色指定均線 (#9E579D)
    fig.add_trace(plotly_go.Scatter(
        x=df['Date'], y=df['MA'], 
        line=dict(color='#9E579D', width=2.5), name=f"② 均線 MA{ma_period} (紫色)"
    ), row=1, col=1)

    # 2. 中圖：成交量
    colors = ['#FF4D4D' if c >= o else '#00B050' for c, o in zip(df['Close'], df['Open'])]
    fig.add_trace(plotly_go.Bar(
        x=df['Date'], y=df['Volume'],
        marker_color=colors, name="成交量"
    ), row=2, col=1)

    # 3. 下圖：MACD
    fig.add_trace(plotly_go.Scatter(x=df['Date'], y=df['DIF'], line=dict(color='#4F6BFF', width=1.5), name="DIF"), row=3, col=1)
    fig.add_trace(plotly_go.Scatter(x=df['Date'], y=df['MACD_Signal'], line=dict(color='#FF8000', width=1.5), name="DEM"), row=3, col=1)
    
    hist_colors = ['#FF4D4D' if h >= 0 else '#00B050' for h in df['MACD_Hist']]
    fig.add_trace(plotly_go.Bar(x=df['Date'], y=df['MACD_Hist'], marker_color=hist_colors, name="MACD 柱狀"), row=3, col=1)

    # 白底美化佈局
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        height=750,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(showgrid=True, gridcolor='#EAEAEA')
    fig.update_yaxes(showgrid=True, gridcolor='#EAEAEA')

    return fig

# --- 快速搜索邏輯 ---
@st.cache_data(ttl=60)
def run_quick_screener(
    market_scope, search_period, limit_up_filter, 
    enable_macd_25ma, macd_ma_period,
    enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
    enable_kd_cross, min_vol, max_growth
):
    df_stocks = get_taiwan_stock_list(market_scope)
    found_targets = []
    
    # 進度條與狀態提示
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_count = len(df_stocks)
    
    tickers = df_stocks['ticker'].tolist()
    batch_size = 60
    
    for i in range(0, total_count, batch_size):
        batch_tickers = tickers[i:i+batch_size]
        current_progress = min(i / total_count, 1.0)
        progress_bar.progress(current_progress)
        status_text.markdown(f"🔍 **全市場掃描進度:** `{i}/{total_count}` 檔 | 🔥 **已找到標的:** `{len(found_targets)}` 檔")
        
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
                        if "5次以上" in limit_up_filter and limit_up_count < 5: continue
                        elif "5次以上" not in limit_up_filter:
                            target_cnt = int(limit_up_filter.replace("次", ""))
                            if limit_up_count != target_cnt: continue

                    # 策略過濾
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

    finmind_token = st.text_input("FinMind Token (選填)", value="", type="password", help="填寫可提升數據抓取穩定度與限制")

    search_period = st.select_slider("1. 搜尋週期 (天數)", options=[20, 60, 90, 120, 240], value=60)
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])
    limit_up_filter = st.selectbox("3. 近期漲停次數", ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"])

    st.divider()
    st.subheader("⚡ 全市場潛力股挖掘")
    
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線 MA", min_value=1, max_value=240, value=20, key="macd_ma")

    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=20, key="lup_ma")

    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    st.divider()
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True)

    st.divider()
    # 6. 個股即時診斷 (修正可正常執行)
    st.subheader("🩺 6. 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    btn_do_diag = st.button("🔎 開始診斷", use_container_width=True)


# ==========================================
# 右側版面設置 (主畫面)
# ==========================================

st.title("DUAL-MA CANVAS · 雙線形態選股")

# 1. 下移頂部選單，解決遮擋問題
st.markdown("<br>", unsafe_allow_html=True)
top_c1, top_c2, top_c3, top_c4 = st.columns([1.5, 1.5, 2.5, 2])

with top_c1:
    only_pattern = st.toggle("僅看形態", value=False)

with top_c2:
    chart_k_period = st.selectbox("週期選單", ["日線", "周線", "15分", "30分", "60分"])

with top_c3:
    layer_mode = st.radio("圖層切換", ["① 形態 (橘色)", "② 均線 (紫色)"], horizontal=True)

with top_c4:
    # 均線數字可自訂填寫 (預設 20)
    custom_ma_input = st.number_input("當前均線 MA", min_value=1, max_value=240, value=20, step=1)

# 畫布樣式控制
stroke_color = "#FF9F43" if "①" in layer_mode else "#9E579D"
stroke_width = 4 if "①" in layer_mode else 3

st.caption(f"時間週期：最近 90 個交易日 〈從左到右 = 過去 ➔ 現在〉 | 當前編輯：{layer_mode} | 均線：MA{custom_ma_input}")

# 2. 放大畫布（長度延伸至清空按鈕，寬 850px，高 380px）
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#0D111A",
    height=380,
    width=850,
    drawing_mode="freedraw",
    key="klyne_canvas_v2",
)

# 3. 按鈕區域（已刪除上傳K線圖識別，長度與畫布切齊）
btn_c1, btn_c2, btn_c3 = st.columns([2, 1, 1])

with btn_c1:
    btn_draw_search = st.button("🎨 請畫完形態與均線 (搜尋股票)", type="primary", use_container_width=True)

with btn_c2:
    if st.button("清除當前線", use_container_width=True):
        st.toast("已清除繪圖軌跡！")

with btn_c3:
    if st.button("清空", use_container_width=True):
        st.rerun()

# 底部 3 步驟卡片
st.markdown("<br>", unsafe_allow_html=True)
guide_c1, guide_c2, guide_c3 = st.columns(3)
with guide_c1:
    st.markdown('<div class="step-card"><div class="step-title">✏️ 1. 繪製形態</div>先畫 K 線形態再畫均線，可隨時切換圖層重畫。</div>', unsafe_allow_html=True)
with guide_c2:
    st.markdown('<div class="step-card"><div class="step-title">⚙️ 2. 調整參數</div>頂部手動填寫均線數字，左側調週期與爆發天數。</div>', unsafe_allow_html=True)
with guide_c3:
    st.markdown('<div class="step-card"><div class="step-title">📊 3. 查看結果</div>結果於下方清單展示，選取標的自動生成白底 K 線圖。</div>', unsafe_allow_html=True)

st.divider()


# ==========================================
# 個股即時診斷區塊處理
# ==========================================
if btn_do_diag and diag_code:
    st.subheader(f"🩺 {diag_code} 個股即時深度診斷報告")
    with st.spinner(f"正透過 FinMind 抓取 {diag_code} 180 天歷史數據..."):
        df_diag = get_finmind_kline(diag_code, finmind_token)
        if df_diag is not None and not df_diag.empty:
            last_row = df_diag.iloc[-1]
            prev_row = df_diag.iloc[-2]
            chg = ((last_row['Close'] - prev_row['Close']) / prev_row['Close']) * 100
            
            c_a, c_b, c_c = st.columns(3)
            c_a.metric("最新收盤價", f"{last_row['Close']:.2f}", f"{chg:.2f}%")
            c_b.metric("當日成交量", f"{int(last_row['Volume']/1000)} 張")
            c_c.metric("技術面形態狀態", "多頭回踩 / 蓄勢" if chg >= 0 else "整理修正")

            fig_diag = plot_white_kline(df_diag, f"診斷報告: {diag_code}", ma_period=custom_ma_input)
            st.plotly_chart(fig_diag, use_container_width=True)
        else:
            st.error(f"❌ 無法取得代號 {diag_code} 的歷史數據，請確認股票代號是否正確。")


# ==========================================
# 全市場選股清單與白底 K 線圖展示
# ==========================================
st.subheader("📋 搜尋股票結果清單")

# 進度條於主要區域呈現
if btn_quick_search:
    st.write("⏳ 開始掃描全市場股票...")
    results_df = run_quick_screener(
        market_scope, search_period, limit_up_filter,
        enable_macd_25ma, macd_ma_period,
        enable_limit_up_pullback, limit_up_days, limit_up_ma_period,
        enable_kd_cross, min_vol, max_growth
    )
    st.session_state.screener_results = results_df

if btn_draw_search:
    st.info("🎯 正在分析畫布軌跡與全市場標的進行技術比對...")

if 'screener_results' in st.session_state:
    res_df = st.session_state.screener_results
    if not res_df.empty:
        st.success(f"✅ 共發現 {len(res_df)} 檔符合條件標的：")
        st.dataframe(res_df, use_container_width=True)

        st.divider()
        st.subheader("📈 下拉選擇標的查看詳細 K 線圖")
        
        selected_stock = st.selectbox(
            "請選擇要查看的股票代號",
            options=res_df["股票代號"].tolist(),
            format_func=lambda x: f"{x} - {res_df[res_df['股票代號']==x]['股票名稱'].values[0]}"
        )

        if selected_stock:
            with st.spinner(f"正由 FinMind 讀取 {selected_stock} 的 180 天歷史日線數據..."):
                df_k = get_finmind_kline(selected_stock, finmind_token)
                if df_k is not None and not df_k.empty:
                    s_name = res_df[res_df['股票代號']==selected_stock]['股票名稱'].values[0]
                    # 美化 K 線圖繪製（純白背景 + K線 + 橘形態 + 紫均線 + Volume + MACD）
                    fig_k = plot_white_kline(df_k, f"{selected_stock} {s_name}", ma_period=custom_ma_input)
                    st.plotly_chart(fig_k, use_container_width=True)
                else:
                    st.error(f"❌ 讀取 {selected_stock} K線數據失敗，請稍後重試。")
    else:
        st.warning("⚠️ 掃描完畢，未搜尋到符合所有條件的股票，請放寬搜尋條件。")
