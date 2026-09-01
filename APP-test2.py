import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import plotly.graph_objects as plotly_go
from streamlit_drawable_canvas import st_canvas

# --- 設定頁面為寬螢幕模式與暗色系主題 ---
st.set_page_config(page_title="Klyne 雙線形態選股系統", layout="wide", initial_sidebar_state="expanded")

# CSS 注入：優化元件間距，防範頂部工具列被欄位遮擋
st.markdown("""
<style>
    .main { background-color: #0B0E14; }
    div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stSelectbox, .stSlider, .stNumberInput { margin-bottom: 0px; }
    /* 卡片區塊樣式 */
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

# 獲取台股清單輔助函式
@st.cache_data(ttl=3600)
def get_taiwan_stock_list(market_scope="上市上櫃"):
    stock_data = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            stock_data.append({"code": code, "name": info.name, "ticker": f"{code}.TW" if info.market == "上市" else f"{code}.TWO"})
    return pd.DataFrame(stock_data)

# 掃描邏輯（快速搜尋）
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
        status_text.markdown(f"🔍 **進度:** `{i}/{total_count}` | 🔥 **符合標的:** `{len(found_targets)}` 檔")
        
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

                    # 1. 基本量價過濾
                    if curr_vol < (min_vol * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth: continue

                    # 2. 計算近 N 日漲停次數 (台股按 9.5% 算漲停)
                    df['daily_change'] = df['close'].pct_change() * 100
                    recent_df = df.iloc[-search_period:]
                    limit_up_count = (recent_df['daily_change'] >= 9.5).sum()

                    # 漲停次數篩選
                    if limit_up_filter != "不限":
                        target_cnt = 5 if "5次以上" in limit_up_filter else int(limit_up_filter.replace("次", ""))
                        if "5次以上" in limit_up_filter and limit_up_count < 5: continue
                        elif "5次以上" not in limit_up_filter and limit_up_count != target_cnt: continue

                    # 3. 策略判定
                    # 策略 A: MACD 回踩 0 軸 + 自訂 MA
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

                    # 策略 B: 前 N 天帶量漲停 + 量縮回踩自訂 MA
                    cond_b = True
                    if enable_limit_up_pullback:
                        df['ma_b'] = df['close'].rolling(limit_up_ma_period).mean()
                        ma_b_curr = df['ma_b'].iloc[-1]
                        df['vol_ma5'] = df['volume'].rolling(5).mean()
                        
                        # 近 N 天是否有帶量漲停
                        check_range = df.iloc[-limit_up_days:]
                        had_limit_up_vol = ((check_range['daily_change'] >= 9.5) & (check_range['volume'] > check_range['vol_ma5'] * 1.5)).any()
                        is_vol_shrink = curr_vol < df['vol_ma5'].iloc[-1]
                        is_touch_ma = (df['low'].iloc[-1] <= ma_b_curr * 1.015) and (curr_price >= ma_b_curr * 0.985)
                        
                        cond_b = had_limit_up_vol and is_vol_shrink and is_touch_ma

                    # 策略 C: 日 KD 金叉
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

    # 1. 搜尋週期 (輪軸選擇)
    search_period = st.select_slider(
        "1. 搜尋週期 (天數)",
        options=[20, 60, 90, 120, 240],
        value=60
    )

    # 2. 搜索範圍 (下拉選單)
    market_scope = st.selectbox("2. 搜索範圍", ["上市上櫃", "上市", "上櫃"])

    # 3. 近期漲停次數 (下拉選單)
    limit_up_filter = st.selectbox(
        "3. 近期漲停次數",
        ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"]
    )

    st.divider()
    # 5. 全市場潛力股挖掘 (快速搜索 - 與繪畫搜索獨立)
    st.subheader("⚡ 全市場潛力股挖掘 (快速搜索)")
    
    # 策略 1: MACD 0軸 + MA 支持
    enable_macd_25ma = st.checkbox("1. MACD 回踩 0 軸 + MA 支持", value=True)
    macd_ma_period = st.number_input("MACD 搭配均線 MA", min_value=1, max_value=240, value=25, key="macd_ma")

    # 策略 2: 前 N 天帶量漲停 + 量縮回踩 MA
    enable_limit_up_pullback = st.checkbox("2. 前 N 天帶量漲停 + 量縮回踩 MA", value=False)
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        limit_up_days = st.number_input("前 N 天", min_value=1, max_value=60, value=20)
    with col_p2:
        limit_up_ma_period = st.number_input("回踩 MA", min_value=1, max_value=240, value=25, key="lup_ma")

    # 策略 3: KD 金叉
    enable_kd_cross = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    st.divider()
    # 基本參數過濾
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_quick_search = st.button("🚀 執行全市場快速搜索", use_container_width=True)

    st.divider()
    # 6. 個股即時診斷
    st.subheader("🩺 6. 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    if st.button("🔎 開始診斷", use_container_width=True) and diag_code:
        st.info(f"正在對 {diag_code} 進行技術面與形態綜合診斷...")


# ==========================================
# 右側版面設置 (主畫面：Klyne Canvas 樣式)
# ==========================================

# 頂部控制列（參考附圖1:1佈局，使用 st.columns 避免被擋住）
top_c1, top_c2, top_c3, top_c4, top_c5 = st.columns([1.2, 1.2, 1.2, 1.2, 1.2])

with top_c1:
    only_pattern = st.toggle("僅看形態", value=False)

with top_c2:
    chart_k_period = st.selectbox(
        "週期選單",
        ["日線", "周線", "15分", "30分", "60分"],
        label_visibility="collapsed"
    )

with top_c3:
    # 畫布圖層切換：① 形態 (橘色) / ② 均線 (紫色)
    layer_mode = st.radio(
        "圖層切換",
        ["① 形態", "② 均線"],
        horizontal=True,
        label_visibility="collapsed"
    )

with top_c4:
    ma_param = st.selectbox("均線參數", ["MA5", "MA10", "MA20", "MA60"], index=2, label_visibility="collapsed")

with top_c5:
    st.caption("🟢 已連接數據源: 護深/全台股")

# 繪圖顏色與圖層控制邏輯
stroke_color = "#FF9F43" if "①" in layer_mode else "#9E579D"
stroke_width = 3 if "①" in layer_mode else 2

# 主畫布區域
st.markdown("<p style='text-align:center; color:#6C757D; font-size:12px; margin-top:5px;'>時間週期：最近 90 個交易日 〈從左到右 = 過去 ➔ 現在〉</p>", unsafe_allow_html=True)

canvas_key = "klyne_dual_canvas"
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=stroke_width,
    stroke_color=stroke_color,
    background_color="#0D111A",
    height=360,
    width=None,
    drawing_mode="freedraw",
    key=canvas_key,
)

# 畫布下方按鈕列
btn_c1, btn_c2, btn_c3, btn_c4 = st.columns([3, 1, 1, 1.5])

with btn_c1:
    btn_draw_search = st.button("🎨 請畫完形態與均線 (搜索股票)", type="primary", use_container_width=True)

with btn_c2:
    if st.button("清除當前線", use_container_width=True):
        st.toast("已清除上一筆劃線（可重新畫圖）")

with btn_c3:
    if st.button("清空", use_container_width=True):
        st.rerun()

with btn_c4:
    st.button("📤 上傳K線圖識別", use_container_width=True)

# 底部 3 步驟指引卡片 (參考附圖)
st.markdown("<br>", unsafe_allow_html=True)
guide_c1, guide_c2, guide_c3 = st.columns(3)

with guide_c1:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">✏️ 1. 繪製形態</div>
        先畫 K 線形態再畫均線，可隨時切換圖層重畫。
    </div>
    """, unsafe_allow_html=True)

