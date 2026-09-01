import streamlit as st
import twstock
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


# --- 設定 Klyne 風格 UI ---
st.set_page_config(page_title="Klyne 智能型態選股系統", layout="wide")

# 套用 Klyne 極簡黑灰暗色系風格
st.markdown("""
<style>
    .main { background-color: #0E1117; }
    div.block-container { padding-top: 1.5rem; }
    .stButton>button { width: 100%; border-radius: 6px; background-color: #1E2638; color: #FFFFFF; border: 1px solid #364153; }
    .stButton>button:hover { background-color: #2A364F; border-color: #4F6BFF; }
</style>
""", unsafe_allow_html=True)

# 模擬全台股代碼轉換
def get_yf_ticker(code):
    return f"{code}.TW"

# --- 核心策略與選股邏輯 ---
@st.cache_data(ttl=60)
def run_custom_screener(
    enable_macd_ma=True, 
    ma_target_period=25, 
    enable_limit_up_pullback=True, 
    limit_up_lookback_days=20, 
    min_volume_limit=500, 
    max_growth_limit=5.0
):
    all_codes = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            all_codes.append(get_yf_ticker(code))
    
    found_targets = []
    batch_size = 80 
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_count = len(all_codes)
    
    for i in range(0, total_count, batch_size):
        batch = all_codes[i:i+batch_size]
        current_progress = min(i / total_count, 1.0)
        progress_bar.progress(current_progress)
        status_text.markdown(f"🔍 **掃描進度:** `{i}/{total_count}` | 🔥 **符合標的:** `{len(found_targets)}` 檔")
        
        try:
            data = yf.download(batch, period="1y", interval="1d", group_by='ticker', progress=False)
            
            for ticker in batch:
                try:
                    if len(batch) > 1:
                        if ticker not in data or data[ticker].empty: continue
                        df = data[ticker].copy()
                    else:
                        df = data.copy()
                    
                    df = df.dropna(subset=['Close'])
                    if len(df) < 100: continue
                    
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    df = df.rename(columns={"adj close": "close"})

                    curr_price = df['close'].iloc[-1]
                    prev_close = df['close'].iloc[-2]
                    curr_vol = df['volume'].iloc[-1]

                    # 基礎過濾
                    if curr_vol < (min_volume_limit * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if change_pct > max_growth_limit: continue

                    # 算指定天數均線
                    ma_col = f"ma_{ma_target_period}"
                    df[ma_col] = df['close'].rolling(ma_target_period).mean()
                    ma_curr = df[ma_col].iloc[-1]

                    df['vol_ma5'] = df['volume'].rolling(5).mean()
                    vol_ma5_curr = df['vol_ma5'].iloc[-1]

                    # --- 策略 1: MACD 回踩 0 軸 + 自訂 MA 支持 ---
                    cond_macd_strategy = True
                    if enable_macd_ma:
                        exp1 = df['close'].ewm(span=12, adjust=False).mean()
                        exp2 = df['close'].ewm(span=26, adjust=False).mean()
                        df['dif'] = exp1 - exp2
                        df['macd_signal'] = df['dif'].ewm(span=9, adjust=False).mean()

                        dif_curr = df['dif'].iloc[-1]
                        sig_curr = df['macd_signal'].iloc[-1]
                        dif_prev = df['dif'].iloc[-2]
                        sig_prev = df['macd_signal'].iloc[-2]

                        # 自訂 MA 支持 (價格接近指定 MA 均線上下 1.5%)
                        cond_ma_support = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        near_zero = abs(dif_curr) < (curr_price * 0.02)
                        macd_cross = (dif_prev <= sig_prev and dif_curr > sig_curr) or (abs(dif_curr - sig_curr) < (curr_price * 0.005))
                        
                        cond_macd_strategy = cond_ma_support and near_zero and macd_cross

                    # --- 策略 2: 前 N 天帶量漲停 + 當前量縮回踩自訂 MA ---
                    cond_limit_up_strategy = True
                    if enable_limit_up_pullback:
                        # 判定前 N 天是否有帶量漲停 (漲幅 >= 9.5% 且 成交量高於 5MA 1.5 倍)
                        df['daily_change'] = df['close'].pct_change() * 100
                        df['is_limit_up'] = (df['daily_change'] >= 9.5) & (df['volume'] > df['vol_ma5'] * 1.5)
                        
                        # 檢查近 N 天內是否有發生過
                        recent_df = df.iloc[-limit_up_lookback_days:]
                        had_limit_up = recent_df['is_limit_up'].any()
                        
                        # 當前條件：量縮 (今日成交量 < 5日均量) 且 價格觸及自訂 MA
                        is_vol_contract = curr_vol < vol_ma5_curr
                        is_touch_ma = (df['low'].iloc[-1] <= ma_curr * 1.015) and (curr_price >= ma_curr * 0.985)
                        
                        cond_limit_up_strategy = had_limit_up and is_vol_contract and is_touch_ma

                    # 綜合篩選邏輯
                    if enable_macd_ma and not cond_macd_strategy: continue
                    if enable_limit_up_pullback and not cond_limit_up_strategy: continue

                    sid = ticker.split('.')[0]
                    found_targets.append({
                        "追蹤": False,
                        "股價代號": sid,
                        "股價": round(curr_price, 2),
                        "漲幅%": round(change_pct, 2),
                        "成交量(張)": int(curr_vol / 1000),
                        f"{ma_target_period}MA": round(ma_curr, 2)
                    })
                except: continue
        except: continue

    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)


