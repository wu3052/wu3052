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

# --- 1. 頁面配置與進階 CSS (改回白底典雅風格) ---
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max V2", page_icon="🏹")

st.markdown("""
<style>
    /* 全局底色與文字 */
    .main { background-color: #f8f9fa; color: #333333; }
    .stApp { background-color: #f8f9fa; }
    
    /* 典雅指標卡片設計 */
    .stMetric { 
        background-color: #ffffff; 
        padding: 20px; 
        border-radius: 12px; 
        border: 1px solid #eaeaea; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.03); 
    }
    [data-testid="stMetricValue"] { color: #212529 !important; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; }
    
    /* 專業狀態顯示卡 */
    .status-card { padding: 20px; border-radius: 10px; margin-bottom: 20px; font-weight: 700; font-size: 1.2em; text-align: center; }
    .buy-signal { background-color: #fff1f0; color: #cf1322; border: 1px solid #ffa39e; }
    .sell-signal { background-color: #f6ffed; color: #389e0d; border: 1px solid #b7eb8f; }
    .neutral-signal { background-color: #f5f5f5; color: #595959; border: 1px solid #d9d9d9; }
    
    /* 個股監控盒 (典雅白) */
    .dashboard-box { 
        background: #ffffff; 
        padding: 20px; 
        border-radius: 12px; 
        border: 1px solid #eaeaea; 
        margin-bottom: 15px;
        transition: box-shadow 0.2s;
    }
    .dashboard-box:hover { box-shadow: 0 4px 8px rgba(0,0,0,0.05); }
    
    /* 強力噴發特效 (點綴型) */
    .highlight-snipe { 
        background-color: #fff1f0 !important;
        border: 2px solid #ff4d4f !important; 
        animation: pulse-red 2.5s infinite; 
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 77, 79, 0.2); }
        70% { box-shadow: 0 0 0 10px rgba(255, 77, 79, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 77, 79, 0); }
    }
    
    /* 戰情日誌風格 (白底清爽) */
    .log-container { 
        background: #ffffff; 
        color: #595959; 
        padding: 15px; 
        border-radius: 8px; 
        font-family: 'Consolas', 'Monaco', monospace; 
        height: 400px; 
        overflow-y: auto; 
        border: 1px solid #eaeaea;
        font-size: 0.9em;
        line-height: 1.6;
    }
    .log-entry { border-bottom: 1px solid #f0f0f0; padding: 8px 0; display: flex; align-items: flex-start; }
    .log-time { color: #1890ff; font-weight: bold; margin-right: 10px; min-width: 75px; }
    .log-tag { padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 8px; font-weight: bold; }
    .tag-buy { background-color: #ff4d4f; color: white; }
    .tag-sell { background-color: #52c41a; color: white; }
    .tag-info { background-color: #bfbfbf; color: white; }
    
    /* Sidebar 樣式微調 */
    .css-163rgb7 { background-color: #ffffff; border-right: 1px solid #eaeaea; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
def init_session():
    states = {
        'notified_status': {},
        'last_notified_price': {},
        'notified_date': {}, 
        'event_log': [],
        'sid_map': {},
        'search_codes': "",
        'inventory_codes': "",
        'first_sync_done': False,
        'market_score': 50,
        'mute_notifications': False  # 需求 1: 手動停止傳送狀態
    }
    for key, val in states.items():
        if key not in st.session_state:
            st.session_state[key] = val

init_session()

# --- 3. 核心工具模組 ---
def get_taiwan_time():
    """獲取台灣標準時間"""
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    """判斷台股開盤時間: 週一至週五 09:00 - 13:35"""
    now = get_taiwan_time()
    if now.weekday() > 4: return False # 平日判斷
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return start_time <= now.time() <= end_time

def get_yf_ticker(sid):
    """轉換台灣股號為 Yahoo Finance 格式"""
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
    return f"{sid}.TW" # 預設

def send_discord_message(msg):
    """
    發送訊息到 Discord (整合需求 1: 手動停止判斷)
    """
    if st.session_state.mute_notifications: return 
    
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10)
    except: pass

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    """寫入內部戰情日誌"""
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-info"
    if tag_type == "BUY": tag_class = "tag-buy"
    elif tag_type == "SELL": tag_class = "tag-sell"
    
    score_html = f" | 分數: <b>{score}</b>" if score is not None else ""
    vol_html = f" | 量比: <b>{vol_ratio:.2f}x</b>" if vol_ratio is not None else ""
    
    log_html = (f"<div class='log-entry'>"
                f"<span class='log-time'>{ts}</span> "
                f"<span class='log-tag {tag_class}'>{tag_type}</span> "
                f"<b>{sid} {name}</b> -> {msg}{score_html}{vol_html}</div>")
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 150: st.session_state.event_log.pop()

# --- 4. 數據獲取引擎 ---
def calculate_est_volume(current_vol):
    """預估今日收盤成交量 (典雅版平滑計算)"""
    now = get_taiwan_time()
    current_minutes = now.hour * 60 + now.minute
    start_minutes = 9 * 60 # 09:00
    passed = current_minutes - start_minutes
    if passed <= 5: return current_vol * 2.8 # 開盤初期給予保守預估
    if passed >= 270: return current_vol     # 已收盤
    return current_vol * (270 / (passed + 5)) 

@st.cache_data(ttl=30 if is_market_open() else 3600)
def get_stock_data(sid, token):
    """獲取FinMind與yfinance混合數據"""
    try:
        # 歷史資料
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date']); df = df.sort_values("date").reset_index(drop=True)

        # 即時資料整合
        if is_market_open() or sid == "TAIEX":
            ticker_str = get_yf_ticker(sid)
            yt = yf.download(ticker_str, period="2d", interval="1m", progress=False, timeout=10)
            if not yt.empty:
                last_price = float(yt['Close'].iloc[-1])
                today_start = get_taiwan_time().replace(hour=9, minute=0, second=0, microsecond=0)
                today_yt = yt[yt.index >= today_start.strftime('%Y-%m-%d %H:%M:%S')]
                if not today_yt.empty:
                    day_vol, day_high, day_low = int(today_yt['Volume'].sum()), float(today_yt['High'].max()), float(today_yt['Low'].min())
                    if df.iloc[-1]['date'].date() == get_taiwan_time().date(): idx = df.index[-1]
                    else:
                        new_row = df.iloc[-1].copy(); new_row['date'] = pd.Timestamp(get_taiwan_time().date())
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True); idx = df.index[-1]
                    df.at[idx, 'close'], df.at[idx, 'high'], df.at[idx, 'low'], df.at[idx, 'volume'] = last_price, day_high, day_low, day_vol
                    df.at[idx, 'est_volume'] = calculate_est_volume(day_vol)
                else: df['est_volume'] = df['volume']
            else: df['est_volume'] = df['volume']
        else: df['est_volume'] = df['volume']
        return df
    except: return None

@st.cache_data(ttl=86400)
def get_stock_info():
    """獲取台股基本資訊"""
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        df = pd.DataFrame(res.json()["data"]); df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# --- 5. 核心策略分析引擎 (旗艦邏輯無刪減) ---
def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 150: return None
    
    # 技術指標計算
    for ma in [5, 10, 20, 60, 200]: df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD
    exp1, exp2 = df['close'].ewm(span=12, adjust=False).mean(), df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2; df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']; df = df.ffill().bfill()
    
    # 乖離、量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵轉折與發動點
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx, row, prev = df.index[-1], df.iloc[-1], df.iloc[-2]
    
    # --- 形態偵測 ---
    ma_short_prev = [prev["ma5"], prev["ma10"], prev["ma20"]]
    ma_long_curr = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_long_curr = (max(ma_long_curr) - min(ma_long_curr)) / row["close"]
    ma5_up_curr = row["ma5"] > prev["ma5"]
    
    # 噴發邏輯 (0.03 糾結)
    was_tangling_prev = (max(ma_short_prev) - min(ma_short_prev)) / prev["close"] < 0.03
    is_first_breakout = (was_tangling_prev and row["close"] > max(ma_short_prev) and row["vol_ratio"] > 1.2 and ma5_up_curr)
    df.at[last_idx, "is_first_breakout"] = is_first_breakout

    pattern_name = "一般盤整"
    pattern_desc = "目前處於無明顯趨勢的整理區間。建議耐心等待均線糾結後的方向突破。"

    if is_first_breakout:
        pattern_name = "🚀 噴發第一根"
        pattern_desc = "均線糾結後首次帶量突破，慣性徹底改變，極具爆發力的進場點。"
    elif diff_long_curr < 0.02 and row["close"] > row["ma5"] and ma5_up_curr:
        pattern_name = "💎 鑽石眼"
        pattern_desc = "四線合一且 5MA 轉強，是飆股噴發前的典型特徵。"
    elif row["close"] > max(ma_long_curr) and prev["close"] <= max(ma_long_curr):
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "突破所有長期壓力，進入主升段。勇敢加碼。"
    elif (max(ma_short_prev) - min(ma_short_prev))/row["close"] < 0.015 and row["close"] > row["ma5"] and ma5_up_curr:
        pattern_name = "🟡 黃金眼"
        pattern_desc = "短期均線同步發散，底部翻多的強烈訊號。"
    
    df.at[last_idx, "pattern"] = pattern_name; df.at[last_idx, "pattern_desc"] = pattern_desc

    # --- 買賣點與位階提示修正 (需求 3) ---
    buy_pts, sell_pts = [], []
    
    # 基礎指標判斷
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上關鍵壓力(轉強)")

    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(減碼)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破關鍵支撐(轉弱)")

    # 決定訊號類型與位階提示文字 (需求 3: 賣出時顯示跌破頭部)
    final_warnings = []
    if len(buy_pts) >= len(sell_pts) and len(buy_pts) > 0:
        if row["low"] >= prev["low"]: final_warnings.append("底部位階支撐(1日不創新低)")
        final_warnings.extend(buy_pts); sig = "BUY"
    elif len(sell_pts) > 0:
        if row["high"] <= prev["high"]: final_warnings.append("頭部位階跌破(1日不創新高)")
        final_warnings.extend(sell_pts); sig = "SELL"
    else: sig = "HOLD"

    # 綜合評分
    score = 50 + (15 * len([p for p in buy_pts if "買點" in p or "支撐" in p])) - (20 * len([p for p in sell_pts if "賣點" in p or "跌破" in p]))
    if row["vol_ratio"] > 1.8: score += 12
    if row["is_weekly_bull"]: score += 8
    if not is_market and st.session_state.market_score < 40: score -= 20
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(final_warnings) if final_warnings else "趨勢穩定中"
    df.at[last_idx, "sig_type"] = sig
    
    # 倉位配置
    risk_pct = (row["atr"] / row["close"]) * 100
    if risk_pct < 1.5: pos = "配置: 15~20%"
    elif risk_pct < 3.0: pos = "配置: 8~12%"
    else: pos = "配置: 3~5%"
    df.at[last_idx, "pos_advice"] = pos
    
    return df

# --- 6. 典雅版圖表引擎 (Plotly White) ---
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])
    
    # K 線 (專業紅綠)
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], 
        name="K線", increasing_line_color='#cf1322', decreasing_line_color='#389e0d',
        increasing_fillcolor='#cf1322', decreasing_fillcolor='#389e0d'
    ), row=1, col=1)
    
    # 均線 (專業色調)
    ma_map = {5: '#1890ff', 10: '#faad14', 20: '#f56a00', 60: '#722ed1'}
    for ma, color in ma_map.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    # 標記噴發點
    if "is_first_breakout" in df_plot.columns:
        breakouts = df_plot[df_plot["is_first_breakout"] == True]
        if not breakouts.empty:
            fig.add_trace(go.Scatter(
                x=breakouts["date"], y=breakouts["low"] * 0.96,
                mode="markers+text", marker=dict(symbol="triangle-up", size=16, color="#cf1322"),
                text="🚀噴發", textposition="bottom center", name="噴發點"
            ), row=1, col=1)

    # MACD
    colors = ['#cf1322' if v >= 0 else '#389e0d' for v in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    
    fig.update_layout(
        height=600, title=title, template="plotly_white", xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(showgrid=False); fig.update_yaxes(showgrid=True, gridcolor="#f0f0f0")
    return fig

# --- 7. 資料同步 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(url)
        def clean(col): return " ".join(df_sheet[col].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
        st.session_state.search_codes = clean('snipe_list')
        st.session_state.inventory_codes = clean('inventory_list')
        add_log("SYS", "SYSTEM", "INFO", "雲端清單同步完成")
    except: st.error("同步失敗，請檢查網路或 Sheet ID")

# --- 8. 側邊指揮中心 ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center; color: #cf1322; font-family:serif;'>SNIPER COMMAND</h1>", unsafe_allow_html=True)
    st.divider()
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    if st.button("🔄 同步雲端清單", use_container_width=True):
        sync_sheets(); st.rerun()
    st.session_state.search_codes = st.text_area("🎯 狙擊清單 (股號空格分隔)", value=st.session_state.search_codes, height=120)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes, height=120)
    
    st.divider()
    # 整合需求 1: 加入停止按鈕
    st.session_state.mute_notifications = st.toggle("🚫 暫停所有訊息傳送 (Discord)", value=st.session_state.mute_notifications, help="開啟後系統仍會掃描並記錄日誌，但不會發送 Discord 通知。避免非開盤期間的干擾。")
    
    interval = st.slider("自動監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動化循環監控", value=True)
    analyze_btn = st.button("🚀 執行手動全局掃描", use_container_width=True)
    
    is_open = is_market_open()
    status_clr = "#cf1322" if is_open else "#389e0d"
    st.markdown(f"""
    <div style='background:#ffffff; padding:15px; border-radius:10px; border:1px solid #eaeaea; text-align:center;'>
        目前時間: <b>{get_taiwan_time().strftime('%H:%M:%S')}</b><br>
        市場狀態: <b style='color:{status_clr}'>{'🔴 盤中交易' if is_open else '🟢 市場收盤'}</b>
    </div>
    """, unsafe_allow_html=True)

# --- 9. 掃描與顯示邏輯 ---
def perform_scan():
    today_str = get_taiwan_time().strftime('%Y-%m-%d'); now = get_taiwan_time()
    st.markdown(f"### 📡 執行時間：`{now.strftime('%Y-%m-%d %H:%M:%S')}`")
    
    # 清單解析
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    if not all_codes: st.warning("請先於側邊欄輸入股號或同步雲端清單。"); return

    stock_info, processed_stocks = get_stock_info(), []

    # A. 大盤分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True); m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]; score = m_last["score"]
        if score >= 65: cmd, clz = "🚀 多頭強勁", "buy-signal"
        elif score >= 45: cmd, clz = "🌪 震盪整理", "neutral-signal"
        else: cmd, clz = "📉 空頭警戒", "sell-signal"
        
        c1, c2 = st.columns([1, 2])
        with c1: st.metric("台股加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with c2: st.markdown(f"<div class='status-card {clz}'>{cmd} (評分: {score})</div>", unsafe_allow_html=True)

    # B. 多執行緒個股掃描
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None or len(df) < 10: continue
                df = analyze_strategy(df)
                last = df.iloc[-1]
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                
                # 通知與日誌
                sig_type = last['sig_type']; old_sig, old_date = st.session_state.notified_status.get(sid), st.session_state.notified_date.get(sid)
                if (old_date != today_str or old_sig != sig_type) and sig_type != "HOLD":
                    is_inv, is_snipe = sid in inv_list, sid in snipe_list
                    # 庫存股只報賣，狙擊股只報買
                    should_notify = (is_inv and sig_type == "SELL") or (is_snipe and sig_type == "BUY")
                    if should_notify:
                        header = "🏹 狙擊目標確認" if sig_type == "BUY" else "🩸 庫存風險警示"
                        msg = (f"{header}\n代碼: `{sid} {name}`\n價格: `{last['close']:.2f}`\n"
                               f"型態: `{last['pattern']}`\n提醒: `{last['warning']}`\n"
                               f"量比: `{last['vol_ratio']:.2f}x` | 時間: `{get_taiwan_time().strftime('%H:%M:%S')}`")
                        send_discord_message(msg)
                        add_log(sid, name, sig_type, last['warning'], last['score'], last['vol_ratio'])
                        st.session_state.notified_status[sid], st.session_state.notified_date[sid] = sig_type, today_str
                
                processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_snipe": sid in snipe_list, "is_inv": sid in inv_list})
            except: continue

    # C. 分區顯示
    col_s, col_i = st.tabs(["🎯 狙擊目標監控", "📦 庫存水位監控"])
    
    with col_s:
        snipe_sorted = sorted([s for s in processed_stocks if s["is_snipe"]], key=lambda x: x["last"]["score"], reverse=True)
        for item in snipe_sorted:
            last, sid, name = item["last"], item["sid"], item["name"]
            border = "#cf1322" if last["sig_type"] == "BUY" else "#d9d9d9"
            highlight = "highlight-snipe" if (last["sig_type"] == "BUY" and last["vol_ratio"] > 1.8) else ""
            st.markdown(f"""
            <div class="dashboard-box {highlight}" style="border-left: 10px solid {border};">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:1.1em;"><b>🎯 {sid} {name}</b> | 現價: <b>{last['close']:.2f}</b></span>
                    <span style="background:{border}; color:white; padding:2px 10px; border-radius:20px; font-size:0.8em;">評分: {last['score']}</span>
                </div>
                <div style="margin-top:8px; color:#595959; font-size:0.9em;">
                    提醒: <span style="color:#cf1322"><b>{last['warning']}</b></span> | 型態: {last['pattern']}<br>
                    {last['pos_advice']} | 預估量比: {last['vol_ratio']:.2f}x
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 分析圖表"): st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name} 技術分析"), use_container_width=True)

    with col_i:
        inv_sorted = sorted([s for s in processed_stocks if s["is_inv"]], key=lambda x: x["last"]["score"], reverse=True)
        for item in inv_sorted:
            last, sid, name = item["last"], item["sid"], item["name"]
            border = "#389e0d" if last["sig_type"] == "SELL" else "#d9d9d9"
            st.markdown(f"""
            <div class="dashboard-box" style="border-left: 10px solid {border};">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:1.1em;"><b>📦 {sid} {name}</b> | 現價: <b>{last['close']:.2f}</b></span>
                    <span style="background:#f5f5f5; color:#595959; padding:2px 10px; border-radius:20px; font-size:0.8em;">健康度: {last['score']}</span>
                </div>
                <div style="margin-top:8px; color:#595959; font-size:0.9em;">
                    風險提醒: <span style="color:#212529"><b>{last['warning']}</b></span> | 5MA乖離: {last['bias_5']:.2f}%<br>
                    技術型態解讀: {last['pattern_desc']}
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 持股監控圖表"): st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name} 持股監控"), use_container_width=True)

    # D. 即時日誌
    st.divider(); st.markdown("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 10. 主循環與自動化控制 (整合需求 2) ---
placeholder = st.empty()

if analyze_btn:
    with placeholder.container(): perform_scan()
elif auto_monitor:
    # 整合需求 2: 自動判斷開盤期間
    if is_market_open():
        with placeholder.container(): perform_scan()
        st.caption(f"🔄 自動監控中... 下次重整: {(get_taiwan_time() + timedelta(minutes=interval)).strftime('%H:%M:%S')}")
        time.sleep(interval * 60); st.rerun()
    else:
        # 收盤期間邏輯
        with placeholder.container():
            st.markdown(f"""
            <div style='background-color:#ffffff; padding:30px; border-radius:15px; border:1px solid #eaeaea; text-align:center;'>
                <h1 style='color:#595959;'>🌙 市場收盤中</h1>
                <p style='color:#8c8c8c;'>台股交易時段為週一至週五 09:00 ~ 13:35。<br>
                自動監控已暫停，系統將在開盤時自動啟動。<br>
                目前台灣時間: <b>{get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')}</b></p>
            </div>
            """, unsafe_allow_html=True)
            # 靜態顯示上一次的日誌方便查閱
            if st.session_state.event_log:
                st.divider(); st.markdown("### 📜 昨日/歷史戰情日誌 (靜態)")
                st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)
        # 非開盤期間，降低檢查頻率（每10分鐘檢查一次是否到了開盤時間）
        time.sleep(600); st.rerun()
else:
    # 靜態顯示
    with placeholder.container():
        if st.session_state.event_log:
            st.divider(); st.markdown("### 📜 戰情日誌 (靜態顯示)")
            st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

