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

# --- 1. 頁面配置與進階 CSS ---
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max", page_icon="🏹")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; font-size: 1.2em; text-align: center; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .dashboard-box { background: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #e0e0e0; text-align: center; height: 100%; }
    .log-container { background: #1e1e1e; color: #00ff00; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; height: 250px; overflow-y: scroll; border: 1px solid #444; }
    .highlight-snipe { background-color: #fff3f3; border: 3px solid #ff4b4b !important; animation: blinker 1.5s linear infinite; }
    @keyframes blinker { 50% { opacity: 0.7; } }
    .info-tag { font-size: 0.85em; padding: 3px 8px; border-radius: 4px; margin-right: 5px; font-weight: bold; }
    .tag-blue { background-color: #e7f5ff; color: #1971c2; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
if 'notified_status' not in st.session_state: st.session_state.notified_status = {}
if 'event_log' not in st.session_state: st.session_state.event_log = []
if 'sid_map' not in st.session_state: st.session_state.sid_map = {}
if 'search_codes' not in st.session_state: st.session_state.search_codes = ""
if 'inventory_codes' not in st.session_state: st.session_state.inventory_codes = ""
if 'first_sync_done' not in st.session_state: st.session_state.first_sync_done = False

# --- 3. 核心工具模組 ---
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

def get_yf_ticker(sid):
    if sid in st.session_state.sid_map: return st.session_state.sid_map[sid]
    for suffix in [".TW", ".TWO"]:
        t = yf.Ticker(f"{sid}{suffix}")
        if t.fast_info.get('previous_close') is not None:
            st.session_state.sid_map[sid] = f"{sid}{suffix}"
            return f"{sid}{suffix}"
    return f"{sid}.TW"

def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10)
    except Exception: pass

def add_log(msg):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    st.session_state.event_log.insert(0, f"[{ts}] {msg}")
    if len(st.session_state.event_log) > 50: st.session_state.event_log.pop()

# --- 4. 數據獲取與預估成交量 ---
@st.cache_data(ttl=300)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=10).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        if is_market_open() and sid != "TAIEX":
            ticker_str = get_yf_ticker(sid)
            yt = yf.download(ticker_str, period="1d", interval="5m", progress=False)
            if not yt.empty:
                last_price = yt['Close'].iloc[-1]
                day_vol = yt['Volume'].sum()
                df.loc[df.index[-1], 'close'] = last_price
                df.loc[df.index[-1], 'high'] = max(df.loc[df.index[-1], 'high'], yt['High'].max())
                df.loc[df.index[-1], 'low'] = min(df.loc[df.index[-1], 'low'], yt['Low'].min())
                df.loc[df.index[-1], 'volume'] = day_vol
                now = get_taiwan_time()
                passed = max(1, (now.hour - 9) * 60 + now.minute)
                passed = min(passed, 270)
                df.loc[df.index[-1], 'est_volume'] = day_vol * (270 / passed)
            else: df['est_volume'] = df['volume']
        else: df['est_volume'] = df['volume']
        return df
    except: return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# --- 5. 核心策略分析 (還原所有長線與短線指標) ---
def analyze_strategy(df):
    if df is None or len(df) < 200: return None
    
    # 均線族群
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 模擬 60 分線與週線判斷
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["ma55_60min"] = df["close"].rolling(14).mean()
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD 指標
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離率與量能比例
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵支撐與壓力位判定
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    buy_pts, sell_pts = [], []
    
    # [買入條件]
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死亡交叉關鍵位(上漲買入)")

    # [賣出條件]
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破黃金交叉關鍵位(下跌賣出)")

    # 綜合評分 (0-100)
    score = 50
    if buy_pts: score += 15 * len(buy_pts)
    if sell_pts: score -= 20 * len(sell_pts)
    if row["vol_ratio"] > 1.8: score += 10
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定中"
    df.at[last_idx, "sig_type"] = "BUY" if buy_pts else ("SELL" if sell_pts else "HOLD")
    
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    df.at[last_idx, "pattern"] = "💎 鑽石眼" if ma_diff < 0.015 else ("📐 黃金三角眼" if row["ma5"] > row["ma10"] > row["ma20"] else "一般盤整")
    
    return df

# --- 6. 視覺化模組 ---
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 主圖 K 線
    fig.add_trace(go.Candlestick(x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線"), row=1, col=1)
    
    # 均線繪製
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    # 關鍵位虛線
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)
    
    # 星星發動點標記
    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=12, color="#FFD700"), name="發動點"), row=1, col=1)
    
    # MACD 副圖
    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    
    fig.update_layout(height=650, title=title, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# --- 7. Google 表單同步核心 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(url)
        def clean_col(name):
            if name in df_sheet.columns:
                return " ".join(df_sheet[name].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
            return ""
        st.session_state.search_codes = clean_col('snipe_list')
        st.session_state.inventory_codes = clean_col('inventory_list')
        add_log("✅ 成功從 Google 表單同步數據")
    except Exception as e:
        st.error(f"同步失敗: {e}")

if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# --- 8. 指揮中心 UI ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    if st.button("🔄 手動同步雲端清單"):
        sync_sheets()
        st.rerun()
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

# --- 9. 執行掃描邏輯 ---
def perform_scan():
    now = get_taiwan_time()
    st.markdown(f"### 📡 掃描時間：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    scan_results = []

    # 大盤戰情區
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        score = m_last["score"]
        if score >= 80: cmd, clz, tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強。"
        elif score >= 60: cmd, clz, tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中。"
        elif score >= 20: cmd, clz, tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱。"
        else: cmd, clz, tip = "💀 強力賣出", "sell-signal", "🚨 極高風險。"
        
        if st.session_state.notified_status.get("TAIEX") != cmd:
            send_discord_message(f"🌐 **大盤戰情變更**：{cmd}\n指數：{m_last['close']:.2f}")
            st.session_state.notified_status["TAIEX"] = cmd

        c1, c2 = st.columns([1, 2])
        with c1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with c2: st.markdown(f"<div class='status-card {clz}'>{cmd} | {tip} (評分: {score})</div>", unsafe_allow_html=True)
        with st.expander("大盤走勢細節"): st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 指數"), use_container_width=True)

    # 個股戰情區
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
        is_inv, is_snipe = sid in inv_list, sid in snipe_list

        # 通知判定
        sig_lvl = f"{'INV' if is_inv else 'SNP'}_{last['sig_type']}_{'BOOM' if (last['sig_type']=='BUY' and last['vol_ratio']>1.8) else 'NOR'}"
        if st.session_state.notified_status.get(sid) != sig_lvl:
            should_send = False
            msg_header = f"### {'📦 庫存' if is_inv else '🎯 狙擊'} 訊號觸發：{sid} {name}"
            if is_inv and last["sig_type"] == "SELL":
                should_send, reason = True, f"🩸 庫存賣點：{last['warning']}"
            elif is_snipe:
                if last["sig_type"] == "BUY" and last["vol_ratio"] > 1.8:
                    should_send, reason = True, f"⚡ 🔥【狙擊目標確認】🔥 爆量突破：{last['warning']}"
                    msg_header = f"## 🔥【狙擊目標確認】🔥\n# {sid} {name} 絕對注意！"
                elif last["sig_type"] == "BUY":
                    should_send, reason = True, f"🏹 買點出現：{last['warning']}"
                elif last["close"] > last["ma5"] and last["vol_ratio"] < 1:
                    should_send, reason = True, "⚪ 量縮站穩5MA(追蹤買點)"
            if should_send:
                discord_msg = (f"{msg_header}\n原因: `{reason}`\n現價: `{last['close']:.2f}`\n提醒: {last['warning']}")
                send_discord_message(discord_msg)
                add_log(f"{sid} {name} -> {reason}")
                st.session_state.notified_status[sid] = sig_lvl

        # UI 卡片
        is_boom = (is_snipe and last["sig_type"]=="BUY" and last["vol_ratio"]>1.8)
        border_clr = "#ff4b4b" if last["sig_type"]=="BUY" else ("#28a745" if last["sig_type"]=="SELL" else "#ccc")
        st.markdown(f"""
        <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border_clr}; margin-bottom:10px; text-align:left;">
            <div style="display:flex; justify-content:space-between;">
                <b>{'📦' if is_inv else '🎯'} {sid} {name} | {last['close']:.2f}</b>
                <span style="background:{border_clr}; color:white; padding:2px 10px; border-radius:10px;">評分: {last['score']}</span>
            </div>
            <div style="font-size:0.9em; margin-top:5px; color:#555;">提醒: {last['warning']} | 5MA乖離: {last['bias_5']:.2f}% | 預估量比: {last['vol_ratio']:.2f}x</div>
        </div>
        """, unsafe_allow_html=True)
        with st.expander(f"詳細分析 {sid} {name}"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {name}"), use_container_width=True)
        scan_results.append({"類別": "庫存" if is_inv else "狙擊", "代碼": sid, "名稱": name, "分數": last["score"], "提醒": last["warning"]})

    # 結果清單
    if scan_results:
        st.divider()
        res_df = pd.DataFrame(scan_results)
        c1, c2 = st.columns(2)
        with c1: st.write("### 🎯 狙擊排行"); st.dataframe(res_df[res_df["類別"]=="狙擊"].sort_values("分數", ascending=False), hide_index=True)
        with c2: st.write("### 📦 庫存監控"); st.dataframe(res_df[res_df["類別"]=="庫存"].sort_values("分數", ascending=False), hide_index=True)
    
    st.write("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{'<br>'.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 10. 主循環與自動化 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    while True:
        with placeholder.container(): perform_scan()
        wait = interval if is_market_open() else 60
        time.sleep(wait * 60)
        st.rerun()
else:
    with placeholder.container(): perform_scan()