with guide_c2:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">⚙️ 2. 調整參數</div>
        頂部選均線週期，左側調週期、漲停與返回數量。
    </div>
    """, unsafe_allow_html=True)

with guide_c3:
    st.markdown("""
    <div class="step-card">
        <div class="step-title">📊 3. 查看結果</div>
        結果在下方網格展示，點擊卡片彈出完整 K 線。
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ==========================================
# 搜尋結果與選股清單展示 (支援下拉式 K 線圖)
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
    st.info("🎯 正在對手繪 K 線與均線軌跡進行形狀擬合計算，比對全市場形態中...")
    # 此處保留手繪軌跡比對觸發點

if 'screener_results' in st.session_state:
    res_df = st.session_state.screener_results
    if not res_df.empty:
        st.success(f"✅ 找到 {len(res_df)} 檔符合條件的標的：")
        st.dataframe(res_df, use_container_width=True)

        # 4. 下拉式 K 線圖查看
        st.subheader("📈 下拉選擇標的查看詳細 K 線圖")
        selected_stock = st.selectbox(
            "選擇股票代號以展開 K 線圖",
            options=res_df["股票代號"].tolist(),
            format_func=lambda x: f"{x} - {res_df[res_df['股票代號']==x]['股票名稱'].values[0]}"
        )

        if selected_stock:
            stock_ticker = f"{selected_stock}.TW"
            df_k = yf.download(stock_ticker, period="6m", interval="1d", progress=False)
            if not df_k.empty:
                if isinstance(df_k.columns, pd.MultiIndex):
                    df_k.columns = df_k.columns.get_level_values(0)
                df_k.columns = [str(c).lower().strip() for c in df_k.columns]

                fig = plotly_go.Figure()
                fig.add_trace(plotly_go.Candlestick(
                    x=df_k.index, open=df_k['open'], high=df_k['high'],
                    low=df_k['low'], close=df_k['close'], name="K線"
                ))
                # 疊加 MA25
                df_k['ma25'] = df_k['close'].rolling(25).mean()
                fig.add_trace(plotly_go.Scatter(x=df_k.index, y=df_k['ma25'], line=dict(color='#9E579D', width=2), name="MA25"))
                
                fig.update_layout(
                    template="plotly_dark",
                    height=400,
                    margin=dict(l=10, r=10, t=30, b=10),
                    xaxis_rangeslider_visible=False
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ 掃描完畢，未搜尋到符合所有條件的股票，請放寬漲幅或成交量限制。")
