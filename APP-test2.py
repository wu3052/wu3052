import streamlit as st
import twstock
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from streamlit_drawable_canvas import st_canvas
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- 全域頁面設定 (Dark Theme) ---
st.set_page_config(page_title="DUAL-MA CANVAS 雙均線與形態選股系統", layout="wide")

# 套用與圖片 1:1 高度還原的暗色調 CSS 風格
st.markdown("""
<style>
    .stApp { background-color: #0A0D14; color: #9EADB9; }
    div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
    
    /* 頂部工具列 */
    .top-bar { display: flex; align-items: center; justify-content: space-between; background-color: #121722; padding: 8px 16px; border-radius: 6px; border: 1px solid #1E2638; margin-bottom: 10px; }
    
    /* 底部三步驟卡片 */
    .step-card { background-color: #121725; border: 1px solid #1E293B; border-radius: 8px; padding: 12px 16px; height: 100%; }
    .step-number { font-size: 1.5rem; font-weight: bold; color: #1E293B; float: right; margin-top: -10px; }
    .step-title { font-size: 0.95rem; font-weight: bold; color: #E2E8F0; margin-bottom: 4px; }
    .step-desc { font-size: 0.75rem; color: #64748B; }

    /* 按鈕與選單外觀 */
    .stButton>button { background-color: #1E2638; color: #94A3B8; border: 1px solid #334155; border-radius: 6px; }
    .stButton>button:hover { background-color: #2A364F; color: #F8FAFC; border-color: #475569; }
</style>
""", unsafe_allow_html=True)

# 模擬台股轉 Yahoo Finance Code
def get_yf_ticker(code):
    return f"{code}.TW"

