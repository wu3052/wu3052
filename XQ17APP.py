import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time
import yfinance as yf

# --- 頁面配置 ---
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro", page_icon="🏹")

# 自定義 CSS 樣式
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; font-size: 1.2em; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .neutral-signal { background-color: #e9ecef; color: #495057; border-left: 8px solid #adb5bd; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 輔助工具模組
# =====================
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

# =====================
# 🔹 Discord Webhook 模組
# =====================
def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    payload = {"content": msg}
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except: pass

# =====================
# 🔹 數據獲取模組 (混合引擎)
# =====================
@st.cache_data(ttl=300)
def get_mixed_data(sid, token):
    # 1. 先抓 FinMind 歷史日線
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": sid,
        "start_date": (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d"),
        "token": token
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10).json()
        df = pd.DataFrame(res.get("data", []))
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        # 2. 盤中切換 yfinance 補時效性
        if is_market_open() and sid != "TAIEX":
            suffix = ".TW" if len(sid) == 4 else ".TWO" # 簡單判斷，上市四碼為主
            yf_sid = f"{sid}{suffix}"
            # 抓取今天最新的 15 分 K
            yt = yf.download(yf_sid, period="1d", interval="15m", progress=False)
            if not yt.empty:
                last_price = yt['Close'].iloc[-1]
                df.loc[df.index[-1], 'close'] = last_price
                df.loc[df.index[-1], 'volume'] = yt['Volume'].sum()
        return df
    except:
        return None

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
    
    # 計算均線
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 模擬 60 分線指標 (日線近似值)
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["ma55_60min"] = df["close"].rolling(14).mean()

    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與量能
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵位
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()

    # 星級發動點
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # 狀態與評分邏輯
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    warnings = []
    buy_signals = []
    sell_signals = []
    
    # 買點判斷
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: buy_signals.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: buy_signals.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_signals.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev_row["close"] <= row["upward_key"]: buy_signals.append("站上死亡交叉關鍵位(上漲買入)")
    
    # 賣點判斷
    if row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: sell_signals.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: sell_signals.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev_row["close"] >= prev_row["ma55_60min"]: sell_signals.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: sell_signals.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev_row["close"] >= row["downward_key"]: sell_signals.append("跌破黃金交叉關鍵位(下跌賣出)")

    # 評分修正
    score = 50
    if buy_signals: score += 15 * len(buy_signals)
    if sell_signals: score -= 20 * len(sell_signals) # 賣點權重高，分數會顯著下降
    if row["vol_ratio"] > 1.5: score += 10
    if row["bias_20"] > 10: score -= 5 # 過度乖離扣分
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_signals + sell_signals) if (buy_signals or sell_signals) else "趨勢穩定中"
    df.at[last_idx, "has_buy"] = len(buy_signals) > 0
    df.at[last_idx, "has_sell"] = len(sell_signals) > 0

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
    fig.add_trace(go.Candlestick(x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線"), row=1, col=1)
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    fig.update_layout(title=title, height=600, template="plotly_white", xaxis_rangeslider_visible=False)
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
        def clean(s): return " ".join(df_sheet[s].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
        return clean('snipe_list'), clean('inventory_list')
    except: return "", ""

# =====================
# 🚀 主程式邏輯
# =====================
if 'search_codes' not in st.session_state:
    s_list, i_list = get_list_from_sheets() # 初始化直接同步
    st.session_state.search_codes = s_list
    st.session_state.inventory_codes = i_list
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}
if 'prev_scores' not in st.session_state: st.session_state.prev_scores = {}

with st.sidebar:
    st.header("🛡️ 指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    if st.button("🔄 同步 Google 表格"):
        s_list, i_list = get_list_from_sheets()
        st.session_state.search_codes, st.session_state.inventory_codes = s_list, i_list
        st.rerun()
    st.session_state.search_codes = st.text_area("🎯 狙擊個股", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存股", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

def perform_scan(is_auto=False):
    now_tpe = get_taiwan_time()
    # 非開盤時間自動降頻在主循環處理，這裡只做提示
    
    st.subheader(f"📊 掃描報告 - {now_tpe.strftime('%H:%M:%S')}")
    
    # 1. 大盤分析
    m_df = get_mixed_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        score = m_last["score"]
        if score >= 80: cmd, cmd_class, risk_tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強。"
        elif score >= 60: cmd, cmd_class, risk_tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中。"
        elif score >= 40: cmd, cmd_class, risk_tip = "🤏 少量買進", "buy-signal", "⚠️ 處於震盪區。"
        elif score >= 20: cmd, cmd_class, risk_tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱。"
        else: cmd, cmd_class, risk_tip = "💀 強力賣出", "sell-signal", "🚨 極高風險。"
        
        # 大盤 Discord 通知 (僅在訊號變更時)
        m_key = f"TAIEX_{cmd}"
        if m_key not in st.session_state.notified_stocks:
            send_discord_message(f"🌐 **大盤戰情變更**\n指令：{cmd}\n風險：{risk_tip}\n指數：{m_last['close']:.2f}")
            st.session_state.notified_stocks[m_key] = time.time()

        col1, col2 = st.columns([1, 2])
        with col1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with col2: st.markdown(f"<div class='status-card {cmd_class}'>{cmd} | {risk_tip} (評分: {score})</div>", unsafe_allow_html=True)
        with st.expander("查看大盤 K 線圖"): st.plotly_chart(plot_advanced_chart(m_df, "TAIEX"), use_container_width=True)

    # 2. 熱圖區域 (Momentum)
    st.write("### 🔥 動能熱圖 (評分變化)")
    h_cols = st.columns(5)

    # 3. 個股掃描
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    stock_info = get_stock_info()
    
    results = []
    for idx, sid in enumerate(all_codes):
        df = get_mixed_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        s_row = stock_info[stock_info["stock_id"] == sid]
        s_name = s_row["stock_name"].values[0] if not s_row.empty else "未知"
        
        # 評分動能
        prev_score = st.session_state.prev_scores.get(sid, last["score"])
        score_diff = last["score"] - prev_score
        st.session_state.prev_scores[sid] = last["score"]
        
        # Discord 通知邏輯
        tag_str = "📦 庫存" if sid in inv_list else "🎯 狙擊"
        should_notify = False
        notify_reason = ""
        
        if sid in inv_list:
            if last["has_sell"]: # 庫存只在意賣點
                should_notify, notify_reason = True, f"🩸 庫存賣點：{last['warning']}"
        else: # 狙擊股
            if last["has_buy"]:
                should_notify, notify_reason = True, f"🏹 買點出現：{last['warning']}"
            elif last["close"] > last["ma5"] and last["vol_ratio"] < 1.0: # 量縮站穩
                should_notify, notify_reason = True, "⚪ 量縮站穩5MA(追蹤買點)"

        if should_notify:
            curr_ts = time.time()
            if (curr_ts - st.session_state.notified_stocks.get(sid, 0)) > 1800:
                bonus_tag = "🔥 狙擊目標確認" if (last["has_buy"] and last["vol_ratio"] > 2) else ""
                discord_msg = (
                    f"### {tag_str} 訊號觸發：{sid} {s_name} {bonus_tag}\n"
                    f"**──────────────────**\n"
                    f" **觸發原因**: `{notify_reason}`\n"
                    f" **目前現價**: `{last['close']:.2f}` (5MA乖離: {last['bias_5']:.2f}%)\n"
                    f" **戰情評分**: `{last['score']} 分`\n"
                    f" **趨勢型態**: {last['pattern']}\n"
                    f" **戰情提醒**: {last['warning']}\n"
                    f"**──────────────────**\n"
                    f"⏰ *通知時間: {get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')}*"
                )
                send_discord_message(discord_msg)
                st.session_state.notified_stocks[sid] = curr_ts

        # UI 顯示
        border = "#28a745" if last["has_sell"] else ("#ff4b4b" if last["has_buy"] else "#adb5bd")
        st.markdown(f"""
        <div style="background: white; padding: 15px; border-left: 10px solid {border}; border-radius: 10px; margin-bottom: 10px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="font-size: 18px; font-weight: bold;">{tag_str} {sid} {s_name} | {last['close']:.2f}</span>
                <span style="background:{border}; color:white; padding:2px 12px; border-radius:15px;">評分: {last['score']}</span>
            </div>
            <div style="color: #666; font-size: 0.9em; margin-top:5px;">提醒: {last['warning']} | 型態: {last['pattern']}</div>
        </div>
        """, unsafe_allow_html=True)
        
        results.append({"類別": tag_str, "代碼": sid, "名稱": s_name, "現價": last["close"], "分數": last["score"], "提醒": last["warning"]})

    # 4. 區分排行榜
    if results:
        res_df = pd.DataFrame(results)
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.write("### 📦 庫存股監控 (依分數降序)")
            st.dataframe(res_df[res_df["類別"] == "📦 庫存"].sort_values("分數", ascending=False), use_container_width=True, hide_index=True)
        with c2:
            st.write("### 🎯 狙擊股排行榜 (由強至弱)")
            st.dataframe(res_df[res_df["類別"] == "🎯 狙擊"].sort_values("分數", ascending=False), use_container_width=True, hide_index=True)

# --- 執行控制 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    while True:
        with placeholder.container():
            perform_scan(is_auto=True)
            # 時間控制邏輯
            is_open = is_market_open()
            current_wait = interval if is_open else 60
            next_run = get_taiwan_time() + timedelta(minutes=current_wait)
            st.caption(f"🔄 {'盤中監控中' if is_open else '盤後休眠中'}... 下次更新: {next_run.strftime('%H:%M:%S')}")
        time.sleep(current_wait * 60)
        st.rerun()