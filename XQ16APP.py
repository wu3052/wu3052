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
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 Discord Webhook 模組
# =====================
def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        st.error("❌ 診斷：程式找不到 DISCORD_WEBHOOK_URL")
        return
    payload = {"content": msg}
    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code in [200, 204]:
            st.success("✅ Discord 訊息發送成功！")
        else:
            st.error(f"❌ Discord 錯誤: {res.status_code}")
    except Exception as e:
        st.error(f"❌ 異常: {str(e)}")

# =====================
# 🔹 數據獲取模組
# =====================
@st.cache_data(ttl=300)
def get_stock_data(sid, token, days=1200): 
    params = {"dataset": "TaiwanStockPrice", "data_id": sid, "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"), "token": token}
    try:
        res = requests.get(BASE_URL, params=params, timeout=10).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values("date").reset_index(drop=True)
    except: return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# =====================
# 🔹 核心策略分析模組
# =====================
def analyze_strategy(df):
    if df is None or len(df) < 200: return None
    
    # 均線計算
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    df["ma144_60min"] = df["close"].rolling(36).mean() 
    df["ma55_60min"] = df["close"].rolling(14).mean()  
    
    # MACD 邏輯 (包含紅柱縮短判斷)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 關鍵位
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    # 初始化 (防止 ValueError)
    df["warning_buy"] = "" 
    df["warning_sell"] = ""
    df["score"] = 50
    
    last_idx = df.index[-1]
    row, prev_row = df.iloc[-1], df.iloc[-2]
    buy_signals, sell_signals = [], []
    
    # 買入邏輯
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: buy_signals.append("🏹 站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: buy_signals.append("🚀 站上60分144MA(買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev_row["close"] <= row["upward_key"]:
        buy_signals.append("🎯 站上死亡交叉關鍵位(上漲買入)")

    # 賣出邏輯
    if row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: sell_signals.append("⚠️ 跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: sell_signals.append("📉 跌破10MA(賣點)")
    if row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: sell_signals.append("🩸 跌破60分144MA(賣點)")
    if row["hist"] < prev_row["hist"] and row["hist"] > 0: sell_signals.append("🎯 目標達成/紅柱縮短")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev_row["close"] >= row["downward_key"]:
        sell_signals.append("🚫 跌破黃金交叉關鍵位(下跌賣出)")

    # 最終得分
    current_score = 50 + (len(buy_signals) * 10) - (len(sell_signals) * 15)
    df.at[last_idx, "score"] = max(10, min(current_score, 100))
    df.at[last_idx, "warning_buy"] = " / ".join(buy_signals)
    df.at[last_idx, "warning_sell"] = " / ".join(sell_signals)

    # 型態
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
    fig.add_trace(go.Candlestick(x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線"), row=1, col=1)
    
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)
    
    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    fig.update_layout(title=title, height=600, template="plotly_white", xaxis_rangeslider_visible=False)
    return fig

# =====================
# 📂 數據同步模組
# =====================
def get_list_from_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return "", ""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    try:
        df_sheet = pd.read_csv(url)
        def clean_codes(series): return [str(c).split('.')[0].strip() for c in series.dropna() if str(c).strip()]
        return " ".join(clean_codes(df_sheet.get('snipe_list'))), " ".join(clean_codes(df_sheet.get('inventory_list')))
    except: return "", ""

# =====================
# 🚀 主程式邏輯
# =====================
fm_token = st.secrets.get("FINMIND_TOKEN", "")
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}

with st.sidebar:
    st.header("🛡️ 指揮中心")
    if 'search_codes' not in st.session_state or st.button("🔄 同步 Google 表格"):
        s_list, i_list = get_list_from_sheets()
        st.session_state.search_codes, st.session_state.inventory_codes = s_list, i_list
    
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    analyze_btn = st.button("🚀 執行掃描", use_container_width=True)

def perform_scan(is_auto=False):
    st.subheader("🌐 指數戰情")
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        score = m_last["score"]
        cmd = "🚀 強力買進" if score >= 80 else "📈 分批買進" if score >= 60 else "📉 謹慎觀察" if score >= 40 else "💀 強力賣出"
        cmd_class = "buy-signal" if score >= 50 else "sell-signal"
        st.markdown(f"<div class='status-card {cmd_class}'>指令：{cmd} | 評分：{score}</div>", unsafe_allow_html=True)
    
    st.divider()

    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    stock_info = get_stock_info()
    scan_results = []
    
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        s_row = stock_info[stock_info["stock_id"] == sid]
        s_name = s_row["stock_name"].values[0] if not s_row.empty else "未知"
        
        is_inv = sid in inv_list
        tag_str = "【庫存股】" if is_inv else "【狙擊股】"
        
        # 通知邏輯
        notify_reason, warning_msg = "", ""
        if is_inv and last["warning_sell"]: notify_reason, warning_msg = "🛑 庫存訊號", last["warning_sell"]
        elif not is_inv and last["warning_buy"]: notify_reason, warning_msg = "🎯 狙擊買點", last["warning_buy"]

        if notify_reason and (time.time() - st.session_state.notified_stocks.get(sid, 0)) > 3600:
            discord_msg = (
                f"### {tag_str} 訊號觸發：{sid} {s_name}\n"
                f"**──────────────────**\n"
                f"💡 **觸發原因**: `{notify_reason}`\n"
                f"💰 **目前現價**: `{last['close']:.2f}`\n"
                f"📊 **戰情評分**: `{last['score']} 分`\n"
                f"🧭 **趨勢型態**: {last['pattern']}\n"
                f"🚩 **戰情提醒**: {warning_msg if warning_msg else '超勢穩定中'}\n"
                f"**──────────────────**\n"
                f"⏰ *通知時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
            )
            send_discord_message(discord_msg)
            st.session_state.notified_stocks[sid] = time.time()

        # --- 修正 HTML 卡片程式碼 ---
        border_color = "#28a745" if last["warning_sell"] else "#ff4b4b" if last["warning_buy"] else "#adb5bd"
        display_warning = warning_msg if (last["warning_buy"] or last["warning_sell"]) else "趨勢穩定中"
        
        # 確保 HTML 標籤正確閉合且不遺留文字
        st.markdown(f"""
        <div style="background: white; padding: 20px; border-left: 10px solid {border_color}; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 18px; font-weight: bold;">{tag_str} {sid} {s_name} ({last['close']:.2f})</span>
                <span style="background:{border_color}; color:white; padding:4px 12px; border-radius:15px; font-size: 14px;">評分: {last['score']}</span>
            </div>
            <div style="margin-top: 10px; color: #555;">
                🚩 戰情提醒：<b>{display_warning}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)
        
        scan_results.append({"代碼": sid, "名稱": s_name, "評分": last['score'], "狀態": display_warning})

    if scan_results:
        st.subheader("🏆 本次掃描排行")
        st.dataframe(pd.DataFrame(scan_results).sort_values("評分", ascending=False), use_container_width=True, hide_index=True)

# --- 執行控管 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    while True:
        with placeholder.container(): perform_scan(is_auto=True)
        time.sleep(interval * 60)
        st.rerun()
else:
    with placeholder.container(): perform_scan()
