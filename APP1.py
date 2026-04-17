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

# --- 1. 頁面配置與極緻 CSS 樣式 ---
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max 旗艦版", page_icon="🏹")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
    
    .main { background-color: #0f172a; color: #f8fafc; }
    .stApp { background-color: #0f172a; }
    
    /* 指標卡片設計 */
    .stMetric { background-color: #1e293b; padding: 20px; border-radius: 15px; border: 1px solid #334155; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    [data-testid="stMetricValue"] { color: #f8fafc !important; font-family: 'JetBrains Mono', monospace; }
    
    /* 狀態顯示卡 */
    .status-card { padding: 25px; border-radius: 16px; margin-bottom: 25px; font-weight: 800; font-size: 1.4em; text-align: center; letter-spacing: 1px; }
    .buy-signal { background: linear-gradient(135deg, #ef4444 0%, #991b1b 100%); color: white; border: 1px solid #f87171; box-shadow: 0 0 20px rgba(239, 68, 68, 0.3); }
    .sell-signal { background: linear-gradient(135deg, #22c55e 0%, #166534 100%); color: white; border: 1px solid #4ade80; box-shadow: 0 0 20px rgba(34, 197, 94, 0.3); }
    .neutral-signal { background: linear-gradient(135deg, #64748b 0%, #334155 100%); color: white; border: 1px solid #94a3b8; }
    
    /* 個股監控盒 */
    .dashboard-box { 
        background: #1e293b; 
        padding: 24px; 
        border-radius: 18px; 
        border: 1px solid #334155; 
        margin-bottom: 15px;
        transition: transform 0.2s, box-shadow 0.2s;
    }
    .dashboard-box:hover { transform: translateY(-3px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.2); border-color: #475569; }
    
    /* 強力噴發特效 */
    .highlight-snipe { 
        background: linear-gradient(135deg, #1e293b 0%, #450a0a 100%) !important;
        border: 2px solid #ef4444 !important; 
        animation: pulse-red 2s infinite; 
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.5); }
        70% { box-shadow: 0 0 0 15px rgba(239, 68, 68, 0); }
        100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0); }
    }
    
    /* 戰情日誌風格 */
    .log-container { 
        background: #020617; 
        color: #94a3b8; 
        padding: 20px; 
        border-radius: 12px; 
        font-family: 'JetBrains Mono', monospace; 
        height: 450px; 
        overflow-y: auto; 
        border: 1px solid #1e293b;
        font-size: 0.85em;
    }
    .log-entry { border-bottom: 1px solid #1e293b; padding: 10px 0; display: flex; align-items: flex-start; }
    .log-time { color: #38bdf8; font-weight: bold; margin-right: 12px; min-width: 80px; }
    .log-tag { padding: 3px 8px; border-radius: 5px; font-size: 0.75em; margin-right: 10px; font-weight: bold; text-transform: uppercase; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #475569; color: #f1f5f9; }
    
    /* 自定義滾動條 */
    ::-webkit-scrollbar { width: 8px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 10px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
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
        'mute_notifications': False  # 手動停止傳送按鈕狀態
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
    """
    判斷台股開盤時間:
    週一至週五 09:00 - 13:35
    """
    now = get_taiwan_time()
    # 判斷平日 (0=週一, 4=週五)
    if now.weekday() > 4:
        return False
    
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    current_time = now.time()
    
    return start_time <= current_time <= end_time

def get_yf_ticker(sid):
    """轉換台灣股號為 Yahoo Finance 格式"""
    if sid == "TAIEX": return "^TWII"
    if sid in st.session_state.sid_map: return st.session_state.sid_map[sid]
    
    # 優先嘗試上市(.TW)，再嘗試上櫃(.TWO)
    for suffix in [".TW", ".TWO"]:
        ticker = f"{sid}{suffix}"
        try:
            t = yf.Ticker(ticker)
            if t.fast_info.get('lastPrice') is not None:
                st.session_state.sid_map[sid] = ticker
                return ticker
        except:
            continue
    return f"{sid}.TW" # 預設

def send_discord_message(msg):
    """
    發送訊息到 Discord
    整合需求 1: 加入手動停止判斷
    """
    if st.session_state.mute_notifications:
        return # 如果使用者勾選了暫停，則不執行
        
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
        
    try:
        payload = {"content": msg}
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Discord 發送失敗: {e}")

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    """寫入內部戰情日誌"""
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-info"
    if tag_type == "BUY": tag_class = "tag-buy"
    elif tag_type == "SELL": tag_class = "tag-sell"
    
    score_html = f" | 評分: <span style='color:#f8fafc'><b>{score}</b></span>" if score is not None else ""
    vol_html = f" | 量比: <span style='color:#38bdf8'><b>{vol_ratio:.2f}x</b></span>" if vol_ratio is not None else ""
    
    log_html = (f"<div class='log-entry'>"
                f"<span class='log-time'>[{ts}]</span> "
                f"<span class='log-tag {tag_class}'>{tag_type}</span> "
                f"<span style='color:#f1f5f9'><b>{sid} {name}</b></span> -> {msg}{score_html}{vol_html}</div>")
    
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 150:
        st.session_state.event_log.pop()

# --- 4. 數據獲取引擎 ---
def calculate_est_volume(current_vol):
    """預估今日收盤成交量 (動態時間加權)"""
    now = get_taiwan_time()
    # 換算為當日開盤後的分鐘數
    current_minutes = now.hour * 60 + now.minute
    start_minutes = 9 * 60 # 09:00
    
    passed = current_minutes - start_minutes
    if passed <= 0: return current_vol
    if passed <= 10: return current_vol * 2.5 # 開盤極早期放大
    if passed >= 270: return current_vol     # 已收盤 (13:30)
    
    # 標準比例插值
    est = current_vol * (270 / (passed + 5)) 
    return est

@st.cache_data(ttl=30 if is_market_open() else 3600)
def get_stock_data(sid, token):
    """獲取 FinMind 與 yfinance 混合數據"""
    try:
        # 1. 獲取歷史日 K (FinMind)
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice",
            "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=450)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        
        data = res.get("data", [])
        if not data: return None
        
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        # 2. 獲取即時價格 (yfinance)
        # 僅在開盤時或大盤分析時抓即時
        if is_market_open() or sid == "TAIEX":
            ticker_str = get_yf_ticker(sid)
            yt = yf.download(ticker_str, period="2d", interval="1m", progress=False, timeout=10)
            
            if not yt.empty:
                last_price = float(yt['Close'].iloc[-1])
                # 計算當日 High/Low/Vol
                today_start = get_taiwan_time().replace(hour=9, minute=0, second=0, microsecond=0)
                today_yt = yt[yt.index >= today_start.strftime('%Y-%m-%d %H:%M:%S')]
                
                if not today_yt.empty:
                    day_vol = int(today_yt['Volume'].sum())
                    day_high = float(today_yt['High'].max())
                    day_low = float(today_yt['Low'].min())
                    
                    # 判斷是否需要插入新的一行或是更新最後一行
                    if df.iloc[-1]['date'].date() == get_taiwan_time().date():
                        idx = df.index[-1]
                    else:
                        new_row = df.iloc[-1].copy()
                        new_row['date'] = pd.Timestamp(get_taiwan_time().date())
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        idx = df.index[-1]
                        
                    df.at[idx, 'close'] = last_price
                    df.at[idx, 'high'] = day_high
                    df.at[idx, 'low'] = day_low
                    df.at[idx, 'volume'] = day_vol
                    df.at[idx, 'est_volume'] = calculate_est_volume(day_vol)
                else:
                    df['est_volume'] = df['volume']
            else:
                df['est_volume'] = df['volume']
        else:
            df['est_volume'] = df['volume']
        
        return df
    except Exception as e:
        print(f"數據獲取失敗 {sid}: {e}")
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    """獲取台股基本資訊清單"""
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

# --- 5. 核心策略分析引擎 (旗艦版邏輯) ---
def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 120: return None
    
    # A. 均線系統 (MA5, 10, 20, 55, 60, 200)
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # B. 雙週期與週線趨勢
    df["ma144_60min"] = df["close"].rolling(36).mean() # 類 60 分 K 144MA
    df["week_ma"] = df["close"].rolling(25).mean()     # 類週線 5MA
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # C. MACD 震盪指標
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    df = df.ffill().bfill()
    
    # D. 乖離率與量比判斷
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # E. 轉折關鍵點
    # 死亡交叉與黃金交叉位置紀錄
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()   # 死交關鍵價
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill() # 金交關鍵價
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # F. ATR 與波動風險
    tr = pd.concat([df['high'] - df['low'], (df['high'] - df['close'].shift()).abs(), (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 旗艦形態偵測邏輯 ---
    ma_short = [row["ma5"], row["ma10"], row["ma20"]]
    ma_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max(ma_short) - min(ma_short)) / row["close"]
    diff_long = (max(ma_long) - min(ma_long)) / row["close"]
    
    # 噴發邏輯
    ma5_up = row["ma5"] > prev["ma5"]
    max_ma_prev = max([prev["ma5"], prev["ma10"], prev["ma20"]])
    was_tangling = (max_ma_prev - min([prev["ma5"], prev["ma10"], prev["ma20"]])) / prev["close"] < 0.03

    is_first_breakout = (was_tangling and row["close"] > max_ma_prev and row["vol_ratio"] > 1.2 and ma5_up)
    df.at[last_idx, "is_first_breakout"] = is_first_breakout

    pattern_name = "一般盤整"
    pattern_desc = "目前處於無明顯趨勢的整理區間。建議耐心等待均線糾結後的方向突破。"

    if is_first_breakout:
        pattern_name = "🚀 噴發第一根"
        pattern_desc = "均線糾結後首次帶量突破，慣性徹底改變，極具爆發力的進場點。"
    elif diff_long < 0.02 and row["close"] > row["ma5"] and ma5_up:
        pattern_name = "💎 鑽石眼"
        pattern_desc = "四線合一且 5MA 轉強，是飆股噴發前的典型特徵。"
    elif row["close"] > max(ma_long) and prev["close"] <= max(ma_long):
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "突破所有長期壓力，進入主升段。勇敢加碼。"
    elif diff_short < 0.015 and row["close"] > row["ma5"] and ma5_up:
        pattern_name = "🟡 黃金眼"
        pattern_desc = "短期均線同步發散，底部翻多的強烈訊號。"
    
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc

    # --- 整合需求 3: 買賣點判斷與位階文字修正 ---
    buy_pts, sell_pts = [], []
    
    # 買點判斷
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: 
        buy_pts.append("站上關鍵壓力(轉強)")

    # 賣點判斷
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(減碼)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]:
        sell_pts.append("跌破關鍵支撐(轉弱)")

    # 位階提示邏輯切換
    # 如果整體趨勢是買訊多，顯示底部位階
    # 如果整體趨勢是賣訊多，顯示頭部位階
    if len(buy_pts) > len(sell_pts):
        is_no_new_low = row["low"] >= prev["low"]
        if is_no_new_low:
            buy_pts.insert(0, "底部位階支撐(1日不創新低)")
    elif len(sell_pts) > 0:
        is_no_new_high = row["high"] <= prev["high"]
        if is_no_new_high:
            sell_pts.insert(0, "頭部位階跌破(1日不創新高)")

    # 綜合評分
    score = 50
    if buy_pts: score += 15 * len([p for p in buy_pts if "買點" in p or "支撐" in p])
    if sell_pts: score -= 20 * len([p for p in sell_pts if "賣點" in p or "跌破" in p])
    if row["vol_ratio"] > 1.8: score += 12
    if row["is_weekly_bull"]: score += 8
    
    # 大盤濾網 (非大盤自身時套用)
    if not is_market and st.session_state.market_score < 40:
        score -= 20
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定中"
    
    # 決定最終訊號類型
    sig = "HOLD"
    if len(buy_pts) > len(sell_pts) and score > 55: sig = "BUY"
    elif len(sell_pts) > 0 and score < 45: sig = "SELL"
    
    # 大盤避險邏輯
    if not is_market and st.session_state.market_score < 40 and sig == "BUY":
        sig = "HOLD (避險中)"
        df.at[last_idx, "warning"] = "⚠️ 大盤疲弱暫緩開火 | " + df.at[last_idx, "warning"]

    df.at[last_idx, "sig_type"] = sig
    
    # ATR 倉位配置
    risk_pct = (row["atr"] / row["close"]) * 100
    if risk_pct < 1.5: pos = "配置: 15~20% (穩健)"
    elif risk_pct < 3.0: pos = "配置: 8~12% (標準)"
    else: pos = "配置: 3~5% (高波動)"
    df.at[last_idx, "pos_advice"] = pos
    
    return df

# --- 6. 專業級圖表引擎 ---
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])
    
    # K 線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], 
        name="K線", increasing_line_color='#ef4444', decreasing_line_color='#22c55e',
        increasing_fillcolor='#ef4444', decreasing_fillcolor='#22c55e'
    ), row=1, col=1)
    
    # 均線
    ma_map = {5: '#38bdf8', 10: '#fbbf24', 20: '#f97316', 60: '#a855f7'}
    for ma, color in ma_map.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    # 標記噴發點
    if "is_first_breakout" in df_plot.columns:
        breakouts = df_plot[df_plot["is_first_breakout"] == True]
        if not breakouts.empty:
            fig.add_trace(go.Scatter(
                x=breakouts["date"], y=breakouts["low"] * 0.96,
                mode="markers+text", marker=dict(symbol="triangle-up", size=18, color="#ef4444"),
                text="🚀噴發", textposition="bottom center", name="噴發第一根"
            ), row=1, col=1)

    # MACD 柱狀圖
    colors = ['#ef4444' if v >= 0 else '#22c55e' for v in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    
    fig.update_layout(
        height=650, title=title, template="plotly_dark", xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10), paper_bgcolor="#0f172a", plot_bgcolor="#0f172a",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(showgrid=True, gridcolor="#1e293b")
    
    return fig

# --- 7. 資料同步與解析 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(url)
        def clean(col): return " ".join(df_sheet[col].dropna().astype(str).apply(lambda x: x.split('.')[0].strip()))
        st.session_state.search_codes = clean('snipe_list')
        st.session_state.inventory_codes = clean('inventory_list')
        add_log("SYS", "SYSTEM", "INFO", "Google 表單同步完成")
    except Exception as e:
        st.error(f"同步錯誤: {e}")

# --- 8. 側邊指揮中心 ---
with st.sidebar:
    st.markdown("<h1 style='text-align: center; color: #ef4444;'>🏹 SNIPER COMMAND</h1>", unsafe_allow_html=True)
    st.divider()
    
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    if st.button("🔄 同步雲端清單"):
        sync_sheets()
        st.rerun()
    
    st.session_state.search_codes = st.text_area("🎯 狙擊清單 (代號空格分隔)", value=st.session_state.search_codes, height=120)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes, height=120)
    
    st.divider()
    
    # 整合需求 1: 加入停止按鈕
    st.session_state.mute_notifications = st.toggle("🚫 停止 Discord 訊息傳送", value=st.session_state.mute_notifications, help="開啟後系統仍會掃描並記錄日誌，但不會發送 Discord 通知。")
    
    interval = st.slider("自動監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動化循環監控", value=True)
    analyze_btn = st.button("🚀 執行手動全局掃描", use_container_width=True)
    
    # 狀態面板
    is_open = is_market_open()
    status_color = "#ef4444" if is_open else "#22c55e"
    st.markdown(f"""
    <div style='background:#1e293b; padding:15px; border-radius:10px; border:1px solid #334155;'>
        時間: <b>{get_taiwan_time().strftime('%H:%M:%S')}</b><br>
        狀態: <b style='color:{status_color}'>{'🔴 盤中交易' if is_open else '🟢 市場收盤'}</b>
    </div>
    """, unsafe_allow_html=True)

# --- 9. 全局執行邏輯 ---
def perform_scan():
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    now = get_taiwan_time()
    st.markdown(f"### 📡 指令下達時間：`{now.strftime('%Y-%m-%d %H:%M:%S')}`")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    # A. 大盤加權分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        
        score = m_last["score"]
        if score >= 65: cmd, clz = "🚀 多頭強勁", "buy-signal"
        elif score >= 45: cmd, clz = "🌪 震盪整理", "neutral-signal"
        else: cmd, clz = "📉 空頭警戒", "sell-signal"
        
        c1, c2 = st.columns([1, 2])
        with c1: st.metric("TAIEX 加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with c2: st.markdown(f"<div class='status-card {clz}'>{cmd} (信心分: {score})</div>", unsafe_allow_html=True)
        with st.expander("📊 查看大盤技術圖表"):
            st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 加權指數"), use_container_width=True)

    # B. 多執行緒處理個股
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None: continue
                df = analyze_strategy(df)
                last = df.iloc[-1]
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                
                # 通知邏輯整合
                sig_type = last['sig_type']
                old_sig = st.session_state.notified_status.get(sid)
                old_date = st.session_state.notified_date.get(sid)
                
                # 只有在訊號改變或跨日時才發送
                if (old_date != today_str or old_sig != sig_type) and sig_type != "HOLD":
                    is_inv, is_snipe = sid in inv_list, sid in snipe_list
                    should_notify = (is_inv and sig_type == "SELL") or (is_snipe and sig_type == "BUY")
                    
                    if should_notify:
                        header = "🏹 **狙擊目標點火**" if sig_type == "BUY" else "🩸 **庫存風險處置**"
                        msg = (f"{header}\n代碼: `{sid} {name}`\n價格: `{last['close']}`\n"
                               f"技術: `{last['pattern']}`\n提醒: `{last['warning']}`\n"
                               f"量比: `{last['vol_ratio']:.2f}x` | 分數: `{last['score']}`")
                        send_discord_message(msg)
                        add_log(sid, name, sig_type, last['warning'], last['score'], last['vol_ratio'])
                        st.session_state.notified_status[sid] = sig_type
                        st.session_state.notified_date[sid] = today_str
                
                processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_snipe": sid in snipe_list, "is_inv": sid in inv_list})
            except Exception as e:
                print(f"處理出錯 {sid}: {e}")

    # C. 視覺化面板分區顯示
    col_snipe, col_inv = st.tabs(["🎯 狙擊目標監控", "📦 庫存水位監控"])
    
    with col_snipe:
        snipe_sorted = sorted([s for s in processed_stocks if s["is_snipe"]], key=lambda x: x["last"]["score"], reverse=True)
        for item in snipe_sorted:
            last, sid, name = item["last"], item["sid"], item["name"]
            is_boom = (last["sig_type"] == "BUY" and last["vol_ratio"] > 1.8)
            border = "#ef4444" if last["sig_type"] == "BUY" else "#334155"
            
            st.markdown(f"""
            <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border};">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-size:1.2em;"><b>🎯 {sid} {name}</b> | 現價: <b>{last['close']:.2f}</b></span>
                    <span style="background:{border}; color:white; padding:2px 12px; border-radius:10px;">評分: {last['score']}</span>
                </div>
                <div style="margin-top:10px; color:#94a3b8; font-size:0.9em;">
                    提醒: <span style="color:#f1f5f9"><b>{last['warning']}</b></span> | 型態: {last['pattern']}<br>
                    {last['pos_advice']} | 預估量比: {last['vol_ratio']:.2f}x
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 詳細分析圖表"):
                st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name} 技術分析"), use_container_width=True)

    with col_inv:
        inv_sorted = sorted([s for s in processed_stocks if s["is_inv"]], key=lambda x: x["last"]["score"], reverse=True)
        for item in inv_sorted:
            last, sid, name = item["last"], item["sid"], item["name"]
            border = "#22c55e" if last["sig_type"] == "SELL" else "#334155"
            st.markdown(f"""
            <div class="dashboard-box" style="border-left: 10px solid {border};">
                <div style="display:flex; justify-content:space-between;">
                    <span style="font-size:1.2em;"><b>📦 {sid} {name}</b> | 現價: <b>{last['close']:.2f}</b></span>
                    <span style="background:#334155; color:white; padding:2px 12px; border-radius:10px;">健康度: {last['score']}</span>
                </div>
                <div style="margin-top:10px; color:#94a3b8; font-size:0.9em;">
                    風險提示: <span style="color:#f1f5f9"><b>{last['warning']}</b></span> | 5MA乖離: {last['bias_5']:.2f}%<br>
                    {item['last']['pattern_desc']}
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 持股圖表"):
                st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name} 持股監控"), use_container_width=True)

    # D. 即時日誌
    st.divider()
    st.markdown("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 10. 主循環與自動化控制 (整合需求 2) ---
placeholder = st.empty()

# 判斷執行的路徑
if analyze_btn:
    # 手動按鈕優先執行
    with placeholder.container(): perform_scan()
elif auto_monitor:
    # 自動監控邏輯
    if is_market_open():
        with placeholder.container(): perform_scan()
        st.caption(f"🔄 自動監控中... 下次更新時間預計: {(get_taiwan_time() + timedelta(minutes=interval)).strftime('%H:%M:%S')}")
        time.sleep(interval * 60)
        st.rerun()
    else:
        # 非開盤時間：自動顯示最後掃描結果，但不發送新通知
        with placeholder.container():
            st.warning(f"🌙 目前非台股交易時段 (09:00~13:35)。系統已自動進入休眠模式。")
            # 為了保持網頁有內容，顯示最後一次掃描結果
            if st.session_state.search_codes:
                perform_scan()
        # 非開盤期間，降低檢查頻率（如每 5 分鐘重整一次網頁看有沒有到開盤時間）
        time.sleep(300) 
        st.rerun()
else:
    # 沒開啟自動也沒按按鈕，僅靜態顯示
    with placeholder.container():
        if st.session_state.search_codes:
            perform_scan()

