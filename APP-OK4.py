import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time
import twstock  # <-- 已取代 yfinance
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
if 'enable_discord' not in st.session_state: st.session_state.enable_discord = True
if 'last_twstock_call' not in st.session_state: st.session_state.last_twstock_call = 0

# --- 3. 核心工具模組 ---
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

def send_discord_message(msg):
    if not st.session_state.get("enable_discord", True):
        return
    
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url: return
    
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        res = requests.post(webhook_url, json={"content": msg}, headers=headers, timeout=10)
        if res.status_code != 204:
            print(f"Discord 傳送失敗: {res.status_code}")
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
    
    est = current_vol * (270 / (passed + 10)) 
    return est

@st.cache_data(ttl=30 if is_market_open() else 3600)
def get_stock_data(sid, token):
    try:
        # FinMind 歷史數據
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

        # twstock 即時數據獲取 (取代 yfinance)
        if is_market_open() or sid == "TAIEX":
            # 頻率控制：每 5 秒不超過 3 個 request
            time.sleep(1.7) 
            
            try:
                # 處理大盤特殊 ID
                target_id = "tse_t00.tw" if sid == "TAIEX" else sid
                rt_data = twstock.realtime.get(target_id)
                
                if rt_data and rt_data.get('success'):
                    rt = rt_data['realtime']
                    info = rt_data['info']
                    
                    # 更新名稱對照
                    st.session_state.sid_map[sid] = info.get('name', sid)
                    
                    # 抓取數值 (考慮開盤未成交情況)
                    try:
                        latest_p = float(rt['latest_trade_price']) if rt['latest_trade_price'] != '-' else float(rt['get'].get('open', 0))
                        day_high = float(rt['high']) if rt['high'] != '-' else latest_p
                        day_low = float(rt['low']) if rt['low'] != '-' else latest_p
                        day_vol = int(rt['accumulated_trade_volume']) if rt['accumulated_trade_volume'] != '-' else 0
                    except:
                        latest_p = df.iloc[-1]['close']
                        day_high, day_low, day_vol = latest_p, latest_p, 0

                    # 更新或新增今日 Row
                    today_date = get_taiwan_time().date()
                    if df.iloc[-1]['date'].date() == today_date:
                        idx = df.index[-1]
                    else:
                        new_row = df.iloc[-1].copy()
                        new_row['date'] = pd.Timestamp(today_date)
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        idx = df.index[-1]
                    
                    df.at[idx, 'close'] = latest_p
                    df.at[idx, 'high'] = day_high
                    df.at[idx, 'low'] = day_low
                    df.at[idx, 'volume'] = day_vol * 1000 # twstock 張轉股
                    df.at[idx, 'est_volume'] = calculate_est_volume(day_vol * 1000)
                else:
                    df['est_volume'] = df['volume']
            except Exception as e:
                print(f"twstock Error for {sid}: {e}")
                df['est_volume'] = df['volume']
        else:
            df['est_volume'] = df['volume']
            
        if df is not None and not df.empty:
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['volume'] = df['volume'].fillna(0)
            if 'est_volume' in df.columns:
                df['est_volume'] = df['est_volume'].fillna(df['volume'])
            for col in ['open', 'high', 'low', 'close']:
                df[col] = df[col].ffill()
        
        return df
    except Exception as e:
        print(f"Error fetching {sid}: {e}")
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        res_json = res.json()
        if "data" in res_json:
            df = pd.DataFrame(res_json["data"])
            df.columns = [c.lower() for c in df.columns]
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Error fetching stock info: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=43200)
def get_chip_details(sid, token):
    try:
        res_inst = requests.get(BASE_URL, params={
            "dataset": "InstitutionalInvestorsBuySell", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        
        res_margin = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockMarginPurchaseSell", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()

        df_inst = pd.DataFrame(res_inst.get("data", []))
        df_margin = pd.DataFrame(res_margin.get("data", []))

        if not df_inst.empty: df_inst.columns = [c.lower() for c in df_inst.columns]
        if not df_margin.empty: df_margin.columns = [c.lower() for c in df_margin.columns]
        
        return df_inst, df_margin
    except Exception as e:
        print(f"籌碼數據獲取失敗 {sid}: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- 5. 核心策略分析 ---
def analyze_strategy(df, sid=None, token=None, is_market=False):
    if df is None or len(df) < 180: return None
    
    # --- 1. 基礎指標與均線計算 ---
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
    
    # 乖離與量比 (使用預估成交量)
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

    # VCP 特徵計算
    df['hl_range'] = (df['high'] - df['low']) / df['close']
    df['vcp_check'] = df['hl_range'].rolling(5).mean() < df['hl_range'].rolling(20).mean() * 0.7

# --- 全表噴發點過濾判定 (確保 5 天內不重複出現 🚀) ---
    max_ma_3_prev = df[["ma5", "ma10", "ma20"]].max(axis=1).shift(1)
    min_ma_3_prev = df[["ma5", "ma10", "ma20"]].min(axis=1).shift(1)
    df["was_tangling"] = (max_ma_3_prev - min_ma_3_prev) / df["close"].shift(1) < 0.035
    
    # 1. 先計算原始的訊號 (raw_signals)
    raw_signals = (df["was_tangling"]) & (df["close"] > max_ma_3_prev) & (df["vol_ratio"] > 1.2) & (df["ma5"] > df["ma5"].shift(1))
    
    # 2. 建立一個乾淨的欄位來存過濾後的結果
    filtered_signals = raw_signals.copy()
    
    # 3. 執行冷卻時間過濾 (Cool-down logic)
    for i in range(1, len(df)):
        if filtered_signals.iloc[i]:
            if filtered_signals.iloc[max(0, i-5):i].any():
                filtered_signals.iloc[i] = False
    
    # 4. 將過濾後的結果存回 DataFrame
    df["is_first_breakout"] = filtered_signals

    # --- 取得最新資料行 ---
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    score = 50
    buy_pts, sell_pts = [], []
    
    # 盤勢基礎判定
    if row["ma5"] > row["ma10"] > row["ma20"] and row["close"] > row["ma5"]:
        market_phase = "📈上漲盤 (多頭)"
    elif row["ma5"] < row["ma10"] < row["ma20"] and row["close"] < row["ma5"]:
        market_phase = "📉下跌盤 (空頭)"
    else:
        market_phase = "🍽️盤整盤 (橫盤)"
    df.at[last_idx, "market_phase"] = market_phase

    # --- 形態強度層級判定 ---
    pattern_name = market_phase
    pattern_desc = f"目前處於{market_phase}階段。"
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max([row["ma5"], row["ma10"], row["ma20"]]) - min([row["ma5"], row["ma10"], row["ma20"]])) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    
    is_long_red = (row["close"] > row["open"]) and ((row["close"] - row["open"]) / row["open"] > 0.03)
    is_gap_up = row["open"] > prev["high"] * 1.005

    if row["is_first_breakout"]:
        score += 35
        pattern_name = "🚀 噴發第一根"
        pattern_desc = "SSS 級判定！均線糾結後首次帶量突破，能量完全釋放，行情起點。"
        buy_pts.append("噴發訊號")
    elif diff_long < 0.02 and row["close"] > row["ma5"] and row["ma5"] > prev["ma5"]:
        score += 30
        pattern_name = "💎 鑽石眼"
        pattern_desc = "SS 級判定！五線合一超級共振，週期成本達成一致，發動令已下。"
        buy_pts.append("鑽石眼強勢點")
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        score += 25
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "S 級判定！克服所有長期壓力，進入主升段無壓力區。"
        buy_pts.append("主升段啟動")
    elif diff_short < 0.015 and row["close"] > row["ma5"] and row["ma5"] > prev["ma5"] and row["close"] > row["open"]:
        score += 20
        pattern_name = "🟡 黃金眼"
        pattern_desc = "A 級判定！均線整齊排列，底部反轉確認。"
        buy_pts.append("黃金眼排列")
    elif row["ma5"] > row["ma10"] and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        score += 15
        pattern_name = "📐 黃金三角眼"
        pattern_desc = "B 級判定！多頭雛形醞釀，適合分批試單。"
        buy_pts.append("多頭一浪啟動")
    elif is_long_red and row["vol_ratio"] > 1.8:
        score += 15
        pattern_name = "🧱 實體長紅突破"
        pattern_desc = "強力買盤介入，實體紅棒穿透壓力區，配合量能噴發。"
        buy_pts.append("實體長紅")

    # --- 買賣點彙整偵測 ---
    recent_low = df["low"].tail(3).min()
    is_retrace = (market_phase == "📈上漲盤 (多頭)" and row["volume"] < row["vol_ma5"] and 0 <= (row["close"] - row["ma5"]) / row["ma5"] < 0.015)

    if row["close"] > prev["close"] and row["low"] >= recent_low: buy_pts.append("底部位階支撐(不創新低)")
    if is_retrace: buy_pts.append("量縮回踩5MA(買點)")
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死交關鍵位(上漲買入)")
    if is_gap_up: buy_pts.append("🚀多方跳空缺口")
    if row["vcp_check"]: buy_pts.append("🔋籌碼壓縮(VCP)")

    if row["close"] < prev["close"] and row["high"] <= prev["high"]: sell_pts.append("頭部位階跌破(不創新高)")
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破黃金交叉關鍵位(下跌賣出)")

    # --- 最終評分與結果存入 ---
    if buy_pts: score += 12 * len(set(buy_pts))
    if sell_pts: score -= 20 * len(set(sell_pts))
    if row["vol_ratio"] > 1.8: score += 10
    if is_gap_up: score += 10
    if row["vcp_check"]: score += 5
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    
    # 大盤風控邏輯
    if not is_market and hasattr(st.session_state, 'market_score') and st.session_state.market_score < 40:
        score -= 20

    if row["vcp_check"] and ("噴發" in pattern_name or "眼" in pattern_name):
        pattern_name = "🔋 VCP + " + pattern_name

    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定"
    
    sig = "HOLD"
    if buy_pts: sig = "BUY"
    if sell_pts: sig = "SELL"
    if not is_market and hasattr(st.session_state, 'market_score') and st.session_state.market_score < 40 and sig == "BUY":
        sig = "HOLD (大盤空頭避險)"
        df.at[last_idx, "warning"] = "⚠️ 大盤疲弱，暫緩開火 | " + df.at[last_idx, "warning"]
    df.at[last_idx, "sig_type"] = sig

    risk_vol = (row["atr"] / row["close"]) * 100
    if risk_vol < 1.5: advice = "建議配置: 15~20% (穩健型)"
    elif risk_vol < 3.0: advice = "建議配置: 8~12% (標準型)"
    else: advice = "建議配置: 3~5% (高波動小心)"
    df.at[last_idx, "pos_advice"] = advice

    return df

def plot_advanced_chart(df, title=""):
    if df is None or df.empty: return go.Figure()
    df_plot = df.tail(100).copy()
    
    if "is_first_breakout" not in df_plot.columns: df_plot["is_first_breakout"] = False
    df_plot["is_first_breakout"] = df_plot["is_first_breakout"].fillna(False).astype(bool)
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 1. 主圖：K線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], 
        name="K線", increasing_line_color='#ff4b4b', decreasing_line_color='#28a745'
    ), row=1, col=1)
    
    # 2. 均線族
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)
    
    # 3. 🚀 噴發標記
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

    # 4. ⭐ 發動點
    if "star_signal" in df_plot.columns:
        stars = df_plot[df_plot["star_signal"].fillna(False).astype(bool)]
        if not stars.empty:
            fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=12, color="#FFD700"), name="發動點"), row=1, col=1)
    
    # 5. 副圖：MACD
    if "hist" in df_plot.columns:
        colors = ['#ff4b4b' if v >= 0 else '#28a745' for v in df_plot["hist"]]
        fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    
    fig.update_layout(
        height=650, title=title, template="plotly_white", xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# --- 7. Google 表單同步 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: 
        add_log("SYS", "SYSTEM", "WARN", "未設定 MONITOR_SHEET_ID，跳過同步")
        return
    try:
        # 增加 timestamp 防止快取
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&cache_bus={int(time.time())}"
        df_sheet = pd.read_csv(url)
        
        def clean_col(name):
            if name in df_sheet.columns:
                # 強化清洗：去除 nan、空值，並確保代號為純數字字串
                valid_series = df_sheet[name].astype(str).replace(['nan', 'None', 'NAT', 'nan.0'], np.nan).dropna()
                valid_series = valid_series[valid_series.str.strip() != ""]
                # 確保 2330.TW 這種格式會被正確處理為 2330
                return " ".join(valid_series.apply(lambda x: x.split('.')[0].strip()))
            return ""
        
        st.session_state.search_codes = clean_col('snipe_list')
        st.session_state.inventory_codes = clean_col('inventory_list')
        add_log("SYS", "SYSTEM", "INFO", "成功從 Google 表單同步數據")
    except Exception as e:
        st.error(f"同步失敗: {e}")
        add_log("SYS", "SYSTEM", "ERROR", f"雲端同步失敗: {str(e)}")

# 初始同步
if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# --- 8. 指揮中心 UI ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    
    # 認證區
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    # 推送開關
    st.session_state.enable_discord = st.toggle("📢 開啟 Discord 訊息推送", value=st.session_state.enable_discord)
    
    # 手動同步按鈕
    if st.button("🔄 手動同步雲端清單", use_container_width=True):
        sync_sheets()
        st.success("同步完成")
        st.rerun()
        
    st.divider()
    
    # 編輯區
    st.session_state.search_codes = st.text_area("🎯 狙擊清單 (空格/換行分隔)", value=st.session_state.search_codes, height=150)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單 (空格/換行分隔)", value=st.session_state.inventory_codes, height=100)
    
    # 監控參數
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟全自動盤中監控", value=True)
    analyze_btn = st.button("🚀 立即執行掃描", use_container_width=True, type="primary")
    
    # 系統狀態
    market_status = is_market_open()
    st.info(f"系統時間: {get_taiwan_time().strftime('%H:%M:%S')}\n市場狀態: {'🔴 開盤中' if market_status else '🟢 已收盤'}")

# --- 9. 執行掃描邏輯 ---
def perform_scan(manual_trigger=False):  
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    now = get_taiwan_time()
    st.markdown(f"### 📡 掃描報告：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 解析代號清單
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    # 1. 優先渲染大盤分析 (TAIEX)
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        score = m_last["score"]
        
        # 決定大盤狀態燈號
        if score >= 80: cmd, clz, tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強，適合積極操作。"
        elif score >= 60: cmd, clz, tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中，擇優佈局。"
        elif score >= 40: cmd, clz, tip = "Neutral 觀望", "neutral-signal", "🌪 盤勢震盪中，保持低水位。"
        elif score >= 20: cmd, clz, tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱，注意風險。"
        else: cmd, clz, tip = "💀 強力賣出", "sell-signal", "🚨 極高風險，建議空手。"
        
        # 渲染大盤卡片
        c1, c2 = st.columns([1, 2])
        with c1: 
            diff = m_last['close'] - m_df.iloc[-2]['close']
            st.metric("加權指數", f"{m_last['close']:.2f}", f"{diff:+.2f}")
        with c2: 
            st.markdown(f"<div class='status-card {clz}'>{cmd} | {tip} (評分: {score})</div>", unsafe_allow_html=True)
        
        with st.expander("📊 查看大盤詳細趨勢圖表"):
            st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 加權指數"), use_container_width=True)

    # 2. 多執行緒處理個股
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None or len(df) < 5: continue
                
                # 套用核心策略分析
                df = analyze_strategy(df, is_market=False)
                last = df.iloc[-1]
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                is_inv, is_snipe = sid in inv_list, sid in snipe_list
                
                # 訊號狀態判定
                sig_type = last['sig_type']
                # 加入爆量判定標記
                sig_lvl = f"{sig_type}_{'BOOM' if (sig_type=='BUY' and last['vol_ratio']>1.8) else 'NOR'}"
                
                # 歷史狀態對比 (決定是否發送通知)
                old_sig = st.session_state.notified_status.get(sid)
                old_date = st.session_state.notified_date.get(sid)
                old_price = st.session_state.last_notified_price.get(sid, last['close'])
                price_drop = (last['close'] - old_price) / old_price < -0.02 # 跌幅超過2%觸發更新
                
                # --- 判定是否觸發通知 ---
                if manual_trigger or old_date != today_str or old_sig != sig_lvl or price_drop:
                    should_send = False
                    msg_header = ""

                    # 邏輯 A：庫存股賣訊警示
                    if is_inv and sig_type == "SELL":
                        should_send = True
                        msg_header = "🚨🚨🚨 【 庫存風險警示：建議減碼 】 🚨🚨🚨"
                    
                    # 邏輯 B：狙擊股買訊觸發
                    elif is_snipe and ("BUY" in sig_type or last.get("is_first_breakout", False)):
                        should_send = True
                        if last.get("is_first_breakout"):
                            msg_header = "🚀🚀🚀 【 噴發第一根：強勢確認 】 🚀🚀🚀"
                        elif "量縮回踩" in last['pattern']:
                            msg_header = "🔴🔴🔴 【 回踩支撐：低吸機會 】 🔴🔴🔴"
                        elif last["vol_ratio"] > 1.8:
                            msg_header = "🔥🔥🔥 【 狙擊標的：爆量點火 】 🔥🔥🔥"
                        else:
                            msg_header = "🎯🎯🎯 【 買點觸發：執行計畫 】 🎯🎯🎯"

                    if should_send:
                        # 處理特別提醒 (多方跳空 / VCP)
                        special_alerts = []
                        if last['close'] > df.iloc[-2]['high']: special_alerts.append("🚀 多方跳空缺口")
                        if "VCP" in last['pattern'] or "壓縮" in last['pattern_desc']: special_alerts.append("💎 籌碼壓縮 VCP")
                        special_note = f"💡 **核心關鍵：** `{' | '.join(special_alerts)}`" if special_alerts else ""

                        # 計算建議區間
                        buy_range_low = last['close'] * 0.995
                        buy_range_high = last['close'] * 1.01
                        stop_loss = last['close'] * 0.94  # 預設 6% 停損

                        # 更新狀態防止重複通知
                        if not manual_trigger:
                            st.session_state.notified_status[sid] = sig_lvl
                            st.session_state.notified_date[sid] = today_str
                            st.session_state.last_notified_price[sid] = last['close']
                        
                        add_log(sid, name, sig_type, f"{last['warning']} | {last['pattern']}", last['score'], last['vol_ratio'])

                        # 推送至 Discord
                        if st.session_state.enable_discord and (manual_trigger or is_market_open()):
                            msg_lines = [
                                f"{msg_header}",
                                f"{special_note}" if special_note else "◈ 穩定趨勢追蹤中",
                                f"📝 **解讀：** {last['pattern_desc']}",
                                f"━━━━━━━━━━━━━━━━━━━━",
                                f"📈 **標的：** `{sid} {name}`",
                                f"💰 **現價：** `{last['close']:.2f}`",
                                f"📊 **預估量比：** `{last['vol_ratio']:.2f}x`",
                                f"🛡️ **戰鬥評分：** `{last['score']} / 100`",
                                f"━━━━━━━━━━━━━━━━━━━━",
                                f"✅ **建議買點：** `{buy_range_low:.2f} ~ {buy_range_high:.2f}`",
                                f"❌ **硬性停損：** `{stop_loss:.2f}`",
                                f"━━━━━━━━━━━━━━━━━━━━",
                                f"🔍 **型態：** {last['pattern']}",
                                f"⚠️ **提醒：** {last['warning']}",
                                f"📍 **策略：** {last['pos_advice']}",
                                f"━━━━━━━━━━━━━━━━━━━━",
                                f"⏰ **時間：** {get_taiwan_time().strftime('%H:%M:%S')} {'(手動)' if manual_trigger else ''}",
                                f"🔗 [查看技術圖表](https://www.wantgoo.com/stock/{sid}/technical-chart)"
                            ]
                            send_discord_message("\n".join(msg_lines))
                
                # 收集已處理資料用於 UI 渲染
                processed_stocks.append({
                    "df": df, "last": last, "sid": sid, "name": name, 
                    "is_inv": is_inv, "is_snipe": is_snipe, "score": last["score"], 
                    "warning": last["warning"], "pattern": last["pattern"], "pattern_desc": last["pattern_desc"]
                })
            except Exception as e:
                st.error(f"處理 {sid} 時發生錯誤: {e}")

    # --- UI 渲染部分 ---
    # 3. 狙擊清單 (按評分排序)
    st.subheader("🔥 狙擊目標監控 (按評分強弱)")
    snipe_targets = sorted([s for s in processed_stocks if s["is_snipe"]], key=lambda x: x["score"], reverse=True)
    
    if not snipe_targets:
        st.info("🎯 目前清單無數據，請在側邊欄輸入股票代號。")
    
    for item in snipe_targets:
        last, sid, name, df = item["last"], item["sid"], item["name"], item["df"]
        # 定義等級顏色
        pattern = item['pattern']
        if "🚀" in pattern: rank_tag, tag_clr, txt_clr = "SSS 級", "#ff4b4b", "white"
        elif "💎" in pattern: rank_tag, tag_clr, txt_clr = "SS 級", "#ffa500", "white"
        elif "🕳️" in pattern: rank_tag, tag_clr, txt_clr = "S 級", "#f1c40f", "black"
        else: rank_tag, tag_clr, txt_clr = "A 級", "#3498db", "white"

        is_boom = (last["vol_ratio"] > 1.8 and "BUY" in last["sig_type"])
        border_clr = "#ff4b4b" if "BUY" in last["sig_type"] else "#ccc"
        
        st.markdown(f"""
        <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border_clr};">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:1.2em;">
                    <b>🎯 {sid} {name}</b> 
                    <span style="font-size:0.8em; background:{tag_clr}; color:{txt_clr}; padding:2px 8px; border-radius:4px; margin-left:10px;">{rank_tag}</span>
                </div>
                <div><span style="background:{border_clr}; color:white; padding:4px 15px; border-radius:20px; font-weight:bold;">戰鬥評分: {last['score']}</span></div>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top:10px; padding:10px; background:white; border-radius:5px;">
                <div>📍 <b>現價：</b>{last['close']:.2f} (量比: {last['vol_ratio']:.2f}x)</div>
                <div>⚠️ <b>關鍵提醒：</b>{last['warning']}</div>
            </div>
            <div style="font-size:0.95em; margin-top:10px; color:#333;">
                <b>💡 形態解讀：</b>{item['pattern_desc']}<br>
                <b>💰 資金建議：</b><span style="color:#d35400; font-weight:bold;">{last['pos_advice']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} {name} 完整分析", expanded=("🚀" in pattern)):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {name}"), use_container_width=True)

    # 4. 庫存監控
    st.divider()
    st.subheader("📦 庫存持股健康度")
    inventory_targets = sorted([s for s in processed_stocks if s["is_inv"]], key=lambda x: x["score"], reverse=True)
    
    for item in inventory_targets:
        last, sid, name, df = item["last"], item["sid"], item["name"], item["df"]
        health_clr = "#28a745" if last['score'] >= 60 else ("#ffa500" if last['score'] >= 40 else "#ff4b4b")
        
        st.markdown(f"""
        <div class="dashboard-box" style="border-left: 10px solid {health_clr}; background: #fdfdfe;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:1.1em; color: black;"><b>📦 {sid} {name} | 現價: {last['close']:.2f}</b></div>
                <div><span style="background:{health_clr}; color:white; padding:4px 15px; border-radius:20px; font-weight:bold;">健康度: {last['score']}</span></div>
            </div>
            <div style="font-size:0.9em; margin-top:8px; color:#555;">
                <b>🛡️ 風險建議:</b> <span style="font-weight:bold; color:{health_clr};">{last['pos_advice']}</span><br>
                <b>💡 型態特徵:</b> {item['pattern']} | 乖離: {last['bias_5']:.2f}%
            </div>
        </div>
        """, unsafe_allow_html=True)

    # 5. 日誌渲染
    st.divider()
    st.write("### 📜 戰情即時日誌")
    log_content = "".join(st.session_state.event_log)
    st.markdown(f"<div class='log-container'>{log_content}</div>", unsafe_allow_html=True)

# --- 10. 主循環執行 ---
placeholder = st.empty()

if analyze_btn:
    with placeholder.container(): 
        perform_scan(manual_trigger=True)

elif auto_monitor:
    # 盤中自動刷新邏輯
    if is_market_open():
        with placeholder.container(): 
            perform_scan(manual_trigger=False)
        st.caption(f"🔄 自動監控中... 下次掃描預計於 {interval} 分鐘後")
        time.sleep(interval * 60) # 等待設定的間隔
        st.rerun()
    else:
        # 非盤中僅執行一次，不進入循環
        with placeholder.container(): 
            perform_scan(manual_trigger=False)
        st.warning("🌙 目前非台股盤中時間，自動監控暫停。")
else:
    with placeholder.container(): 
        perform_scan(manual_trigger=False)
