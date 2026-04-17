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
from concurrent.futures import ThreadPoolExecutor

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
    """判斷是否為台股開盤時段: 週一至週五 09:00 ~ 13:35"""
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

def get_yf_ticker(sid):
    if sid == "TAIEX": return "^TWII"
    if sid in st.session_state.sid_map: return st.session_state.sid_map[sid]
    for suffix in [".TW", ".TWO"]:
        ticker = f"{sid}{suffix}"
        try:
            t = yf.Ticker(ticker)
            if t.fast_info.get('lastPrice') is not None:
                st.session_state.sid_map[sid] = ticker
                return ticker
        except: continue
    return f"{sid}.TW"

def send_discord_message(msg):
    # 如果手動勾選停止傳送，則直接跳過
    if st.session_state.get("stop_discord", False):
        return
    
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
    score_html = f" | 評分: <b>{score}</b>" if score is not None else ""
    vol_html = f" | 量比: <b>{vol_ratio:.2f}x</b>" if vol_ratio is not None else ""
    log_html = (f"<div class='log-entry'><span class='log-time'>[{ts}]</span> "
                f"<span class='log-tag {tag_class}'>{tag_type}</span> "
                f"<b>{sid} {name}</b> -> {msg}{score_html}{vol_html}</div>")
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 100: st.session_state.event_log.pop()

# --- 4. 數據獲取與預估成交量 ---
def calculate_est_volume(current_vol):
    now = get_taiwan_time()
    current_minutes = now.hour * 60 + now.minute
    start_minutes = 9 * 60
    passed = current_minutes - start_minutes
    if passed <= 5: return current_vol * 3  
    if passed >= 270: return current_vol
    return current_vol * (270 / (passed + 10)) 

@st.cache_data(ttl=30 if is_market_open() else 3600)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        if is_market_open() or sid == "TAIEX":
            ticker_str = get_yf_ticker(sid)
            yt = yf.download(ticker_str, period="2d", interval="1m", progress=False, timeout=10)
            if not yt.empty:
                last_price = float(yt['Close'].iloc[-1])
                today_start = get_taiwan_time().replace(hour=9, minute=0, second=0, microsecond=0)
                today_yt = yt[yt.index >= today_start.strftime('%Y-%m-%d %H:%M:%S')]
                if not today_yt.empty:
                    day_vol, day_high, day_low = int(today_yt['Volume'].sum()), float(today_yt['High'].max()), float(today_yt['Low'].min())
                    if df.iloc[-1]['date'].date() == get_taiwan_time().date():
                        idx = df.index[-1]
                    else:
                        new_row = df.iloc[-1].copy()
                        new_row['date'] = pd.Timestamp(get_taiwan_time().date())
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        idx = df.index[-1]
                    df.at[idx, 'close'], df.at[idx, 'high'], df.at[idx, 'low'], df.at[idx, 'volume'] = last_price, day_high, day_low, day_vol
                    df.at[idx, 'est_volume'] = calculate_est_volume(day_vol)
                else: df['est_volume'] = df['volume']
            else: df['est_volume'] = df['volume']
        else: df['est_volume'] = df['volume']
        return df
    except: return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# --- 5. 核心策略分析 ---
def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 180: return None
    for ma in [5, 10, 20, 55, 60, 200]: df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["ma55_60min"] = df["close"].rolling(14).mean()
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))
    
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    df = df.ffill().bfill()
    
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row, prev = df.iloc[-1], df.iloc[-2]
    
    # --- 形態 ---
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    ma5_up = row["ma5"] > prev["ma5"]
    was_tangling = (max([prev["ma5"], prev["ma10"], prev["ma20"]]) - min([prev["ma5"], prev["ma10"], prev["ma20"]])) / prev["close"] < 0.03
    is_first_breakout = was_tangling and row["close"] > max([prev["ma5"], prev["ma10"], prev["ma20"]]) and row["vol_ratio"] > 1.2 and ma5_up
    df.at[last_idx, "is_first_breakout"] = is_first_breakout

    pattern_name = "一般盤整"
    if is_first_breakout: pattern_name = "🚀 噴發第一根"
    elif diff_long < 0.02 and row["close"] > row["ma5"] and ma5_up: pattern_name = "💎 鑽石眼"
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long): pattern_name = "🕳️ 鑽石坑"
    
    df.at[last_idx, "pattern"] = pattern_name

    # --- 買賣點與位階提示修正 ---
    buy_pts, sell_pts = [], []
    
    # 判斷 K 棒位階 (修正邏輯)
    is_no_new_low = row["low"] >= prev["low"]
    is_no_new_high = row["high"] <= prev["high"]

    # 基礎指標判斷
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")

    # 根據最終訊號類型決定位階提示文字
    final_warning_list = []
    if len(buy_pts) >= len(sell_pts) and len(buy_pts) > 0:
        if is_no_new_low: final_warning_list.append("底部位階支撐(1日不創新低)")
        final_warning_list.extend(buy_pts)
        sig = "BUY"
    elif len(sell_pts) > 0:
        if is_no_new_high: final_warning_list.append("頭部位階跌破(1日不創新高)")
        final_warning_list.extend(sell_pts)
        sig = "SELL"
    else:
        sig = "HOLD"

    score = 50 + (15 * len(buy_pts)) - (20 * len(sell_pts))
    if is_no_new_low: score += 5
    if row["vol_ratio"] > 1.8: score += 10
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(final_warning_list) if final_warning_list else "趨勢穩定中"
    df.at[last_idx, "sig_type"] = sig
    df.at[last_idx, "pos_advice"] = "建議配置: 8~12%"
    return df