# ==========================================
# 側邊欄：參數與策略設定
# ==========================================
with st.sidebar:
    st.header("🎯 Klyne 參數控制台")
    st.divider()

    st.subheader("⚙️ 均線與量能設定")
    ma_target_period = st.number_input("自訂均線天數 (MA)", min_value=1, max_value=240, value=25, step=1)
    min_vol = st.number_input("最低成交量 (張)", value=500, step=100)
    max_pct = st.number_input("當日最高漲幅限制 (%)", value=5.0, step=0.5)

    st.divider()
    st.subheader("🔍 選股策略模式")
    
    # 策略 1
    use_macd_ma = st.checkbox(f"🎯 MACD 回踩 0 軸 + {ma_target_period}MA 支持", value=True)
    
    # 策略 2
    use_limit_up_pullback = st.checkbox(f"🔥 前 N 天帶量漲停 + 量縮回踩 {ma_target_period}MA", value=True)
    limit_up_lookback_days = st.number_input("漲停回溯天數 (N 天)", min_value=3, max_value=60, value=20, step=1, disabled=not use_limit_up_pullback)

    st.divider()
    btn_start_scan = st.button("🚀 執行全市場形態匹配選股", use_container_width=True)

# ==========================================
# 主畫面：參考 Klyne.cn 左右雙欄配置
# ==========================================
st.title("Klyne · AI 形態與均線匹配系統")
st.caption("基於手繪/自訂趨勢與均線條件，從全市場中秒級篩選符合技術面形態之標的。")

col_left, col_right = st.columns([1, 1], gap="large")

# --- 左欄：手繪型態與均線畫布 (Klyne 風格) ---
with col_left:
    st.subheader("🎨 畫布：繪製 K 線走勢與均線型態")
    st.markdown("請在下方黑框內繪製 **趨勢走勢 (黃線)** 與 **支撐均線 (藍線)**：")
    
    draw_mode = st.radio("繪製工具", ["freedraw", "line"], horizontal=True, key="draw_mode")
    stroke_color = st.color_picker("筆刷顏色 (黃色: K線趨勢 / 藍色: 均線)", "#FFD700")
    
    # Canvas 畫布
    canvas_result = st_canvas(
        fill_color="rgba(255, 165, 0, 0.3)",
        stroke_width=3,
        stroke_color=stroke_color,
        background_color="#141824",
        height=320,
        width=500,
        drawing_mode=draw_mode,
        key="klyne_canvas",
    )
    st.info(f"💡 當前判定指標：重點關聯 **{ma_target_period}MA** 支撐位與前 **{limit_up_lookback_days}** 天內之帶量爆發點。")

# --- 右欄：篩選結果與動態對比 ---
with col_right:
    st.subheader("📊 形態匹配選股結果")

    if btn_start_scan:
        screen_results = run_custom_screener(
            enable_macd_ma=use_macd_ma,
            ma_target_period=ma_target_period,
            enable_limit_up_pullback=use_limit_up_pullback,
            limit_up_lookback_days=limit_up_lookback_days,
            min_volume_limit=min_vol,
            max_growth_limit=max_pct
        )
        st.session_state.custom_screen_results = screen_results

    if 'custom_screen_results' in st.session_state:
        results = st.session_state.custom_screen_results
        if not results.empty:
            st.success(f"🎯 掃描完成！發現 `{len(results)}` 檔符合目標形態之標的。")
            
            # 使用 Data Editor 展示結果
            edited_df = st.data_editor(
                results,
                column_config={
                    "追蹤": st.column_config.CheckboxColumn(help="勾選以進行圖表擬合檢視", default=False)
                },
                disabled=["股價代號", "股價", "漲幅%", "成交量(張)", f"{ma_target_period}MA"],
                hide_index=True,
                use_container_width=True
            )
            
            # 點擊即時擬合預覽
            selected_rows = edited_df[edited_df["追蹤"] == True]
            if not selected_rows.empty:
                target_code = selected_rows.iloc[-1]["股價代號"]
                st.subheader(f"📈 標的即時對比: {target_code}")
                
                # 抓取技術圖表進行擬合預覽
                df_single = yf.download(get_yf_ticker(target_code), period="6m", interval="1d", progress=False)
                if not df_single.empty:
                    if isinstance(df_single.columns, pd.MultiIndex):
                        df_single.columns = df_single.columns.get_level_values(0)
                    df_single.columns = [str(c).lower().strip() for c in df_single.columns]
                    
                    fig = plotly_go.Figure()
                    fig.add_trace(plotly_go.Candlestick(
                        x=df_single.index,
                        open=df_single['open'], high=df_single['high'],
                        low=df_single['low'], close=df_single['close'],
                        name="K線"
                    ))
                    
                    # 計算自訂均線
                    ma_vals = df_single['close'].rolling(ma_target_period).mean()
                    fig.add_trace(plotly_go.Scatter(
                        x=df_single.index, y=ma_vals, 
                        line=dict(color='#4F6BFF', width=2), 
                        name=f"{ma_target_period}MA"
                    ))
                    
                    fig.update_layout(
                        template="plotly_dark",
                        height=350,
                        margin=dict(l=10, r=10, t=30, b=10),
                        xaxis_rangeslider_visible=False
                    )
                    st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("⚠️ 掃描完成，未發現同時滿足條件的股票，請放寬均線容忍度或量能條件。")
    else:
        st.info("👈 請於左側畫布確認型態，並點擊側邊欄「執行全市場形態匹配選股」按鈕。")
