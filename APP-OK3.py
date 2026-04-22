import streamlit as st
import twstock
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

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
if 'enable_discord' not in st.session_state: st.session_state.enable_discord = True

# --- 3. 核心工具模組 ---
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

def get_yf_ticker(sid):
    if sid == "TAIEX": return "^TWII"
    if sid in st.session_state.sid_map: return st.session_state.sid_map[sid]
    
    sid_str = str(sid)
    if len(sid_str) == 4 and sid_str[0] in ['3', '5', '6', '8']:
        ticker = f"{sid_str}.TWO"
    else:
        ticker = f"{sid_str}.TW"
    
    st.session_state.sid_map[sid] = ticker
    return ticker

def send_discord_message(msg):
    if not st.session_state.get("enable_discord", True):
        return
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    try:
        requests.post(webhook_url, json={"content": msg}, headers=headers, timeout=10)
    except Exception as e: 
        print(f"Discord 連線異常: {e}")

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-info"
    if tag_type == "BUY": tag_class = "tag-buy"
    elif tag_type == "SELL": tag_class = "tag-sell"
    
    score_html = f" | 評分: <b>{score}</b>" if score is not None else ""
    vol_html = f" | 量比: <b>{vol_ratio:.2f}x</b>" if vol_ratio is not None else ""
    
    log_html = (f"<div class='log-entry'>"
                f"<span class='log-time'>[{ts}]</span> "
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

@st.cache_data(ttl=60)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=10).json()
        
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        
        try:
            realtime_data = twstock.realtime.get(sid)
            if realtime_data and realtime_data['success']:
                real = realtime_data['realtime']
                def safe_float(val, default):
                    return float(val) if val != '-' else default

                last_price = safe_float(real['latest_trade_price'], safe_float(real['open'], 0))
                if last_price == 0 and not df.empty: last_price = df['close'].iloc[-1]
                
                day_high = safe_float(real['high'], last_price)
                day_low = safe_float(real['low'], last_price)
                day_vol = int(real['accumulate_trade_volume']) * 1000 

                today_dt = pd.Timestamp(get_taiwan_time().date())
                
                if df['date'].iloc[-1].date() < today_dt.date():
                    new_row = pd.DataFrame([{
                        'date': today_dt, 'open': safe_float(real['open'], last_price),
                        'high': day_high, 'low': day_low, 'close': last_price, 'volume': day_vol
                    }])
                    df = pd.concat([df, new_row], ignore_index=True)
                else:
                    idx = df.index[-1]
                    df.at[idx, 'close'] = last_price
                    df.at[idx, 'high'] = max(df.at[idx, 'high'], day_high)
                    df.at[idx, 'low'] = min(df.at[idx, 'low'], day_low)
                    df.at[idx, 'volume'] = day_vol
        except Exception as e:
            print(f"即時數據合併跳過 ({sid}): {e}")

        df['est_volume'] = df['volume'].apply(calculate_est_volume) if is_market_open() else df['volume']
        df = df.sort_values("date").drop_duplicates(subset=['date'], keep='last')
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].ffill()
        df['date'] = df['date'].dt.tz_localize(None)
        return df
    except Exception as e:
        st.error(f"獲取股票 {sid} 失敗: {e}")
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15).json()
        if "data" in res:
            df = pd.DataFrame(res["data"])
            df.columns = [c.lower() for c in df.columns]
            return df
        return pd.DataFrame()
    except: return pd.DataFrame()

@st.cache_data(ttl=43200)
def get_chip_details(sid, token):
    try:
        res_inst = requests.get(BASE_URL, params={"dataset": "InstitutionalInvestorsBuySell", "data_id": sid, "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"), "token": token}, timeout=15).json()
        res_margin = requests.get(BASE_URL, params={"dataset": "TaiwanStockMarginPurchaseSell", "data_id": sid, "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"), "token": token}, timeout=15).json()
        df_inst = pd.DataFrame(res_inst.get("data", []))
        df_margin = pd.DataFrame(res_margin.get("data", []))
        if not df_inst.empty: df_inst.columns = [c.lower() for c in df_inst.columns]
        if not df_margin.empty: df_margin.columns = [c.lower() for c in df_margin.columns]
        return df_inst, df_margin
    except: return pd.DataFrame(), pd.DataFrame()

