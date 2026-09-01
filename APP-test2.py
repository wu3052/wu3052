import time
import pandas as pd
import numpy as np
import streamlit as st
import yfinance as yf
import twstock
import plotly.graph_objects as plotly_go
from streamlit_drawable_canvas import st_canvas

# --- 1. 頁面配置與 Klyne 暗黑視覺風格 ---
st.set_page_config(page_title="Klyne 雙圖層型態選股系統", layout="wide")

st.markdown("""
<style>
    .main { background-color: #0B0E14; color: #E1E6ED; }
    div.block-container { padding-top: 1rem; padding-bottom: 1rem; }
    .stSelectbox, .stSlider, .stNumberInput { font-size: 14px; }
    .stButton>button { 
        width: 100%; border-radius: 6px; 
        background-color: #1A2130; color: #FFFFFF; 
        border: 1px solid #2D3748; transition: all 0.3s;
    }
    .stButton>button:hover { 
        background-color: #252D3E; border-color: #4A5568; 
    }
    .action-btn>button {
        background-color: #10B981 !important; color: #FFFFFF !important; font-weight: bold;
    }
    .action-btn>button:hover { background-color: #059669 !important; }
</style>
""", unsafe_allow_html=True)

# 輔助函式：代碼轉 yfinance 格式
def get_yf_ticker(code):
    return f"{code}.TW"

