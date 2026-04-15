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
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 Discord Webhook 模組 (美化版)
# =====================
def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        st.error("❌ 診斷：程式找不到 DISCORD_WEBHOOK_URL，請檢查 Secrets 設定！")
        return
    payload = {"content": msg}
    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            st.success("✅ Discord 訊息發送成功！")
        else:
            st.error(f"❌ Discord 回傳錯誤代碼: {res.status_code}")
    except Exception as e:
        st.error(f"❌ 發生異常: {str(e)}")

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
    
    # 技術指標計算
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 特殊均線邏輯 (模擬 60分K 的視角)
    df["ma144_60min"] = df["close"].rolling(36).mean() 
    df["ma55_60min"] = df["close"].rolling(14).mean()  
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 關鍵位判斷
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    # 星級發動點
    df["star_signal"] = False
    for i in range(1, len(df)):
        is_golden_cross = (df["ma5"].iloc[i] > df["ma10"].iloc[i]) and (df["ma5"].iloc[i-1] <= df["ma10"].iloc[i-1])
        if df["close"].iloc[i] > df["ma5"].iloc[i] and is_golden_cross:
            df.loc[df.index[i], "star_signal"] = True

    # --- 修正後的狀態初始化 ---
    df["warning_buy"] = "" 
    df["warning_sell"] = ""
    df["score"] = 50
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    buy_signals = []
    sell_signals = []
    
    # --- 買點判斷 ---
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: buy_signals.append("🏹 站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: buy_signals.append("🚀 站上60分144MA(買點)")
    if row["star_signal"]: buy_signals.append("⭐ 站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev_row["close"] <= row["upward_key"]:
        buy_signals.append("🎯 站上死亡交叉關鍵位(上漲買入)")

    # --- 賣點判斷 ---
    if row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: sell_signals.append("⚠️ 跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: sell_signals.append("📉 跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev_row["close"] >= prev_row["ma55_60min"]: sell_signals.append("🩹 跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: sell_signals.append("🩸 跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev_row["close"] >= row["downward_key"]:
        sell_signals.append("🚫 跌破黃金交叉關鍵位(下跌賣出)")

    # --- 評分邏輯修正 ---
    current_score = 50
    if buy_signals: current_score += (len(buy_signals) * 10)
    if sell_signals: current_score -= (len(sell_signals) * 15)

    # 寫入最後一行
    df.at[last_idx, "score"] = max(10, min(current_score, 100))
    df.at[last_idx, "warning_buy"] = " / ".join(buy_signals)
    df.at[last_idx, "warning_sell"] = " / ".join(sell_signals)

    # 型態判斷
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
# 📂 Google Sheets 數據讀取模組
# =====================
def get_list_from_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return "", ""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df_sheet = pd.read_csv(url)
        def clean_codes(series):
            if series is None or series.empty: return []
            return [str(c).split('.')[0].strip() for c in series.dropna() if str(c).strip()]
        return " ".join(clean_codes(df_sheet.get('snipe_list'))), " ".join(clean_codes(df_sheet.get('inventory_list')))
    except:
        return "", ""

# =====================
# 🚀 整合與主程式邏輯
# =====================
fm_token = st.secrets.get("FINMIND_TOKEN", "")
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}

with st.sidebar:
    st.header("🛡️ 指揮中心設定")
    fm_token = st.text_input("FinMind Token", value=fm_token, type="password")
    
    if 'search_codes' not in st.session_state or st.button("🔄 同步 Google 表格清單"):
        s_list, i_list = get_list_from_sheets()
        st.session_state.search_codes, st.session_state.inventory_codes = s_list, i_list
        st.toast("✅ 清單已同步")

    st.divider()
    st.session_state.search_codes = st.text_area("🎯 狙擊個股清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存股清單", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控 (保持網頁開啟)")
    if st.button("🔔 測試 Discord 通知"): send_discord_message("🏹 股票狙擊手：Discord 連線測試成功！")
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

def perform_scan(is_auto=False):
    now_taiwan = datetime.utcnow() + timedelta(hours=8)
    weekday, current_time = now_taiwan.weekday(), now_taiwan.time()
    start_time, end_time = datetime.strptime("08:55", "%H:%M").time(), datetime.strptime("14:00", "%H:%M").time()
    
    if is_auto and not (0 <= weekday <= 4 and start_time <= current_time <= end_time):
        st.info(f"💤 當前非開盤時間 ({now_taiwan.strftime('%H:%M:%S')})，自動監控暫停中。")
        return

    # 大盤分析
    st.subheader("🌐 台股加權指數 (TAIEX)")
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        score = m_last["score"]
        
        if score >= 80: cmd, cmd_class, risk_tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強。"
        elif score >= 60: cmd, cmd_class, risk_tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中。"
        elif score >= 40: cmd, cmd_class, risk_tip = "🤏 少量買進", "buy-signal", "⚠️ 處於震盪區。"
        elif score >= 20: cmd, cmd_class, risk_tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱。"
        else: cmd, cmd_class, risk_tip = "💀 強力賣出", "sell-signal", "🚨 極高風險。"
        
        col1, col2 = st.columns([1, 2])
        with col1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with col2: st.markdown(f"<div class='status-card {cmd_class}'>指揮官指令：{cmd}<br><small>{risk_tip}</small></div>", unsafe_allow_html=True)
        
        # 大盤推播 (間隔 2 小時)
        if is_auto and (time.time() - st.session_state.notified_stocks.get("TAIEX", 0)) > 7200:
            send_discord_message(f"🌐 **大盤戰情通知**\n狀態：`{cmd}`\n分數：`{score}`\n提醒：{risk_tip}")
            st.session_state.notified_stocks["TAIEX"] = time.time()

    st.divider()

    # 個股掃描
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
        
        is_inv = sid in inv_list
        is_snipe = sid in snipe_list
        
        # 通知邏輯過濾
        notify_msg = ""
        if is_inv and last["warning_sell"]:
            notify_msg = f"🟢 **【庫存賣點】** 觸發！\n原因：`{last['warning_sell']}`"
        elif is_snipe and last["warning_buy"]:
            notify_msg = f"🔴 **【狙擊買點】** 觸發！\n原因：`{last['warning_buy']}`"

        if notify_msg and (time.time() - st.session_state.notified_stocks.get(sid, 0)) > 3600:
            full_msg = (
                f"{notify_msg}\n"
                f"標的：`{sid} {s_name}`\n"
                f"現價：`{last['close']:.2f}` | 分數：`{last['score']}`\n"
                f"型態：`{last['pattern']}`"
            )
            send_discord_message(full_msg)
            st.session_state.notified_stocks[sid] = time.time()

        # UI 顯示
        border_color = "#28a745" if last["warning_sell"] else "#ff4b4b" if last["warning_buy"] else "#adb5bd"
        st.markdown(f"""
        <div style="background: white; padding: 20px; border-left: 10px solid {border_color}; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;">
            <div style="display: flex; justify-content: space-between;">
                <span style="font-size: 20px; font-weight: bold;">{'📦' if is_inv else '🎯'} {sid} {s_name} ({last['close']:.2f})</span>
                <span style="background:{border_color}; color:white; padding:2px 10px; border-radius:10px;">評分: {last['score']}</span>
            </div>
            <div style="margin-top: 10px;">
                <span style="color:#ff4b4b; font-weight:bold;">{last['warning_buy']}</span>
                <span style="color:#28a745; font-weight:bold;">{last['warning_sell']}</span>
                {'' if (last['warning_buy'] or last['warning_sell']) else '<span style="color:gray;">趨勢穩定中</span>'}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} {s_name} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)

# --- 執行控制區 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan(is_auto=False)
elif auto_monitor:
    while True:
        with placeholder.container():
            perform_scan(is_auto=True)
            st.caption(f"🔄 自動監控中... 下次更新: {(datetime.utcnow() + timedelta(hours=8, minutes=interval)).strftime('%H:%M:%S')}")
        time.sleep(interval * 60)
        st.rerun()
else:
    with placeholder.container(): perform_scan(is_auto=True)

st.sidebar.markdown("---")
st.sidebar.caption(f"最後更新: {(datetime.utcnow() + timedelta(hours=8)).strftime('%H:%M:%S')}")