# --- 5. 核心策略分析 ---
def analyze_strategy(df, sid=None, token=None, is_market=False):
    if df is None or len(df) < 180: return None
    
    # 均線指標
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["ma55_60min"] = df["close"].rolling(14).mean()
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD 計算
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵轉折
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR & VCP
    high_low = df['high'] - df['low']
    tr = pd.concat([high_low, (df['high'] - df['close'].shift()).abs(), (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    df['hl_range'] = (df['high'] - df['low']) / df['close']
    df['vcp_check'] = df['hl_range'].rolling(5).mean() < df['hl_range'].rolling(20).mean() * 0.7

    # 噴發點判定
    max_ma_3_prev = df[["ma5", "ma10", "ma20"]].max(axis=1).shift(1)
    min_ma_3_prev = df[["ma5", "ma10", "ma20"]].min(axis=1).shift(1)
    df["was_tangling"] = (max_ma_3_prev - min_ma_3_prev) / df["close"].shift(1) < 0.035
    raw_signals = (df["was_tangling"]) & (df["close"] > max_ma_3_prev) & (df["vol_ratio"] > 1.2) & (df["ma5"] > df["ma5"].shift(1))
    filtered_signals = raw_signals.copy()
    for i in range(1, len(df)):
        if filtered_signals.iloc[i] and filtered_signals.iloc[max(0, i-5):i].any():
            filtered_signals.iloc[i] = False
    df["is_first_breakout"] = filtered_signals

    # --- 重要：先定義資料行 ---
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    score = 50
    buy_pts, sell_pts = [], []
    
    # 盤勢基礎判定
    market_phase = "📈上漲盤 (多頭)" if row["ma5"] > row["ma10"] > row["ma20"] else ("📉下跌盤 (空頭)" if row["ma5"] < row["ma10"] < row["ma20"] else "🍽️盤整盤 (橫盤)")
    df.at[last_idx, "market_phase"] = market_phase

    # --- 形態強度判定 ---
    pattern_name = market_phase
    pattern_desc = f"目前處於{market_phase}階段。"
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max([row["ma5"], row["ma10"], row["ma20"]]) - min([row["ma5"], row["ma10"], row["ma20"]])) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    is_long_red = (row["close"] > row["open"]) and ((row["close"] - row["open"]) / row["open"] > 0.03)

    if row["is_first_breakout"]:
        score += 35
        pattern_name, pattern_desc = "🚀 噴發第一根", "SSS 級判定！均線糾結後首次帶量突破。"
        buy_pts.append("噴發訊號")
    elif diff_long < 0.02 and row["close"] > row["ma5"] and row["ma5"] > prev["ma5"]:
        score += 30
        pattern_name, pattern_desc = "💎 鑽石眼", "SS 級判定！五線合一超級共振。"
        buy_pts.append("鑽石眼強勢點")
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        score += 25
        pattern_name, pattern_desc = "🕳️ 鑽石坑", "S 級判定！克服長期壓力。"
        buy_pts.append("主升段啟動")
    elif diff_short < 0.015 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        score += 20
        pattern_name, pattern_desc = "🟡 黃金眼", "A 級判定！均線排列，底部反轉。"
        buy_pts.append("黃金眼排列")
    elif row["ma5"] > row["ma10"] and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        score += 15
        pattern_name, pattern_desc = "📐 黃金三角眼", "B 級判定！多頭雛形醞釀。"
        buy_pts.append("多頭一浪啟動")
    elif is_long_red and row["vol_ratio"] > 1.8:
        score += 15
        pattern_name, pattern_desc = "🧱 實體長紅突破", "強力買盤介入。"
        buy_pts.append("實體長紅")

    # --- 輔助判斷 ---
    recent_low = df["low"].tail(3).min()
    is_gap_up = row["open"] > prev["high"] * 1.005
    is_retrace = (row["low"] <= row["ma5"] * 1.005) and (row["close"] > row["ma5"]) and (row["volume"] < prev["volume"])

    # 買點彙整
    if is_gap_up: buy_pts.append("🚀多方跳空缺口")
    if row["vcp_check"]: buy_pts.append("🔋籌碼壓縮(VCP)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死交關鍵位")
    if row["star_signal"]: buy_pts.append("站上發動點")
    if is_retrace: buy_pts.append("量縮回踩5MA(買點)")
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA")
    if row["close"] > prev["close"] and row["low"] >= recent_low: buy_pts.append("底部位階支撐")

    # 賣點彙整 (完整補回)
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破金交關鍵位(下跌賣出)") 
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if row["close"] < prev["close"] and row["high"] <= prev["high"]: sell_pts.append("頭部位階跌破(不創新高)")

    # 最終評分
    if buy_pts: score += 12 * len(set(buy_pts))
    if sell_pts: score -= 20 * len(set(sell_pts))
    if row["vol_ratio"] > 1.8: score += 10
    if is_gap_up: score += 10
    if row["vcp_check"]: score += 5
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    if not is_market and hasattr(st.session_state, 'market_score') and st.session_state.market_score < 40: score -= 20

    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "pattern"], df.at[last_idx, "pattern_desc"] = pattern_name, pattern_desc
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定"
    df.at[last_idx, "sig_type"] = "BUY" if buy_pts else ("SELL" if sell_pts else "HOLD")
    
    risk_vol = (row["atr"] / row["close"]) * 100
    df.at[last_idx, "pos_advice"] = "建議配置: 15~20% (穩健)" if risk_vol < 1.5 else "建議配置: 8~12% (標準)"
    return df

def plot_advanced_chart(df, title=""):
    if df is None or df.empty: return go.Figure()
    
    # 確保資料量足夠且補齊缺失欄位避免報錯
    df_plot = df.tail(100).copy()
    if "is_first_breakout" not in df_plot.columns: df_plot["is_first_breakout"] = False
    df_plot["is_first_breakout"] = df_plot["is_first_breakout"].fillna(False).astype(bool)
    if "star_signal" not in df_plot.columns: df_plot["star_signal"] = False
    
    # 建立子圖：K線主圖 + MACD/成交量副圖
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.05, 
        row_heights=[0.7, 0.3]
    )

    # 1. 主圖：K線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], 
        open=df_plot["open"], 
        high=df_plot["high"], 
        low=df_plot["low"], 
        close=df_plot["close"], 
        name="K線", 
        increasing_line_color='#ff4b4b', 
        decreasing_line_color='#28a745'
    ), row=1, col=1)

    # 2. 均線系統
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=df_plot["date"], 
                y=df_plot[f"ma{ma}"], 
                name=f"{ma}MA", 
                line=dict(color=color, width=1.5)
            ), row=1, col=1)

    # 3. 關鍵位（虛線表示）
    if "upward_key" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot["date"], y=df_plot["upward_key"], 
            name="上漲關鍵位", 
            line=dict(color='rgba(235,77,75,0.4)', dash='dash')
        ), row=1, col=1)
    
    if "downward_key" in df_plot.columns:
        fig.add_trace(go.Scatter(
            x=df_plot["date"], y=df_plot["downward_key"], 
            name="下跌關鍵位", 
            line=dict(color='rgba(46,204,113,0.4)', dash='dash')
        ), row=1, col=1)

    # 4. 特殊訊號標記 (噴發第一根 🚀)
    breakouts = df_plot[df_plot["is_first_breakout"] == True]
    if not breakouts.empty:
        fig.add_trace(go.Scatter(
            x=breakouts["date"], 
            y=breakouts["low"] * 0.96, 
            mode="markers+text", 
            marker=dict(symbol="triangle-up", size=15, color="#ff4b4b"), 
            text="🚀", 
            textposition="bottom center", 
            name="噴發第一根"
        ), row=1, col=1)

    # 5. 特殊訊號標記 (發動點 ⭐)
    stars = df_plot[df_plot["star_signal"].fillna(False).astype(bool)]
    if not stars.empty:
        fig.add_trace(go.Scatter(
            x=stars["date"], 
            y=stars["low"] * 0.98, 
            mode="markers", 
            marker=dict(symbol="star", size=12, color="#FFD700"), 
            name="發動點"
        ), row=1, col=1)

    # 6. 副圖：MACD 柱狀圖
    if "hist" in df_plot.columns:
        colors = ['#ff4b4b' if v >= 0 else '#28a745' for v in df_plot["hist"]]
        fig.add_trace(go.Bar(
            x=df_plot["date"], 
            y=df_plot["hist"], 
            name="MACD柱狀", 
            marker_color=colors
        ), row=2, col=1)

    # 7. 圖表佈局優化
    fig.update_layout(
        height=650, 
        title=dict(text=title, font=dict(size=20)),
        template="plotly_white", 
        xaxis_rangeslider_visible=False, 
        margin=dict(l=10, r=10, t=50, b=10),
        legend=dict(
            orientation="h", 
            yanchor="bottom", 
            y=1.02, 
            xanchor="right", 
            x=1
        ),
        hovermode="x unified"
    )
    
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
                # 這裡保留您最嚴格的清洗邏輯：排除 nan、空值，並確保代碼格式正確
                valid_series = df_sheet[name].astype(str).replace(['nan', 'None', 'NAT', 'nan.0'], np.nan).dropna()
                valid_series = valid_series[valid_series.str.strip() != ""]
                return ",".join(valid_series.apply(lambda x: x.split('.')[0].strip()))
            return None

        new_search = clean_col('snipe_list')
        new_inv = clean_col('inventory_list')
        
        # 只有在真的有抓到資料時才更新，防止雲端斷線時把本地清單洗掉
        if new_search is not None:
            st.session_state.search_codes = new_search
        if new_inv is not None:
            st.session_state.inventory_codes = new_inv
            
        add_log("SYS", "SYSTEM", "INFO", "成功從 Google 表單同步數據")
    except Exception as e:
        add_log("SYS", "SYSTEM", "ERROR", f"雲端同步失敗: {str(e)}")