# --- 2. 後端核心篩選演算法 ---
@st.cache_data(ttl=300)
def get_filtered_stocks(
    market_scope, 
    search_period, 
    limit_up_filter, 
    enable_macd_ma, 
    enable_limit_up_pullback, 
    enable_kd,
    ma_param, 
    limit_up_days, 
    min_vol, 
    max_growth
):
    # 1. 判斷搜索範圍 (上市 / 上櫃 / 全部)
    all_codes = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            if market_scope == "上市" and info.market != "上市": continue
            if market_scope == "上櫃" and info.market != "上櫃": continue
            all_codes.append((code, info.name))
    
    found_targets = []
    batch_size = 60
    
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()
    total_count = len(all_codes)

    yf_tickers = [get_yf_ticker(item[0]) for item in all_codes]
    code_to_name = {item[0]: item[1] for item in all_codes}
    
    for i in range(0, total_count, batch_size):
        batch_tickers = yf_tickers[i:i+batch_size]
        current_progress = min((i + batch_size) / total_count, 1.0)
        progress_bar.progress(current_progress)
        status_text.markdown(f"⏳ **掃描進度:** `{min(i+batch_size, total_count)}/{total_count}` | 🎯 **合規:** `{len(found_targets)}` 檔")
        
        try:
            # 依週期下載歷史數據
            fetch_period = "1y" if search_period >= 120 else "6m"
            data = yf.download(batch_tickers, period=fetch_period, interval="1d", group_by='ticker', progress=False)
            
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

                    # 過濾成交量與當日漲幅上限
                    if curr_vol < (min_vol * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth: continue

                    # 近 N 日漲停次數計算 (以 > 9.5% 視為漲停)
                    df['pct_change'] = df['close'].pct_change() * 100
                    recent_df = df.iloc[-search_period:]
                    limit_up_count = int((recent_df['pct_change'] >= 9.5).sum())

                    # 漲停次數條件過濾
                    if limit_up_filter != "不限":
                        target_cnt = 5 if limit_up_filter == "5次以上" else int(limit_up_filter.replace("次", ""))
                        if limit_up_filter == "5次以上" and limit_up_count < 5: continue
                        elif limit_up_filter != "5次以上" and limit_up_count != target_cnt: continue

                    # 指標計算
                    ma_col = f"ma_{ma_param}"
                    df[ma_col] = df['close'].rolling(ma_param).mean()
                    ma_curr = df[ma_col].iloc[-1]
                    df['vol_ma5'] = df['volume'].rolling(5).mean()

                    # 策略 1: MACD 回踩 0 軸 + MA 支持
                    cond1 = True
                    if enable_macd_ma:
                        exp1 = df['close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['close'].ewm(span=26, adjust=False).mean()
                        df['dif'] = exp1 - exp2
                        df['macd_signal'] = df['dif'].ewm(span=9, adjust=False).mean()

                        dif_curr, sig_curr = df['dif'].iloc[-1], df['macd_signal'].iloc[-1]
                        dif_prev, sig_prev = df['dif'].iloc[-2], df['macd_signal'].iloc[-2]
                        
                        touch_ma = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        macd_near_zero = abs(dif_curr) < (curr_price * 0.02)
                        macd_gold = (dif_prev <= sig_prev and dif_curr > sig_curr) or (abs(dif_curr - sig_curr) < (curr_price * 0.005))
                        cond1 = touch_ma and macd_near_zero and macd_gold

                    # 策略 2: 前 N 天帶量漲停 + 量縮回踩 MA
                    cond2 = True
                    if enable_limit_up_pullback:
                        df['limit_up_vol'] = (df['pct_change'] >= 9.5) & (df['volume'] > df['vol_ma5'] * 1.3)
                        had_limit_up = df['limit_up_vol'].iloc[-limit_up_days:].any()
                        vol_contract = curr_vol < df['vol_ma5'].iloc[-1]
                        touch_ma = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        cond2 = had_limit_up and vol_contract and touch_ma

                    # 策略 3: 日 KD 金叉
                    cond3 = True
                    if enable_kd:
                        low_9 = df['low'].rolling(9).min()
                        high_9 = df['high'].rolling(9).max()
                        rsv = (df['close'] - low_9) / (high_9 - low_9) * 100
                        df['k'] = rsv.ewm(com=2).mean()
                        df['d'] = df['k'].ewm(com=2).mean()
                        cond3 = (df['k'].iloc[-2] <= df['d'].iloc[-2]) and (df['k'].iloc[-1] > df['d'].iloc[-1])

                    if not (cond1 and cond2 and cond3): continue

                    sid = ticker.split('.')[0]
                    found_targets.append({
                        "股票代號": sid,
                        "股票名稱": code_to_name.get(sid, "未知"),
                        "當日漲幅(%)": round(change_pct, 2),
                        f"近{search_period}日漲停次數": limit_up_count,
                        "成交量(張)": int(curr_vol / 1000),
                        "當前價格": round(curr_price, 2)
                    })
                except: continue
        except: continue

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 3. 左側版面設置 (Sidebar)
# ==========================================
with st.sidebar:
    st.header("🎛️ 篩選控制台")
    st.divider()

    # 1. 搜尋週期 (20, 60, 90, 120, 240日 輪軸選單)
    search_period = st.select_slider(
        "1. 搜尋週期",
        options=[20, 60, 90, 120, 240],
        value=60,
        format_func=lambda x: f"{x}日"
    )

    # 2. 搜索範圍 (下拉式選單)
    market_scope = st.selectbox(
        "2. 搜索範圍",
        ["上市上櫃", "上市", "上櫃"]
    )

    # 3. 近期漲停次數 (下拉式選單)
    limit_up_filter = st.selectbox(
        "3. 近期漲停次數",
        ["不限", "0次", "1次", "2次", "3次", "4次", "5次", "5次以上"]
    )

    st.divider()
    
    # 5. 全市場潛力股挖掘 (快速搜索)
    st.subheader("5. 全市場潛力股挖掘 (快速搜索)")
    
    ma_param = st.number_input("MA 均線天數設定", min_value=2, max_value=240, value=25)
    limit_up_days = st.number_input("帶量漲停回溯天數 (N天)", min_value=1, max_value=60, value=20)
    
    enable_macd_ma = st.checkbox(f"1. MACD 回踩 0 軸 + {ma_param}MA 支持", value=True)
    enable_limit_up_pullback = st.checkbox(f"2. 前{limit_up_days}天帶量漲停 + 量縮回踩 {ma_param}MA", value=True)
    enable_kd = st.checkbox("3. 僅顯示 KD 金叉 (日)", value=False)
    
    min_vol = st.number_input("成交量大於 (張)", value=500, step=100)
    max_growth = st.number_input("當日漲幅小於 (%)", value=5.0, step=0.5)

    btn_search = st.button("🚀 執行全市場快搜", use_container_width=True)

    st.divider()
    
    # 6. 個股即時診斷
    st.subheader("6. 個股即時診斷")
    diag_code = st.text_input("輸入股票代號", placeholder="例如: 2330")
    if st.button("🔎 開始診斷"):
        if diag_code:
            try:
                df_diag = yf.download(get_yf_ticker(diag_code), period="6m", progress=False)
                if not df_diag.empty:
                    last_price = df_diag['Close'].iloc[-1]
                    st.success(f"**{diag_code}** 當前收盤價: `{last_price:.2f}`")
                else:
                    st.error("查無此股票資料")
            except Exception as e:
                st.error("診斷失敗，請確認代碼。")


# ==========================================
# 4. 右側版面設置 (如 Klyne.cn 附圖所示)
# ==========================================

# 右側上排工具列 (頂部條)
top_col1, top_col2, top_col3, top_col4 = st.columns([1.5, 2, 2.5, 2])

with top_col1:
    only_pattern = st.toggle("只看型態", value=False)

with top_col2:
    time_frame = st.selectbox(
        "K線週期",
        ["日線", "周線", "15分", "30分", "60分"],
        label_visibility="collapsed"
    )

with top_col3:
    layer_mode = st.radio(
        "繪圖圖層",
        ["① 形態 (橘色)", "② 均線 (紫色)"],
        horizontal=True,
        label_visibility="collapsed"
    )

with top_col4:
    canvas_ma_setting = st.selectbox(
        "均線參數",
        [f"MA{ma_param}", "MA5", "MA10", "MA20", "MA60"],
        label_visibility="collapsed"
    )

# 設定筆刷顏色：形態=橘色 (#FF9F43)，均線=紫色 (#9E57E5)
stroke_color = "#FF9F43" if "①" in layer_mode else "#9E57E5"

# 4. 繪圖畫布區域 (複製 Klyne 風格暗黑背景)
st.markdown("<p style='text-align: right; color: #718096; font-size: 12px;'>第 1 步：畫 K 線形態 ➔ 第 2 步：畫 MA 均線</p>", unsafe_allow_html=True)

canvas_result = st_canvas(
    fill_color="rgba(255, 255, 255, 0)",
    stroke_width=3,
    stroke_color=stroke_color,
    background_color="#0D1117",
    height=360,
    drawing_mode="freedraw",
    key="canvas_klyne_main",
)

# 畫布下方控制按鈕列
btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([4, 1.5, 1.5, 2])

with btn_col1:
    st.markdown('<div class="action-btn">', unsafe_allow_html=True)
    search_by_canvas = st.button("請畫完型態與均線（搜索股票）", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

with btn_col2:
    clear_last = st.button("清除當前線", use_container_width=True)

with btn_col3:
    clear_all = st.button("清空", use_container_width=True)

with btn_col4:
    upload_k = st.button("📤 上傳K線圖識別", use_container_width=True)


st.divider()

# ==========================================
# 5. 搜尋結果顯示區 (包含下拉式 K 線圖)
# ==========================================
st.subheader("3. 搜尋結果")

if btn_search or search_by_canvas:
    results_df = get_filtered_stocks(
        market_scope=market_scope,
        search_period=search_period,
        limit_up_filter=limit_up_filter,
        enable_macd_ma=enable_macd_ma,
        enable_limit_up_pullback=enable_limit_up_pullback,
        enable_kd=enable_kd,
        ma_param=ma_param,
        limit_up_days=limit_up_days,
        min_vol=min_vol,
        max_growth=max_growth
    )
    st.session_state.search_results_df = results_df

if 'search_results_df' in st.session_state:
    res_df = st.session_state.search_results_df
    
    if not res_df.empty:
        st.success(f"🎉 共找到 `{len(res_df)}` 檔符合條件之標的！")
        
        # 顯示主要數據表格
        st.dataframe(res_df, use_container_width=True, hide_index=True)
        
        # 下拉式 K 線圖預覽
        st.markdown("#### 📈 下拉展開 K 線圖細節預覽")
        selected_stock = st.selectbox(
            "選擇要查看 K 線圖的股票：",
            options=res_df["股票代號"] + " " + res_df["股票名稱"]
        )
        
        if selected_stock:
            selected_code = selected_stock.split()[0]
            with st.spinner(f"正在加載 {selected_stock} K 線圖..."):
                df_k = yf.download(get_yf_ticker(selected_code), period="6m", interval="1d", progress=False)
                
                if not df_k.empty:
                    if isinstance(df_k.columns, pd.MultiIndex):
                        df_k.columns = df_k.columns.get_level_values(0)
                    df_k.columns = [str(c).lower().strip() for c in df_k.columns]

                    fig = plotly_go.Figure()
                    fig.add_trace(plotly_go.Candlestick(
                        x=df_k.index, open=df_k['open'], high=df_k['high'],
                        low=df_k['low'], close=df_k['close'], name="K線"
                    ))
                    
                    # 疊加選擇的 MA 均線
                    ma_series = df_k['close'].rolling(ma_param).mean()
                    fig.add_trace(plotly_go.Scatter(
                        x=df_k.index, y=ma_series,
                        line=dict(color='#9E57E5', width=2),
                        name=f"MA{ma_param}"
                    ))

                    fig.update_layout(
                        template="plotly_dark",
                        height=400,
                        margin=dict(l=10, r=10, t=30, b=10),
                        xaxis_rangeslider_visible=False
                    )
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("⚠️ 未能篩選出符合條件的股票，請調鬆篩選標準或更改型態筆刷。")
else:
    st.info("👈 請於左側設定條件後點擊「執行全市場快搜」，或畫完型態後點擊「請畫完型態與均線（搜索股票）」。")