# --- 全市場篩選引擎 ---
@st.cache_data(ttl=60)
def run_stock_screener(
    search_period,
    market_range,
    limit_up_filter,
    ma_target,
    limit_up_lookback,
    use_macd,
    use_limit_up,
    use_kd,
    min_vol,
    max_growth
):
    all_codes = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            # 依選單過濾市場種類
            if market_range == "上市" and info.market != "上市": continue
            if market_range == "上櫃" and info.market != "上櫃": continue
            all_codes.append(get_yf_ticker(code))
    
    found_targets = []
    batch_size = 80
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_count = len(all_codes)
    
    for i in range(0, total_count, batch_size):
        batch = all_codes[i:i+batch_size]
        progress_bar.progress(min(i / total_count, 1.0))
        status_text.markdown(f"🔍 **掃描進度:** `{i}/{total_count}` | 🔥 **符合條件:** `{len(found_targets)}` 檔")
        
        try:
            data = yf.download(batch, period=f"{search_period}d", interval="1d", group_by='ticker', progress=False)
            
            for ticker in batch:
                try:
                    df = data[ticker].copy() if len(batch) > 1 else data.copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) < 40: continue
                    
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    df = df.rename(columns={"adj close": "close"})

                    curr_price = df['close'].iloc[-1]
                    prev_close = df['close'].iloc[-2]
                    curr_vol = df['volume'].iloc[-1]

                    # 基礎量能與漲幅過濾
                    if curr_vol < (min_vol * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth: continue

                    # 漲停次數統計 (日漲幅 >= 9.5%)
                    df['daily_pct'] = ((df['close'] - df['close'].shift(1)) / df['close'].shift(1)) * 100
                    limit_up_count = (df['daily_pct'].iloc[-search_period:] >= 9.5).sum()

                    # 近期漲停次數條件判斷
                    if limit_up_filter != "不限":
                        target_cnt = 5 if limit_up_filter == "5次以上" else int(limit_up_filter.replace("次", ""))
                        if limit_up_filter == "5次以上" and limit_up_count < 5: continue
                        elif limit_up_filter != "5次以上" and limit_up_count != target_cnt: continue

                    # 均線指標
                    ma_col = f"ma_{ma_target}"
                    df[ma_col] = df['close'].rolling(ma_target).mean()
                    ma_curr = df[ma_col].iloc[-1]
                    df['vol_ma5'] = df['volume'].rolling(5).mean()

                    # --- 條件 1: MACD 回踩 0 軸 + 指定 MA 支持 ---
                    cond_macd_pass = True
                    if use_macd:
                        exp1 = df['close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['close'].ewm(span=26, adjust=False).mean()
                        df['dif'] = exp1 - exp2
                        df['macd_signal'] = df['dif'].ewm(span=9, adjust=False).mean()

                        dif_curr, sig_curr = df['dif'].iloc[-1], df['macd_signal'].iloc[-1]
                        dif_prev, sig_prev = df['dif'].iloc[-2], df['macd_signal'].iloc[-2]

                        ma_support = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        near_zero = abs(dif_curr) < (curr_price * 0.02)
                        macd_cross = (dif_prev <= sig_prev and dif_curr > sig_curr) or (abs(dif_curr - sig_curr) < (curr_price * 0.005))
                        cond_macd_pass = ma_support and near_zero and macd_cross

                    # --- 條件 2: 前 N 天帶量漲停 + 量縮回踩指定 MA ---
                    cond_limit_up_pass = True
                    if use_limit_up:
                        df['is_limit_vol'] = (df['daily_pct'] >= 9.5) & (df['volume'] > df['vol_ma5'] * 1.3)
                        had_limit = df['is_limit_vol'].iloc[-limit_up_lookback:].any()
                        vol_contract = curr_vol < df['vol_ma5'].iloc[-1]
                        ma_touch = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        cond_limit_up_pass = had_limit and vol_contract and ma_touch

                    # --- 條件 3: KD 金叉 (日) ---
                    cond_kd_pass = True
                    if use_kd:
                        low9 = df['low'].rolling(9).min()
                        high9 = df['high'].rolling(9).max()
                        rsv = (df['close'] - low9) / (high9 - low9) * 100
                        k = rsv.ewm(com=2).mean()
                        d = k.ewm(com=2).mean()
                        cond_kd_pass = (k.iloc[-2] <= d.iloc[-2]) and (k.iloc[-1] > d.iloc[-1])

                    if use_macd and not cond_macd_pass: continue
                    if use_limit_up and not cond_limit_up_pass: continue
                    if use_kd and not cond_kd_pass: continue

                    sid = ticker.split('.')[0]
                    found_targets.append({
                        "追蹤": False,
                        "股價代號": sid,
                        "當前價格": round(curr_price, 2),
                        "當日漲幅%": round(change_pct, 2),
                        "近N日漲停次數": int(limit_up_count),
                        "成交量(張)": int(curr_vol / 1000),
                        f"{ma_target}MA": round(ma_curr, 2)
                    })
                except: continue
        except: continue

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 左側版面設置 (側邊欄控制中心)
# ==========================================
with st.sidebar:
    st.header("🎛️ 篩選控制面板")
    st.divider()

    # 1. 搜尋週期 (由右至左輪軸/Slider)
    st.subheader("1. 搜尋週期")
    search_period = st.select_slider(
        "選擇計算區間天數",
        options=[240, 120, 90, 60, 20],  # 由右至左視覺排序
        value=90
    )

    # 2. 搜索範圍 (下拉選單)
    st.subheader("2. 搜索範圍")
    market_range = st.selectbox("市場類別", ["上市上櫃", "上市", "上櫃"], index=0)

    # 3. 近期漲停次數 (下拉選單)
    st.subheader("3. 近期漲停次數")
    limit_up_filter = st.selectbox(
        "篩選漲停頻率",
        ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"],
        index=0
    )

    st.divider()

    # 4. 全市場潛力股挖掘 (快速搜索)
    st.subheader("4. 全市場潛力股挖掘 (快速搜索)")
    
    # 可修改參數
    col_param1, col_param2 = st.columns(2)
    with col_param1:
        ma_target = st.number_input("均線 (MA)", min_value=1, max_value=240, value=25, step=1)
    with col_param2:
        limit_up_lookback = st.number_input("漲停回溯天數", min_value=1, max_value=60, value=20, step=1)

    use_macd = st.checkbox(f"1. MACD 回踩 0 軸 + {ma_target}MA 支持", value=True)
    use_limit_up = st.checkbox(f"2. 前{limit_up_lookback}天帶量漲停 + 量縮回踩 {ma_target}MA", value=True)
    use_kd = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)

    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_run_screener = st.button("🚀 執行全場潛力股挖掘", use_container_width=True)

    st.divider()

    # 5. 個股即時診斷
    st.subheader("5. 個股即時診斷")
    diag_code = st.text_input("輸入股票代碼", placeholder="例如: 2330")
    btn_diag = st.button("🔎 立即診斷個股", use_container_width=True)
    
    if btn_diag and diag_code:
        with st.spinner(f"正在分析 {diag_code}..."):
            df_diag = yf.download(get_yf_ticker(diag_code), period="6m", interval="1d", progress=False)
            if not df_diag.empty:
                st.success(f"【{diag_code}】診斷完成！")
                st.metric("最新收盤價", f"{df_diag['Close'].iloc[-1]:.2f}")
            else:
                st.error("查無該股票數據。")


# ==========================================
# 右側版面設置 (完全對照截圖 Layout)
# ==========================================

# 1. 頂部狀態與控制列
st.markdown("""
<div class="top-bar">
    <div style="display:flex; align-items:center; gap:12px;">
        <span style="font-weight:bold; color:#00E699; font-size:1.1rem;">● DUAL-MA CANVAS</span>
        <span style="font-size:0.8rem; color:#64748B;">| 分鐘緩存已就緒 · 滬深5,488只 · 截至2026-09-01 15:00</span>
    </div>
    <div style="font-size:0.85rem; color:#00E699;">第 1 步: 畫K線形態</div>
</div>
""", unsafe_allow_html=True)

# 工具按鈕組合列 (模仿截圖選項)
top_col1, top_col2, top_col3, top_col4, top_col5 = st.columns([1.5, 1.2, 1.2, 1.2, 5])
with top_col1:
    st.toggle("僅著形態", value=False)
with top_col2:
    st.selectbox("週期", ["日線", "週線", "60分鐘"], index=0, label_visibility="collapsed")
with top_col3:
    st.button("① 形態", use_container_width=True)
with top_col4:
    st.button("② 均線 MA20", use_container_width=True)
with top_col5:
    st.selectbox("選擇均線", [f"MA{ma_target}", "MA5", "MA10", "MA60"], index=0, label_visibility="collapsed")

# 2. 中央手繪畫布區域 (模仿截圖坐標與提示)
st.markdown("""
<div style="display:flex; justify-between:space-between; font-size:0.75rem; color:#475569; margin-top:5px;">
    <span>高</span>
    <span>時間週期: 最近 90 個交易日 (從左到右 = 過去 → 現在)</span>
    <span>相對位置: 低 ~ 高</span>
</div>
""", unsafe_allow_html=True)

# 畫布區域
canvas_result = st_canvas(
    fill_color="rgba(0, 0, 0, 0)",
    stroke_width=2,
    stroke_color="#00E699",
    background_color="#0A0D14",
    height=360,
    width=None,
    drawing_mode="freedraw",
    key="dual_ma_canvas",
)

# 3. 畫布下方控制與上傳列 (複製圖片按鈕配置)
c_btn1, c_btn2, c_btn3, c_btn4 = st.columns([4, 1, 1, 2])
with c_btn1:
    st.button(f"請畫完形態與均線（形態 ... / 均線 MA{ma_target} ...）", use_container_width=True, disabled=True)
with c_btn2:
    st.button("清當前線", use_container_width=True)
with c_btn3:
    st.button("清空", use_container_width=True)
with c_btn4:
    st.button("📤 上傳K線圖識別", use_container_width=True)

st.caption("<div style='text-align:right; font-size:0.75rem;'>建議上傳帶 MA5 均線的 K 線圖，識別更貼合匹配口徑</div>", unsafe_allow_html=True)
st.divider()

# 4. 底部 3 步驟操作指南卡片 (複製圖片三欄卡片配置)
step_col1, step_col2, step_col3 = st.columns(3)

with step_col1:
    st.markdown("""
    <div class="step-card">
        <span class="step-number">01</span>
        <div class="step-title">✏️ 繪制形態</div>
        <div class="step-desc">先畫 K 線形態再畫均線，可隨時切換圖層重畫</div>
    </div>
    """, unsafe_allow_html=True)

with step_col2:
    st.markdown("""
    <div class="step-card">
        <span class="step-number">02</span>
        <div class="step-title">⚙️ 調整參數</div>
        <div class="step-desc">頂部選均線週期，左側調週期、漲停與返回數量</div>
    </div>
    """, unsafe_allow_html=True)

with step_col3:
    st.markdown("""
    <div class="step-card">
        <span class="step-number">03</span>
        <div class="step-title">📊 查看結果</div>
        <div class="step-desc">結果在下方網格展示，點擊卡片彈出完整 K 線</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# 5. 選股匹配結果渲染區塊
if btn_run_screener:
    st.session_state.screener_results = run_stock_screener(
        search_period=search_period,
        market_range=market_range,
        limit_up_filter=limit_up_filter,
        ma_target=ma_target,
        limit_up_lookback=limit_up_lookback,
        use_macd=use_macd,
        use_limit_up=use_limit_up,
        use_kd=use_kd,
        min_vol=min_vol,
        max_growth=max_growth
    )

if 'screener_results' in st.session_state and not st.session_state.screener_results.empty:
    res = st.session_state.screener_results
    st.success(f"✅ 匹配完成，共挖掘出 `{len(res)}` 檔符合形態標的：")
    
    st.data_editor(
        res,
        column_config={"追蹤": st.column_config.CheckboxColumn(default=False)},
        hide_index=True,
        use_container_width=True
    )
else:
    # 未執行時呈現如圖片底部的預設空狀態圖示
    st.markdown("""
    <div style="text-align:center; padding: 40px; color:#334155;">
        <div style="font-size: 3rem;">📊</div>
        <div style="font-weight:bold; color:#64748B; margin-top:8px;">畫好兩條均線或點擊左側「執行」開始匹配</div>
        <div style="font-size:0.8rem; color:#475569; margin-top:4px;">系統將對齊最新交易日，找出雙均線形態最像的股票</div>
    </div>
    """, unsafe_allow_html=True)