if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# --- 7.5 全市場選股工具函式 ---
def get_yf_ticker(sid):
    """將台股代碼轉換為 yfinance 格式"""
    if sid == "TAIEX": return "^TWII"
    sid_str = str(sid)
    if len(sid_str) == 4 and sid_str[0] in ['3', '5', '6', '8']:
        return f"{sid_str}.TWO"
    else:
        return f"{sid_str}.TW"

@st.cache_data(ttl=60)
def run_stock_screener(enable_kd_filter=True, min_volume_limit=500, max_growth_limit=5.0):
    all_codes = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == '股票':
            all_codes.append(get_yf_ticker(code))
    
    found_targets = []
    batch_size = 50 
    progress_bar = st.progress(0)
    status_text = st.empty()
    total_count = len(all_codes)
    
    for i in range(0, total_count, batch_size):
        batch = all_codes[i:i+batch_size]
        progress_bar.progress(min(i / total_count, 1.0))
        status_text.markdown(f"🔍 **進度:** `{i}/{total_count}` | 🔥 **符合標的:** `{len(found_targets)}` 檔")
        
        try:
            data = yf.download(batch, period="1y", interval="1d", group_by='ticker', progress=False, threads=False)
            for ticker in batch:
                try:
                    df = data[ticker].copy() if len(batch) > 1 else data.copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) < 60: continue
                    
                    df.columns = [str(c).lower().strip() for c in df.columns]
                    if 'adj close' in df.columns: df = df.rename(columns={"adj close": "close"})

                    curr_price = df['close'].iloc[-1]
                    prev_close = df['close'].iloc[-2]
                    curr_vol = df['volume'].iloc[-1]

                    if curr_vol < (min_volume_limit * 1000): continue
                    change_pct = ((curr_price - prev_close) / prev_close) * 100
                    if not (0 <= change_pct <= max_growth_limit): continue

                    # 出量偵測
                    def check_volume_burst(idx):
                        if abs(idx) + 4 > len(df): return False
                        v = df['volume'].iloc[idx]
                        avg_v = df['volume'].iloc[idx-4 : idx-1].mean()
                        return v > (avg_v * 2.0)
                    
                    is_volume_burst = check_volume_burst(-1) or check_volume_burst(-2) or check_volume_burst(-3)

                    # 均線與 KD 篩選
                    ma20 = df['close'].rolling(20).mean().iloc[-1]
                    ma200 = df['close'].rolling(200).mean().iloc[-1]
                    ma5 = df['close'].rolling(5).mean().iloc[-1]
                    ma10 = df['close'].rolling(10).mean().iloc[-1]
                    
                    cond_trend = curr_price > ma20 and curr_price > ma200
                    cond_retrace = ma5 < ma10 

                    low_9 = df['low'].rolling(9).min()
                    high_9 = df['high'].rolling(9).max()
                    rsv = (df['close'] - low_9) / (high_9 - low_9 + 0.0001) * 100
                    df['k'] = rsv.ewm(com=2).mean()
                    df['d'] = df['k'].ewm(com=2).mean()
                    kd_cross = df['k'].iloc[-2] <= df['d'].iloc[-2] and df['k'].iloc[-1] > df['d'].iloc[-1]

                    if cond_trend and cond_retrace:
                        if enable_kd_filter and not kd_cross: continue
                        sid = ticker.split('.')[0]
                        stock_info = get_stock_info()
                        name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                        
                        found_targets.append({
                            "追蹤": False, "股價代號": sid, "股價名稱": name, "評分": 0,
                            "股價": round(curr_price, 2), "漲幅%": round(change_pct, 2), "出量": "✅ 是" if is_volume_burst else "—"
                        })
                except: continue
        except: continue
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(found_targets)

