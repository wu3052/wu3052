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
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max V2", page_icon="🏹")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; font-size: 1.2em; text-align: center; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .neutral-signal { background-color: #6c757d; color: white; border-left: 8px solid #343a40; }
    .dashboard-box { background: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #e0e0e0; text-align: center; height: 100%; transition: 0.3s; }
    
    /* 戰情日誌風格 */
    .log-container { 
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
        color: #e2e8f0; 
        padding: 20px; 
        border-radius: 12px; 
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
        height: 400px; 
        overflow-y: scroll; 
        border: 1px solid #334155;
        box-shadow: inset 0 2px 10px rgba(0,0,0,0.3);
        line-height: 1.6;
    }
    .log-entry { 
        border-bottom: 1px solid #334155; 
        padding: 8px 0; 
        font-size: 0.9em;
    }
    .log-time { color: #38bdf8; font-weight: bold; margin-right: 10px; }
    .log-tag { padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 5px; font-weight: bold; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #64748b; color: white; }
    
    .highlight-snipe { 
        background-color: #fff5f5; 
        border: 2px solid #ff4b4b !important; 
        animation: pulse-red 2s infinite; 
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
if 'notified_status' not in st.session_state: st.session_state.notified_status = {}
if 'last_notified_price' not in st.session_state: st.session_state.last_notified_price = {}
if 'notified_date' not in st.session_state: st.session_state.notified_date = {} 
if 'event_log' not in st.session_state: st.session_state.event_log = []
if 'sid_map' not in st.session_state: st.session_state.sid_map = {}
if 'search_codes' not in st.session_state: st.session_state.search_codes = ""
if 'inventory_codes' not in st.session_state: st.session_state.inventory_codes = ""
if 'first_sync_done' not in st.session_state: st.session_state.first_sync_done = False
if 'market_score' not in st.session_state: st.session_state.market_score = 50

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
        try:
            if t.fast_info.get('previous_close') is not None:
                st.session_state.sid_map[sid] = f"{sid}{suffix}"
                return f"{sid}{suffix}"
        except: continue
    return f"{sid}.TW"

def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10)
    except Exception: pass

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-info"
    if tag_type == "BUY": tag_class = "tag-buy"
    elif tag_type == "SELL": tag_class = "tag-sell"
    
    score_html = f" | 評分: <b>{score}</b>" if score else ""
    vol_html = f" | 量比: <b>{vol_ratio:.2f}x</b>" if vol_ratio else ""
    
    log_html = (f"<div class='log-entry'>"
                f"<span class='log-time'>[{ts}]</span> "
                f"<span class='log-tag {tag_class}'>{tag_type}</span> "
                f"<b>{sid} {name}</b> -> {msg}{score_html}{vol_html}</div>")
    
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 100: st.session_state.event_log.pop()

# --- 4. 數據獲取 ---
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

# --- 5. 核心策略分析 ---
def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 200: return None
    
    # 基本均線
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 策略指標 (包含 60分線模擬)
    df["ma144_60min"] = df["close"].rolling(36).mean() # 模擬60分144MA (約等同日線36MA)
    df["ma55_60min"] = df["close"].rolling(14).mean()  # 模擬60分55MA (約等同日線14MA)
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵轉折位
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR 資金控管
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # 形態偵測邏輯
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max([row["ma5"], row["ma10"], row["ma20"]]) - min([row["ma5"], row["ma10"], row["ma20"]])) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    
    pattern_name, pattern_desc = "一般盤整", "目前處於無明顯趨勢的整理區間。建議耐心等待均線糾結後的方向突破。"

    if diff_long < 0.02 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        pattern_name, pattern_desc = "💎 鑽石眼", "「四線或五線合一」是「超級飆股」的訊號，股價將展開「無壓力」的飆升。"
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        pattern_name, pattern_desc = "🕳️ 鑽石坑", "成功克服了市場的所有長期壓力，是「主升段」的開始，「勇敢加碼」。"
    elif diff_short < 0.015 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        pattern_name, pattern_desc = "🟡 黃金眼", "均線將同步向上發散，「三均線整齊排列」，「底部翻多」的最強訊號。"
    elif row["ma5"] > row["ma10"] and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        pattern_name, pattern_desc = "📐 黃金三角眼", "多頭一浪啟動！標誌空頭盤整結束與新上漲慣性開始，「試單進場點」。"
    
    # 訊號判定 (完整買賣點定義)
    buy_pts, sell_pts = [], []
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死亡交叉關鍵位(上漲買入)")

    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破黃金交叉關鍵位(下跌賣出)")

    # 評分系統
    score = 50
    if buy_pts: score += 15 * len(buy_pts)
    if sell_pts: score -= 20 * len(sell_pts)
    if row["vol_ratio"] > 1.8: score += 10
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    if not is_market and st.session_state.market_score < 40: score -= 20
    
    # 寫入結果
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定中"
    
    sig = "HOLD"
    if buy_pts: sig = "BUY"
    if sell_pts: sig = "SELL"
    if not is_market and st.session_state.market_score < 40 and sig == "BUY": sig = "HOLD (大盤空頭避險)"
    df.at[last_idx, "sig_type"] = sig
    
    risk_volatility = (row["atr"] / row["close"]) * 100
    if risk_volatility < 1.5: pos_advice = "建議配置: 15~20% (穩健型)"
    elif risk_volatility < 3.0: pos_advice = "建議配置: 8~12% (標準型)"
    else: pos_advice = "建議配置: 3~5% (高波動小心)"
    df.at[last_idx, "pos_advice"] = pos_advice
    
    return df

# --- 6. 視覺化模組 ---
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線", increasing_line_color='#ff4b4b', decreasing_line_color='#28a745'), row=1, col=1)
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    colors = ['#ff4b4b' if val >= 0 else '#28a745' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    fig.update_layout(height=650, title=title, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    return fig

# --- 7. Google 表單同步 ---
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
        add_log("SYS", "SYSTEM", "INFO", "成功從 Google 表單同步數據")
    except Exception as e: st.error(f"同步失敗: {e}")

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
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    st.markdown(f"### 📡 掃描時間：{get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')}")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    # 大盤掃描
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        score = m_last["score"]
        if score >= 60: cmd, clz = "📈 分批買進", "buy-signal"
        elif score >= 40: cmd, clz = "Neutral 觀望", "neutral-signal"
        else: cmd, clz = "📉 減碼避險", "sell-signal"
        
        c1, c2 = st.columns([1, 2])
        with c1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with c2: st.markdown(f"<div class='status-card {clz}'>{cmd} | 大盤評分: {score}</div>", unsafe_allow_html=True)

    # 個股處理
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df, is_market=False)
        last = df.iloc[-1]
        name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
        is_inv, is_snipe = sid in inv_list, sid in snipe_list
        
        sig_type = last['sig_type']
        sig_lvl = f"{sig_type}_{'BOOM' if (sig_type=='BUY' and last['vol_ratio']>1.8) else 'NOR'}"
        
        # 判斷是否發送訊息
        old_sig = st.session_state.notified_status.get(sid)
        old_date = st.session_state.notified_date.get(sid)
        should_send = False

        if old_date != today_str or old_sig != sig_lvl:
            if (is_inv and sig_type == "SELL") or (is_snipe and "BUY" in sig_type):
                should_send = True
        
        if should_send:
            msg_header = "🔥🔥 【 狙 擊 目 標 確 認 】 🔥🔥" if last['vol_ratio'] > 1.8 else "🏹 【 買 賣 訊 號 觸 發 】"
            if sig_type == "SELL": msg_header = "🩸 【 庫 存 風 險 警 示 】"
            
            discord_msg = (f"{msg_header}\n"
                           f"---------------------------------------------------\n"
                           f"股價代號 : `{sid} {name}`\n"
                           f"現價 : `{last['close']:.2f}`\n"
                           f"技術型態 : `{last['pattern']}`\n"
                           f"戰鬥評分 : `{last['score']}`\n"
                           f"提醒 : `{last['warning']}`\n"
                           f"💡 形態解讀：{last['pattern_desc']}\n"
                           f"📍 `{last['pos_advice']}`\n"
                           f"預估量比 : `{last['vol_ratio']:.2f}x`\n"
                           f"---------------------------------------------------")
            send_discord_message(discord_msg)
            add_log(sid, name, "BUY" if "BUY" in sig_type else "SELL", f"{last['warning']} | {last['pattern']}", last['score'], last['vol_ratio'])
            st.session_state.notified_status[sid] = sig_lvl
            st.session_state.notified_date[sid] = today_str

        processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_inv": is_inv, "is_snipe": is_snipe, "score": last["score"]})

    # --- UI 顯示區 ---
    st.subheader("🔥 狙擊目標監控")
    for item in sorted([s for s in processed_stocks if s["is_snipe"]], key=lambda x: x["score"], reverse=True):
        last, sid, name = item["last"], item["sid"], item["name"]
        is_boom = (last["vol_ratio"] > 1.8)
        st.markdown(f"""<div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid #ff4b4b; margin-bottom:10px; text-align:left;">
            <b>🎯 {sid} {name} | 現價: {last['close']:.2f} | {last['pattern']}</b> | 分數: {last['score']}<br>
            <small>{last['pattern_desc']}</small><br>
            <b>{last['pos_advice']}</b> | 提醒: {last['warning']} | 量比: {last['vol_ratio']:.2f}x
        </div>""", unsafe_allow_html=True)
        with st.expander(f"查看 {sid} 分析圖表"): st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name}"), use_container_width=True)

    st.subheader("📦 庫存持股監控")
    for item in sorted([s for s in processed_stocks if s["is_inv"]], key=lambda x: x["score"], reverse=True):
        last, sid, name = item["last"], item["sid"], item["name"]
        st.markdown(f"""<div class="dashboard-box" style="border-left: 10px solid #28a745; margin-bottom:10px; text-align:left;">
            <b>📦 {sid} {name} | 現價: {last['close']:.2f} | {last['pattern']}</b> | 健康評分: {last['score']}<br>
            提醒: {last['warning']} | 乖離: {last['bias_5']:.2f}%
        </div>""", unsafe_allow_html=True)

    st.divider()
    st.write("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 10. 主循環 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    while True:
        with placeholder.container(): perform_scan()
        time.sleep(interval * 60)
        st.rerun()
else:
    with placeholder.container(): perform_scan()
