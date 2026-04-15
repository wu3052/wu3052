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
    .neutral-signal { background-color: #6c757d; color: white; border-left: 8px solid #343a40; }
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
    
    # 指標計算
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    df["ma144_60min"] = df["close"].rolling(36).mean() # 模擬60分144MA
    df["ma55_60min"] = df["close"].rolling(14).mean()  # 模擬60分55MA
    
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan) 
    
    # 關鍵位判定
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    # 發動點判定
    df["star_signal"] = False
    for i in range(1, len(df)):
        if (df["ma5"].iloc[i] > df["ma10"].iloc[i]) and (df["ma5"].iloc[i-1] <= df["ma10"].iloc[i-1]) and (df["close"].iloc[i] > df["ma5"].iloc[i]):
            df.loc[df.index[i], "star_signal"] = True

    # 買賣點與警告邏輯
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    buy_signals = []
    sell_signals = []
    trace_signals = []

    # 買點判斷
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: buy_signals.append("🏹 站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: buy_signals.append("🚀 站上60分144MA(買點)")
    if row["star_signal"]: buy_signals.append("⭐ 站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev_row["close"] <= row["upward_key"]:
        buy_signals.append("🎯 站上死亡交叉關鍵位(上漲買入)")
    
    # 追蹤買點 (量縮站穩5MA)
    if row["close"] > row["ma5"] and row["vol_ratio"] < 0.8 and prev_row["close"] > prev_row["ma5"]:
        trace_signals.append("⚪ 量縮站穩5MA(追蹤買點)")

    # 賣點判斷
    if row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: sell_signals.append("⚠️ 跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: sell_signals.append("🩸 跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev_row["close"] >= prev_row["ma55_60min"]: sell_signals.append("🚫 跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: sell_signals.append("🩸 跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev_row["close"] >= row["downward_key"]:
        sell_signals.append("📉 跌破黃金交叉關鍵位(下跌賣出)")

    # 評分系統
    score = 50
    if buy_signals: score += len(buy_signals) * 10
    if trace_signals: score += 5
    if sell_signals: score -= len(sell_signals) * 15 # 賣點出現大幅扣分
    
    # 多頭排列加分
    if row["ma5"] > row["ma20"] > row["ma60"]: score += 10
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_signals + trace_signals + sell_signals) if (buy_signals or trace_signals or sell_signals) else "趨勢穩定中"
    df.at[last_idx, "buy_trigger"] = buy_signals
    if trace_signals: df.at[last_idx, "buy_trigger"] = buy_signals + trace_signals
    df.at[last_idx, "sell_trigger"] = sell_signals

    # 型態
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    df.at[last_idx, "pattern"] = "💎 鑽石眼" if ma_diff < 0.015 else ("📐 黃金三角眼" if row["ma5"] > row["ma10"] > row["ma20"] else "一般盤整")
    
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
    
    fig.update_layout(title=title, height=600, template="plotly_white", xaxis_rangeslider_visible=False)
    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
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
    except: return "", ""

# =====================
# 🚀 主程式邏輯
# =====================
fm_token = st.secrets.get("FINMIND_TOKEN", "")
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}

with st.sidebar:
    st.header("🛡️ 指揮中心設定")
    fm_token = st.text_input("FinMind Token", value=fm_token, type="password")
    if st.button("🔄 同步 Google 表格清單"):
        s_list, i_list = get_list_from_sheets()
        st.session_state.search_codes = s_list
        st.session_state.inventory_codes = i_list
        st.toast("✅ 清單已同步")
    st.session_state.search_codes = st.text_area("🎯 狙擊個股清單", value=st.session_state.get('search_codes', ""))
    st.session_state.inventory_codes = st.text_area("📦 庫存股清單", value=st.session_state.get('inventory_codes', ""))
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

def perform_scan(is_auto=False):
    now_taiwan = datetime.utcnow() + timedelta(hours=8)
    if is_auto and not (0 <= now_taiwan.weekday() <= 4 and datetime.strptime("08:55", "%H:%M").time() <= now_taiwan.time() <= datetime.strptime("14:00", "%H:%M").time()):
        st.info(f"💤 非開盤時間 ({now_taiwan.strftime('%H:%M:%S')})")
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
        col1.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        col2.markdown(f"<div class='status-card {cmd_class}'>指揮官指令：{cmd}<br><small>{risk_tip}</small></div>", unsafe_allow_html=True)
        
        # 大盤通知
        if m_last["buy_trigger"] or m_last["sell_trigger"]:
            ts_key = f"TAIEX_{now_taiwan.strftime('%Y%H')}"
            if ts_key not in st.session_state.notified_stocks:
                msg = f"📢 **大盤戰情廣播**\n指令: `{cmd}`\n提醒: `{m_last['warning']}`"
                send_discord_message(msg)
                st.session_state.notified_stocks[ts_key] = time.time()
        
        with st.expander("查看大盤 K 線圖"):
            st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 指數"), use_container_width=True)

    # 個股掃描
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    stock_info = get_stock_info()
    
    scan_results = []
    for sid in sorted(list(set(snipe_list + inv_list))):
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        s_name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
        
        is_inv = sid in inv_list
        is_snipe = sid in snipe_list
        tag_str = "📦庫存" if is_inv else "🎯狙擊"
        
        # 通知邏輯
        notify_reason = ""
        should_send = False
        if is_inv and last["sell_trigger"]: # 庫存只報憂
            notify_reason = f"🚨 庫存賣點：{', '.join(last['sell_trigger'])}"
            should_send = True
        elif is_snipe and last["buy_trigger"]: # 狙擊只報喜
            notify_reason = f"🏹 狙擊買點：{', '.join(last['buy_trigger'])}"
            should_send = True
            
        if should_send:
            curr_ts = time.time()
            if curr_ts - st.session_state.notified_stocks.get(sid, 0) > 3600:
                discord_msg = (
                    f"### {tag_str} 訊號觸發：{sid} {s_name}\n"
                    f"**──────────────────**\n"
                    f" **觸發原因**: `{notify_reason}`\n"
                    f" **目前現價**: `{last['close']:.2f}`\n"
                    f" **戰情評分**: `{last['score']} 分`\n"
                    f" **趨勢型態**: {last['pattern']}\n"
                    f" **戰情提醒**: {last['warning']}\n"
                    f"**──────────────────**\n"
                    f"⏰ *通知時間: {now_taiwan.strftime('%Y-%m-%d %H:%M:%S')}*"
                )
                if send_discord_message(discord_msg):
                    st.session_state.notified_stocks[sid] = curr_ts

        # 顯示卡片
        border = "#28a745" if last["sell_trigger"] else ("#ff4b4b" if last["buy_trigger"] else "#adb5bd")
        st.markdown(f"""
        <div style="background: white; padding: 15px; border-left: 8px solid {border}; border-radius: 10px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between;">
                <span style="font-weight: bold;">{tag_str} {sid} {s_name} | {last['close']:.2f}</span>
                <span style="color: {border}; font-weight: bold;">評分: {last['score']}</span>
            </div>
            <div style="font-size: 0.9em; color: #555;">提醒: {last['warning']}</div>
        </div>
        """, unsafe_allow_html=True)
        with st.expander(f"查看 {sid} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)
        
        scan_results.append({"類別": tag_str, "代碼": sid, "名稱": s_name, "收盤價": last['close'], "分數": last['score'], "提醒": last['warning']})

    if scan_results:
        st.subheader("🏆 本次掃描排行榜")
        df_res = pd.DataFrame(scan_results).sort_values("分數", ascending=False)
        c1, c2 = st.columns(2)
        c1.write("🎯 狙擊股排行")
        c1.dataframe(df_res[df_res["類別"] == "🎯狙擊"], hide_index=True)
        c2.write("📦 庫存股排行")
        c2.dataframe(df_res[df_res["類別"] == "📦庫存"], hide_index=True)

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