# --- 8. 指揮中心 UI ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    st.session_state.enable_discord = st.toggle("📢 開啟 Discord 推送", value=st.session_state.enable_discord)
    
    if st.button("🔄 同步雲端清單"):
        sync_sheets()
        st.rerun()
        
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes, height=100)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes, height=100)
    
    auto_monitor = st.checkbox("🔄 開啟盤中自動監控", value=True)
    interval = st.slider("監控頻率 (分鐘)", 1, 30, 5) # 補回 interval 變數
    analyze_btn = st.button("🚀 執行即時掃描", use_container_width=True)

    st.divider()
    st.subheader("🔍 個股即時診斷")
    query_sid = st.text_input("輸入代碼 (例如: 2330)", key="diag_input")
    if (st.button("🔎 開始診斷報告") or (query_sid and len(query_sid)==4)) and query_sid:
        with st.spinner(f"正在分析 {query_sid}..."):
            df_q = get_stock_data(query_sid, fm_token)
            if df_q is not None:
                df_q = analyze_strategy(df_q)
                q_last = df_q.iloc[-1]
                st.info(f"### 📊 {query_sid} 診斷報告")
                col_a, col_b = st.columns(2)
                col_a.metric("當前股價", f"{q_last['close']:.2f}")
                col_b.metric("戰鬥評分", f"{int(q_last['score'])}")
                st.markdown(f"**形態：** `{q_last['pattern']}`\n**建議：** **{q_last['pos_advice']}**")
                with st.expander("📈 查看技術圖表"):
                    st.plotly_chart(plot_advanced_chart(df_q, f"診斷: {query_sid}"), use_container_width=True)
    
    st.divider()
    st.subheader("🔭 全市場潛力股挖掘")
    use_kd_strict = st.checkbox("🎯 僅顯示 KD 金叉", value=True, key="screen_kd")
    vol_limit = st.number_input("成交量 > (張)", value=500, key="screen_vol")
    growth_limit = st.number_input("漲幅 < (%)", value=5.0, key="screen_growth")

    if st.button("🔎 執行全台股掃描"):
        screen_results = run_stock_screener(use_kd_strict, vol_limit, growth_limit)
        st.session_state.screen_results = screen_results
        if not screen_results.empty: st.balloons()

    if 'screen_results' in st.session_state and not st.session_state.screen_results.empty:
        with st.expander("📊 掃描結果", expanded=True):
            edited_df = st.data_editor(st.session_state.screen_results, hide_index=True, key="editor_v2")
            if st.button("📥 加入勾選股票"):
                selected = edited_df[edited_df["追蹤"] == True]["股價代號"].tolist()
                new_list = ",".join(list(set([c.strip() for c in (st.session_state.search_codes + "," + ",".join(selected)).split(",") if c.strip()])))
                st.session_state.search_codes = new_list
                st.rerun()