def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線"), row=1, col=1)
    for ma, clr in {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6'}.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=clr, width=1.5)), row=1, col=1)
    fig.update_layout(height=600, title=title, template="plotly_white", xaxis_rangeslider_visible=False)
    return fig

# --- 7. Google 表單同步 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(url)
        st.session_state.search_codes = " ".join(df_sheet['snipe_list'].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
        st.session_state.inventory_codes = " ".join(df_sheet['inventory_list'].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
        add_log("SYS", "SYSTEM", "INFO", "成功從 Google 表單同步數據")
    except: st.error("同步失敗")

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
    
    st.divider()
    # 1. 手動停止按鈕
    st.session_state.stop_discord = st.toggle("🚫 暫停 Discord 訊息傳送", value=False)
    
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟盤中自動監控", value=True)
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)
    st.info(f"系統時間: {get_taiwan_time().strftime('%H:%M:%S')}\n市場狀態: {'🔴開盤中' if is_market_open() else '🟢已收盤'}")

# --- 9. 掃描邏輯 ---
def perform_scan():
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    stock_info = get_stock_info()
    processed_stocks = []

    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        st.session_state.market_score = m_df.iloc[-1]["score"]
        st.metric("加權指數", f"{m_df.iloc[-1]['close']:.2f}", f"{m_df.iloc[-1]['close']-m_df.iloc[-2]['close']:.2f}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            df = future.result()
            if df is None: continue
            df = analyze_strategy(df)
            last = df.iloc[-1]
            name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
            
            # 通知判斷
            sig_type = last['sig_type']
            old_sig, old_date = st.session_state.notified_status.get(sid), st.session_state.notified_date.get(sid)
            if old_date != today_str or old_sig != sig_type:
                if (sid in inv_list and sig_type == "SELL") or (sid in snipe_list and sig_type == "BUY"):
                    msg = f"【{sig_type} 訊號】{sid} {name}\n價格: {last['close']}\n提醒: {last['warning']}\n時間: {get_taiwan_time().strftime('%H:%M:%S')}"
                    send_discord_message(msg)
                    add_log(sid, name, sig_type, last['warning'], last['score'], last['vol_ratio'])
                    st.session_state.notified_status[sid], st.session_state.notified_date[sid] = sig_type, today_str
            
            processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_inv": sid in inv_list, "is_snipe": sid in snipe_list})

    for item in sorted(processed_stocks, key=lambda x: x['last']['score'], reverse=True):
        with st.expander(f"{'🎯' if item['is_snipe'] else '📦'} {item['sid']} {item['name']} - 評分: {item['last']['score']}"):
            st.write(f"提醒: {item['last']['warning']} | 型態: {item['last']['pattern']}")
            st.plotly_chart(plot_advanced_chart(item['df'], f"{item['sid']} {item['name']}"), use_container_width=True)

# --- 10. 主循環與自動啟動邏輯 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    # 2. 自動設定開盤期間啟動
    if is_market_open():
        with placeholder.container(): perform_scan()
        time.sleep(interval * 60)
        st.rerun()
    else:
        st.warning(f"🌙 非交易時段 (09:00~13:35)，自動監控暫停中。目前時間: {get_taiwan_time().strftime('%H:%M:%S')}")
        time.sleep(60) # 每分鐘檢查一次是否到開盤時間
        st.rerun()

