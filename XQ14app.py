import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time

# --- 頁面配置 ---
st.set_page_config(layout="wide", page_title="股票狙擊手", page_icon="🏹")

# 自定義 CSS 樣式
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .info-tag { font-size: 0.85em; padding: 3px 8px; border-radius: 4px; margin-right: 5px; }
    .tag-blue { background-color: #e7f5ff; color: #1971c2; }
    .tag-purple { background-color: #f3f0ff; color: #6741d9; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 LINE Messaging API 模組
# =====================
def send_line_message(msg):
    # 從 Secrets 讀取 (請確保後台名稱為 LINE_ACCESS_TOKEN 與 LINE_USER_ID)
    token = st.secrets.get("LINE_ACCESS_TOKEN")
    user_id = st.secrets.get("LINE_USER_ID")
    
    if not token or not user_id:
        return
    
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": msg}]
    }
    try:
        # 增加狀態碼檢查，若失敗可在 Streamlit Logs 查看
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code != 200:
            print(f"LINE 發送失敗: {res.text}")
    except Exception as e:
        print(f"LINE 連線錯誤: {e}")

# =====================
# 🔹 數據獲取模組
# =====================
@st.cache_data(ttl=300)
def get_stock_data(sid, token, days=1200): 
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": sid,
        "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "token": token
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values("date").reset_index(drop=True)
    except:
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

# =====================
# 🔹 核心策略分析模組
# =====================
def analyze_strategy(df):
    if df is None or len(df) < 200: return None
    
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["week_ma"] = df["close"].rolling(25).mean() 
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan) 
    
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    df["star_signal"] = False
    for i in range(1, len(df)):
        is_golden_cross = (df["ma5"].iloc[i] > df["ma10"].iloc[i]) and (df["ma5"].iloc[i-1] <= df["ma10"].iloc[i-1])
        if df["close"].iloc[i] > df["ma5"].iloc[i] and is_golden_cross:
            df.loc[df.index[i], "star_signal"] = True

    df["warning"] = ""
    df["position_type"] = "觀察中"
    df["score"] = 50
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev_row = df.iloc[-2]
    warnings = []
    
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: warnings.append("🚀 站上60分144MA(買點)")
    elif row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: warnings.append("🩸 跌破60分144MA(賣點)")
    
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: warnings.append("🏹 站上5MA(買點)")
    elif row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: warnings.append("⚠️ 跌破5MA(注意賣點)")
    
    if row["vol_ratio"] > 2.0: warnings.append("🔥 量能爆發(2倍均量)")
    if row["hist"] > 0 and row["hist"] < prev_row["hist"]: warnings.append("🎯 目標達成/紅柱縮短")
    if row["bias_20"] > 10: warnings.append("⚠️ 乖離過高")
    
    df.at[last_idx, "warning"] = " | ".join(warnings) if warnings else "趨勢穩定中"

    score_bonus = 5 if row["vol_ratio"] > 1.2 else 0
    if row["close"] > row["ma200"] and row["ma5"] > row["ma60"]:
        df.at[last_idx, "position_type"] = "超級噴發位" if row["bias_20"] > 8 else "主升段確認位"
        df.at[last_idx, "score"] = 85 + score_bonus
    elif row["close"] > row["ma20"] and row["close"] < row["ma60"]:
        df.at[last_idx, "position_type"] = "底部起漲位"
        df.at[last_idx, "score"] = 70 + score_bonus
    elif row["star_signal"]:
        df.at[last_idx, "position_type"] = "起漲發動位"
        df.at[last_idx, "score"] = 80 + score_bonus

    df["pattern"] = "一般盤整"
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    if ma_diff < 0.015: df.at[last_idx, "pattern"] = "💎 鑽石眼"
    elif row["ma5"] > row["ma10"] > row["ma20"]: df.at[last_idx, "pattern"] = "📐 黃金三角眼"
    
    return df