# --- 9. 執行掃描邏輯 (完整補回 Discord 格式與 UI 分級) ---
def perform_scan(manual_trigger=False):  
    if not manual_trigger: sync_sheets() 
    
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    st.markdown(f"### 📡 掃描時間：{get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')}")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    # 1. 大盤分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        score = int(m_last["score"])
        cmd, clz, tip = ("🚀 強力買進", "buy-signal", "🔥 市場動能極強") if score >= 80 else ("📈 分批買進", "buy-signal", "⚖️ 穩定上漲中") if score >= 60 else ("Neutral 觀望", "neutral-signal", "🌪 盤勢震盪")
        c1, c2 = st.columns([1, 2])
        c1.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        c2.markdown(f"<div class='status-card {clz}'>{cmd} | {tip} (評分: {score})</div>", unsafe_allow_html=True)

    # 2. 個股處理
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None: continue
                df = analyze_strategy(df)
                last = df.iloc[-1]
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                is_inv, is_snipe = sid in inv_list, sid in snipe_list
                
                # 通知判定邏輯
                sig_type = last['sig_type']
                sig_lvl = f"{sig_type}_{'BOOM' if (sig_type=='BUY' and last['vol_ratio']>1.8) else 'NOR'}"
                
                # 只有信號改變或是強制掃描才發送 Discord
                if manual_trigger or st.session_state.notified_status.get(sid) != sig_lvl:
                    should_send = False
                    msg_header = ""
                    if is_inv and sig_type == "SELL":
                        should_send, msg_header = True, "🚨🚨🚨 【 庫存風險警示：立即減碼 】 "
                    elif is_snipe and ("BUY" in sig_type or last.get("is_first_breakout", False)):
                        should_send = True
                        if last.get("is_first_breakout"): msg_header = "🚀🚀🚀 【 噴發第一根：強勢確認 】 "
                        elif last["vol_ratio"] > 1.8: msg_header = "🔥🔥🔥 【 狙擊標的：爆量點火 】 "
                        else: msg_header = "🎯🎯🎯 【 買點觸發：執行計畫 】 "

                    if should_send:
                        # 補回特殊的 VCP / 跳空 標籤
                        special_alerts = []
                        if last['close'] > df.iloc[-2]['high']: special_alerts.append("🚀 多方跳空缺口")
                        if "VCP" in last['pattern'] or "壓縮" in last['pattern_desc']: special_alerts.append("💎 籌碼壓縮 VCP")
                        special_note = f"💡 **核心關鍵：** `{' | '.join(special_alerts)}`" if special_alerts else ""

                        # 完整的 Discord 專業排版
                        if st.session_state.get("enable_discord", False):
                            msg = f"## {msg_header}\n{special_note}\n### 📈 **標的：** `{sid} {name} {last['close']:.2f}`\n" \
                                  f"📊 **預估量比：** `{last['vol_ratio']:.2f}x` | **評分：** `{int(last['score'])}` \n" \
                                  f"━━━━━━━━━━━━━━━━━━━━\n" \
                                  f"✅ **建議買點：** `{last['close']*0.995:.2f} ~ {last['close']*1.01:.2f}`\n" \
                                  f"❌ **硬性停損：** `{last['close']*0.94:.2f}`\n" \
                                  f"📍 **策略：** {last['pos_advice']}\n" \
                                  f"🔗 [技術圖表](https://www.wantgoo.com/stock/{sid}/technical-chart)"
                            send_discord_message(msg)
                        
                        st.session_state.notified_status[sid] = sig_lvl
                        add_log(sid, name, "BUY" if "BUY" in sig_type else "SELL", last['pattern'], int(last['score']), last['vol_ratio'])

                processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_inv": is_inv, "is_snipe": is_snipe, "score": int(last["score"])})
            except: continue

    # 3. 渲染 UI (補回 SSS/SS 級分級與高亮樣式)
    for category, title in [("is_snipe", "🔥 狙擊目標監控"), ("is_inv", "📦 庫存持股監控")]:
        st.subheader(title)
        targets = sorted([s for s in processed_stocks if s[category]], key=lambda x: x["score"], reverse=True)
        for item in targets:
            last, sid, name, pattern = item["last"], item["sid"], item["name"], item["last"]["pattern"]
            
            # 分級邏輯
            if "🚀" in pattern: rank, clr = "SSS 級", "#ff4b4b"
            elif "💎" in pattern: rank, clr = "SS 級", "#ffa500"
            elif "🕳️" in pattern: rank, clr = "S 級", "#f1c40f"
            else: rank, clr = "A 級", "#3498db"
            
            is_boom = ("BUY" in last["sig_type"] and last["vol_ratio"] > 1.8)
            border_clr = "#ff4b4b" if "BUY" in last["sig_type"] else ("#28a745" if "SELL" in last["sig_type"] else "#ccc")
            
            st.markdown(f"""
            <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border_clr}; padding: 15px; background: #f8f9fa; border-radius: 5px; margin-bottom: 10px; color: black;">
                <div style="display:flex; justify-content:space-between;">
                    <b>🎯 {sid} {name}</b>
                    <span style="background:{clr}; color:white; padding:2px 8px; border-radius:4px; font-size:0.8em;">{rank}</span>
                </div>
                <div style="margin-top:5px;">評分: {int(last['score'])} | 現價: {last['close']} | 量比: {last['vol_ratio']:.2f}x</div>
                <div style="font-size:0.9em; color:#555; margin-top:5px;">💡 {item['last']['pattern_desc']}</div>
                <div style="font-weight:bold; color:#d35400; margin-top:5px;">💰 {last['pos_advice']}</div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} {name} 分析圖表", expanded=("🚀" in pattern)):
                st.plotly_chart(plot_advanced_chart(item["df"], f"{sid} {name}"), use_container_width=True)

    st.write("### 📜 戰情即時日誌")
    log_content = "".join(st.session_state.event_log)
    st.markdown(f"<div class='log-container'>{log_content}</div>", unsafe_allow_html=True)

# --- 10. 主循環邏輯 ---
placeholder = st.empty()
if analyze_btn:
    with placeholder.container(): perform_scan(manual_trigger=True)
elif auto_monitor:
    if is_market_open():
        with placeholder.container(): perform_scan()
        st.info(f"🔄 自動監控中... 下次掃描預計於 {interval} 分鐘後。")
        time.sleep(interval * 60)
        st.rerun()
    else:
        with placeholder.container(): perform_scan()
        st.warning("🌙 目前非開盤時間，自動監控已進入休眠。")
else:
    with placeholder.container(): perform_scan()
