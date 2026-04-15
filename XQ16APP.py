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
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro", page_icon="🏹")

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
        return res.status_code in [200, 204]
    except Exception as e:
        st.error(f"❌ Discord 發送異常: {str(e)}")
        return False

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
    
    # 均線計算
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 特殊均線
    df["ma144_60min"] = df["close"].rolling(36).mean() # 模擬 60min MA144
    df["ma55_60min"] = df["close"].rolling(14).mean()  # 模擬 60min MA55
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與量能
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan) 
    
    # 關鍵位邏輯
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    # 星級發動點 (5MA>10MA 黃金交叉且收盤在5MA之上)
    df["star_signal"] = False
    for i in range(1, len(df)):
        if (df["ma5"].iloc[i] > df["ma10"].iloc[i]) and (df["ma5"].iloc[i-1] <= df["ma10"].iloc[i-1]) and (df["close"].iloc[i] > df["ma5"].iloc[i]):
            df.loc[df.index[i], "star_signal"] = True

    # 初始化評分與警告
    score = 50
    buy_warnings = []
    sell_warnings = []
    
    row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # --- 買點判斷 ---
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: buy_warnings.append("🏹 站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: buy_warnings.append("🚀 站上60分144MA(買點)")
    if row["star_signal"]: buy_warnings.append("⭐ 站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev_row["close"] <= row["upward_key"]:
        buy_warnings.append("🎯 站上死亡交叉關鍵位(上漲買入)")
    
    # 追蹤買點: 量縮站穩5MA
    if row["close"] > row["ma5"] and row["vol_ratio"] < 0.8 and prev_row["close"] > prev_row["ma5"]:
        buy_warnings.append("⚪ 量縮站穩5MA(追蹤買點)")

    # --- 賣點判斷 ---
    if row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: sell_warnings.append("🩸 跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: sell_warnings.append("📉 跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev_row["close"] >= prev_row["ma55_60min"]: sell_warnings.append("⚠️ 跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: sell_warnings.append("🚨 跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev_row["close"] >= row["downward_key"]:
        sell_warnings.append("💀 跌破黃金交叉關鍵位(下跌賣出)")

    # --- 分數邏輯計算 ---
    # 基礎分根據均線多空
    if row["close"] > row["ma20"]: score += 10
    if row["ma5"] > row["ma10"]: score += 10
    if row["hist"] > 0: score += 10
    
    # 買點加分
    score += len(buy_warnings) * 10
    # 賣點重扣 (確保出現賣點時分數下降)
    score -= len(sell_warnings) * 25
    
    # 強制限制分數範圍
    score = max(0, min(100, score))

    df.at[df.index[-1], "score"] = score
    
    # 合併警告訊息，並標註顏色邏輯
    all_warn = []
    if buy_warnings: all_warn.append(f"🟢 {', '.join(buy_warnings)}")
    if sell_warnings: all_warn.append(f"🔴 {', '.join(sell_warnings)}")
    
    df.at[df.index[-1], "warning"] = " | ".join(all_warn) if all_warn else "趨勢穩定中"
    df.at[df.index[-1], "buy_signal_count"] = len(buy_warnings)
    df.at[df.index[-1], "sell_signal_count"] = len(sell_warnings)

    # 型態
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    pattern = "一般盤整"
    if ma_diff < 0.015: pattern = "💎 鑽石眼"
    elif row["ma5"] > row["ma10"] > row["ma20"]: pattern = "📐 黃金三角眼"
    df.at[df.index[-1], "pattern"] = pattern
    
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

    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)

    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=12, color="#FFD700"), name="發動點"), row=1, col=1)

    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)

    fig.update_layout(title=title, height=600, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# =====================
# 📂 Google Sheets 數據讀取
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
# 🚀 主程式邏輯
# =====================
fm_token = st.secrets.get("FINMIND_TOKEN", "")
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}

with st.sidebar:
    st.header("🛡️ 指揮中心")
    fm_token = st.text_input("FinMind Token", value=fm_token, type="password")
    if st.button("🔄 同步 Google 表格"):
        s_list, i_list = get_list_from_sheets()
        st.session_state.search_codes, st.session_state.inventory_codes = s_list, i_list
    
    st.session_state.search_codes = st.text_area("🎯 狙擊個股清單", value=st.session_state.get('search_codes', ""))
    st.session_state.inventory_codes = st.text_area("📦 庫存股清單", value=st.session_state.get('inventory_codes', ""))
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

