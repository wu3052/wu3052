import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time

# =====================
# 🔑 1. 系統密鑰 (請在 Streamlit Cloud Secrets 設定)
# =====================
FM_TOKEN = st.secrets.get("FM_TOKEN", "")
LINE_BOT_TOKEN = st.secrets.get("LINE_BOT_TOKEN", "")
USER_ID = st.secrets.get("USER_ID", "")

st.set_page_config(layout="centered", page_title="股票狙擊手Pro", page_icon="🏹")

# 手機版介面優化 CSS
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .status-card { padding: 15px; border-radius: 12px; margin-bottom: 15px; font-weight: bold; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .info-tag { font-size: 0.8em; padding: 2px 6px; border-radius: 4px; margin-right: 3px; display: inline-block; }
    .tag-blue { background-color: #e7f5ff; color: #1971c2; }
</style>
""", unsafe_allow_html=True)

# =====================
# 🟢 2. 通訊與數據功能
# =====================
def send_line_alert(msg):
    if not LINE_BOT_TOKEN or not USER_ID: return
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_BOT_TOKEN}"}
    payload = {"to": USER_ID, "messages": [{"type": "text", "text": msg}]}
    requests.post(url, headers=headers, json=payload, timeout=5)

@st.cache_data(ttl=3600)
def get_stock_data(sid, token): 
    params = {"dataset": "TaiwanStockPrice", "data_id": sid, 
              "start_date": (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"), "token": token}
    try:
        res = requests.get("https://api.finmindtrade.com/api/v4/data", params=params, timeout=10).json()
        df = pd.DataFrame(res.get("data", []))
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        return df.sort_values("date").reset_index(drop=True)
    except: return None

# =====================
# 🔹 3. 核心監控邏輯 (包含賣出判定)
# =====================
def analyze_strategy(df, sid, inventory_list):
    if df is None or len(df) < 60: return None
    
    # 指標計算
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan)
    
    last = df.iloc[-1]
    prev = df.iloc[-2]
    warnings = []
    
    # --- 判斷邏輯 ---
    is_gc = (last["ma5"] > last["ma10"]) and (prev["ma5"] <= prev["ma10"])
    is_stand_ma5 = (last["close"] > last["ma5"]) and (prev["close"] <= prev["ma5"])
    is_drop_ma5 = (last["close"] < last["ma5"]) and (prev["close"] >= prev["ma5"])
    is_drop_ma10 = (last["close"] < last["ma10"]) and (prev["close"] >= prev["ma10"])

    # --- 💡 自動推播判斷 ---
    if sid != "TAIEX":
        alert_msg = ""
        
        # A. 買入訊號 (站上5MA 或 黃金交叉)
        if is_stand_ma5 or is_gc:
            alert_msg = f"🏹 【買入發動】\n標的：{sid}\n現價：{last['close']}\n訊號：{'黃金交叉' if is_gc else '站上5MA'}"
        
        # B. 賣出訊號 (跌破5MA 或 10MA)
        elif is_drop_ma5 or is_drop_ma10:
            status = "🚨 【庫存緊急賣出】" if sid in inventory_list else "⚠️ 【建議減碼】"
            reason = "跌破5MA" if is_drop_ma5 else "跌破10MA"
            alert_msg = f"{status}\n標的：{sid}\n現價：{last['close']}\n訊號：{reason}"

        if alert_msg:
            send_line_alert(alert_msg)

    # 介面顯示回傳
    df.at[df.index[-1], "warning"] = "買入訊號" if (is_stand_ma5 or is_gc) else "賣出警示" if (is_drop_ma5 or is_drop_ma10) else "趨勢穩定"
    df.at[df.index[-1], "score"] = 80 if is_stand_ma5 else 40 if is_drop_ma5 else 60
    return df

# =====================
# 🚀 4. 主程式介面
# =====================
st.title("🏹 狙擊手 Pro (2026)")

with st.sidebar:
    st.header("⚙️ 監控設定")
    fm_token = st.text_input("FinMind Token", value=FM_TOKEN, type="password")
    inventory_input = st.text_area("📦 我的庫存 (空格分開)", value="6257 2330 2382")
    search_input = st.text_area("🎯 狙擊清單 (空格分開)", value="")
    
    refresh_rate = st.slider("自動刷新(分)", 1, 30, 5)
    auto_monitor = st.toggle("🚀 啟動自動監控")

# 整理清單
inventory_list = [c for c in re.split(r'[\s\n,]+', inventory_input) if c]
search_list = [c for c in re.split(r'[\s\n,]+', search_input) if c]
all_codes = list(set(inventory_list + search_list))

if auto_monitor:
    status_placeholder = st.empty()
    while True:
        status_placeholder.write(f"⏱️ 監控中... 最後更新: {datetime.now().strftime('%H:%M:%S')}")
        
        for sid in all_codes:
            df = get_stock_data(sid, fm_token if fm_token else FM_TOKEN)
            if df is not None:
                df = analyze_strategy(df, sid, inventory_list)
                last = df.iloc[-1]
                
                # 簡單卡片
                color = "#ff4b4b" if "買入" in last["warning"] else "#28a745" if "賣出" in last["warning"] else "#adb5bd"
                st.markdown(f"""
                <div style="background:white; padding:10px; border-left:5px solid {color}; border-radius:8px; margin-bottom:5px;">
                    <b>{sid}</b> | 價: {last['close']} | <b>{last['warning']}</b>
                </div>
                """, unsafe_allow_html=True)

        time.sleep(refresh_rate * 60)
        st.rerun()