# =====================
# 📊 圖表繪製模組
# =====================
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], 
        low=df_plot["low"], close=df_plot["close"], name="K線",
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b', 
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71'
    ), row=1, col=1)

    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)

    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=14, color="#FFD700"), name="發動點"), row=1, col=1)

    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)

    fig.update_layout(title=title, height=700, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# =====================
# 🚀 主應用程式
# =====================
if 'search_codes' not in st.session_state:
    st.session_state.search_codes = ""
if 'inventory_codes' not in st.session_state:
    st.session_state.inventory_codes = "6257 2303 8028 2811 8374 3019 6188 6727 6643 2382 00679B"

with st.sidebar:
    st.header("🛡️ 指揮中心設定")
    
    secret_token = st.secrets.get("FINMIND_TOKEN")
    if secret_token:
        fm_token = secret_token
    else:
        fm_token = st.text_input("請輸入 FinMind Token", type="password")
    
    if not fm_token:
        st.warning("⚠️ 尚未偵測到 Token")

    st.divider()
    st.session_state.search_codes = st.text_area("🎯 狙擊個股清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存股清單", value=st.session_state.inventory_codes)
    
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控 (保持網頁開啟)")
    
    # LINE 測試按鈕：用來排除通知失敗的原因
    if st.button("🔔 測試 LINE 通知"):
        send_line_message("🏹 股票狙擊手：連線測試成功！")
        st.toast("測試訊息已發出，請檢查手機")
        
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

# 掃描邏輯
def perform_scan():
    if not fm_token:
        st.error("請先提供 FinMind Token")
        return

    scan_results = []
    
    # --- 1. 大盤戰情區 ---
    st.subheader(" 🌐 台股加權指數 (TAIEX)")
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        score = m_last["score"]
        cmd, cmd_class = ("🚀 強力買進", "buy-signal") if score >= 60 else (("🤏 少量買進", "buy-signal") if score >= 40 else ("💀 分批賣出", "sell-signal"))

        col1, col2 = st.columns([1, 2])
        with col1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with col2: st.markdown(f"<div class='status-card {cmd_class}'>指揮官指令：{cmd}</div>", unsafe_allow_html=True)
        with st.expander("大盤詳細走勢"): st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 指數"), use_container_width=True)

    st.divider()

    # --- 2. 個股掃描 ---
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None or len(df) < 200: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        
        s_row = stock_info[stock_info["stock_id"] == sid]
        s_name = s_row["stock_name"].values[0] if not s_row.empty else "未知"
        
        tags = []
        if sid in inv_list: tags.append("【庫存通知】")
        if sid in snipe_list: tags.append("【狙擊個股通知】")
        tag_str = "".join(tags)

        # 訊號觸發通知
        if last["warning"] != "趨勢穩定中" or last["star_signal"]:
            line_msg = f"{tag_str}\n股號: {sid} ({s_name})\n現價: {last['close']:.2f}\n戰情: {last['warning']}"
            if last["star_signal"]: line_msg += "\n🏹 觸發星級發動點買入訊號!"
            send_line_message(line_msg)

        border = "#ff4b4b" if last["score"] >= 75 else "#28a745" if last["score"] <= 30 else "#adb5bd"
        st.markdown(f"""
        <div style="background: white; padding: 20px; border-left: 10px solid {border}; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;">
            <div style="display: flex; justify-content: space-between;">
                <span style="font-size: 20px; font-weight: bold;">{tag_str} {sid} {s_name} ({last['close']:.2f})</span>
                <span style="background:{border}; color:white; padding:2px 10px; border-radius:10px;">評分: {last['score']}</span>
            </div>
            <div style="margin-top: 10px; color:#d9480f; font-weight:bold;">🚩 戰情提醒: {last['warning']}</div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} {s_name} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)

        scan_results.append({"代碼": sid, "名稱": s_name, "收盤價": last['close'], "分數": last['score'], "戰情提醒": last['warning']})
    
    if scan_results:
        st.subheader("🏆 本次掃描排行")
        st.dataframe(pd.DataFrame(scan_results).sort_values("分數", ascending=False), use_container_width=True, hide_index=True)

# 介面執行與自動監控循環
placeholder = st.empty()

if analyze_btn or auto_monitor:
    if auto_monitor:
        while True:
            with placeholder.container():
                perform_scan()
                st.caption(f"🔄 自動監控中... 下次更新時間: {(datetime.now() + timedelta(minutes=interval)).strftime('%H:%M:%S')}")
            time.sleep(interval * 60)
            st.rerun()
    else:
        with placeholder.container():
            perform_scan()

st.sidebar.markdown("---")
st.sidebar.caption(f"最後更新: {datetime.now().strftime('%H:%M:%S')}")