def perform_scan(is_auto=False):
    now_tw = datetime.utcnow() + timedelta(hours=8)
    if is_auto and not (0 <= now_tw.weekday() <= 4 and datetime.strptime("08:55", "%H:%M").time() <= now_tw.time() <= datetime.strptime("14:05", "%H:%M").time()):
        st.info(f"💤 非開盤時間 ({now_tw.strftime('%H:%M:%S')})")
        return

    if not fm_token: 
        st.error("缺失 Token")
        return

    # --- 1. 大盤分析與通知 ---
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
        
        # 大盤通知邏輯 (每小時通知一次)
        if (time.time() - st.session_state.notified_stocks.get("TAIEX", 0)) > 3600:
            m_msg = (f"### 🌐 大盤戰情通知\n**──────────────────**\n"
                     f"**指令**: `{cmd}`\n**風險**: `{risk_tip}`\n**指數**: `{m_last['close']:.2f}`\n"
                     f"**提醒**: {m_last['warning']}\n**──────────────────**")
            if send_discord_message(m_msg): st.session_state.notified_stocks["TAIEX"] = time.time()
            
        with st.expander("大盤詳細走勢圖"): st.plotly_chart(plot_advanced_chart(m_df, "TAIEX"), use_container_width=True)

    # --- 2. 個股掃描 ---
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    stock_info = get_stock_info()
    
    results_inv = []
    results_snipe = []

    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None or len(df) < 200: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        s_row = stock_info[stock_info["stock_id"] == sid]
        s_name = s_row["stock_name"].values[0] if not s_row.empty else "未知"
        
        is_inventory = sid in inv_list
        tag_str = "📦 庫存" if is_inventory else "🎯 狙擊"
        
        # --- 通知過濾邏輯 ---
        should_notify = False
        notify_reason = ""
        
        if is_inventory:
            # 庫存股：只在意賣點
            if last["sell_signal_count"] > 0:
                should_notify, notify_reason = True, "🛑 庫存出現賣出訊號"
        else:
            # 狙擊股：只在意買點 (包含量縮站穩)
            if last["buy_signal_count"] > 0:
                should_notify, notify_reason = True, "🏹 狙擊觸發買入點"

        if should_notify:
            curr_ts = time.time()
            if (curr_ts - st.session_state.notified_stocks.get(sid, 0)) > 3600:
                discord_msg = (
                    f"### {tag_str} 訊號觸發：{sid} {s_name}\n"
                    f"**──────────────────**\n"
                    f" **觸發原因**: `{notify_reason}`\n"
                    f" **目前現價**: `{last['close']:.2f}`\n"
                    f" **戰情評分**: `{last['score']} 分`\n"
                    f" **趨勢型態**: {last['pattern']}\n"
                    f" **戰情提醒**: {last['warning']}\n"
                    f"**──────────────────**\n"
                    f"⏰ *通知時間: {(datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S')}*"
                )
                if send_discord_message(discord_msg):
                    st.session_state.notified_stocks[sid] = curr_ts

        # 顯示 UI 卡片
        border = "#28a745" if last["sell_signal_count"] > 0 else "#ff4b4b" if last["buy_signal_count"] > 0 else "#adb5bd"
        st.markdown(f"""
        <div style="background: white; padding: 15px; border-left: 10px solid {border}; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 18px; font-weight: bold;">{tag_str} {sid} {s_name} | {last['close']:.2f}</span>
                <span style="background:{border}; color:white; padding:2px 12px; border-radius:15px;">評分: {int(last['score'])}</span>
            </div>
            <div style="margin-top: 8px; font-size: 14px;">{last['warning']} | 型態: {last['pattern']}</div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)
        
        res_data = {"代碼": sid, "名稱": s_name, "收盤": last['close'], "分數": int(last['score']), "提醒": last['warning']}
        if is_inventory: results_inv.append(res_data)
        else: results_snipe.append(res_data)

    # --- 3. 排行榜展示 ---
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("📦 庫存股監控 (由強至弱)")
        if results_inv: st.dataframe(pd.DataFrame(results_inv).sort_values("分數", ascending=False), use_container_width=True, hide_index=True)
    with col_b:
        st.subheader("🎯 狙擊股排行榜 (由強至弱)")
        if results_snipe: st.dataframe(pd.DataFrame(results_snipe).sort_values("分數", ascending=False), use_container_width=True, hide_index=True)

# --- 執行控制 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan(is_auto=False)
elif auto_monitor:
    while True:
        with placeholder.container():
            perform_scan(is_auto=True)
            st.caption(f"🔄 監控中... 下次更新: {(datetime.utcnow() + timedelta(hours=8, minutes=interval)).strftime('%H:%M:%S')}")
        time.sleep(interval * 60)
        st.rerun()
else:
    with placeholder.container(): perform_scan(is_auto=True)

st.sidebar.markdown("---")
st.sidebar.caption(f"最後更新: {(datetime.utcnow() + timedelta(hours=8)).strftime('%H:%M:%S')}")
