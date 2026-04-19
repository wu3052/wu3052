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
    
    for suffix in [".TW", ".TWO"]:
        ticker = f"{sid}{suffix}"
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            if info.get('lastPrice') is not None:
                st.session_state.sid_map[sid] = ticker
                return ticker
        except: continue
    return f"{sid}.TW"

def send_discord_message(msg):
    # 修復 2: 嚴格判斷開關，只有在勾選開啟且有 Webhook 時才執行
    if not st.session_state.get("enable_discord", True):
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
                    day_vol = int(today_yt['Volume'].sum())
                    day_high = float(today_yt['High'].max())
                    day_low = float(today_yt['Low'].min())
                    
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
            
        # --- ✨ 新增：日期與格式化修正 ---
        if df is not None and not df.empty:
            # 1. 抹除時區資訊 (核心修正：防止 Plotly X 軸錯位)
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            # 2. 填充可能出現的 NaN (防止 TA-Lib 計算崩潰)
            df['volume'] = df['volume'].fillna(0)
            if 'est_volume' in df.columns:
                df['est_volume'] = df['est_volume'].fillna(df['volume'])
        
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

@st.cache_data(ttl=43200) # 籌碼資料半天更新一次即可
def get_chip_details(sid, token):
    try:
        # 1. 三大法人買賣超
        res_inst = requests.get(BASE_URL, params={
            "dataset": "InstitutionalInvestorsBuySell", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        
        # 2. 融資融券增減
        res_margin = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockMarginPurchaseSell", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()

        # 3. 大戶持股比例 (修正了這裡的字串斷行)
        res_holding = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockHoldingSharesPer", 
            "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()

        df_inst = pd.DataFrame(res_inst.get("data", []))
        df_margin = pd.DataFrame(res_margin.get("data", []))
        df_holding = pd.DataFrame(res_holding.get("data", []))

        # 統一轉換欄位名稱為小寫，方便後續計算邏輯使用
        if not df_inst.empty: df_inst.columns = [c.lower() for c in df_inst.columns]
        if not df_margin.empty: df_margin.columns = [c.lower() for c in df_margin.columns]
        if not df_holding.empty: df_holding.columns = [c.lower() for c in df_holding.columns]
        
        return df_inst, df_margin, df_holding
    except Exception as e:
        print(f"籌碼數據獲取失敗 {sid}: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

def calculate_main_cost_logic(df_k, df_i, df_m, df_h, period=40):
    """
    計算主力加權成本與大戶持股
    """
    # 基本檢查：如果 K 線或法人資料是空的就跳過
    if df_k is None or df_k.empty or df_i.empty: 
        return None, 0
    
    # 1. 準備 K 線副本與日期格式
    k = df_k.copy()
    k['date_only'] = k['date'].dt.date
    
    # 計算每日加權均價 (O+H+L+C)/4，模擬主力的平均成交位階
    k['day_avg'] = (k['open'] + k['high'] + k['low'] + k['close']) / 4
    
    # 2. 準備籌碼資料日期格式
    df_i['date_only'] = pd.to_datetime(df_i['date']).dt.date
    
    # 3. 合併資料 (主力定義：外資 + 投信)
    m = pd.merge(k, df_i[['date_only', 'foreign_investor_buy', 'investment_trust_buy']], on='date_only', how='left').fillna(0)
    
    # 併入融資資料 (主力融資)
    if not df_m.empty:
        df_m['date_only'] = pd.to_datetime(df_m['date']).dt.date
        m = pd.merge(m, df_m[['date_only', 'margin_purchase_buy']], on='date_only', how='left').fillna(0)
        # 定義 Smart Money 買盤 = 法人買超 + 融資買進
        m['smart_buy'] = m['foreign_investor_buy'] + m['investment_trust_buy'] + m['margin_purchase_buy']
    else:
        m['smart_buy'] = m['foreign_investor_buy'] + m['investment_trust_buy']

    # 4. 只取最近 period 天中，「主力有買進」的日子來做加權平均
    recent = m[m['smart_buy'] > 0].tail(period)
    if recent.empty:
        return None, 0
    
    # 計算主力加權平均成本：Σ(買量 * 均價) / Σ買量
    avg_cost = (recent['smart_buy'] * recent['day_avg']).sum() / recent['smart_buy'].sum()
    
    # 5. 計算大戶佔比 (對標截圖中的 400 張大戶門檻)
    holder_pct = 0
    if not df_h.empty:
        # 取最新的持股日期
        last_date = df_h['date'].max()
        target = df_h[df_h['date'] == last_date]
        # 統計 400 張以上所有等級的比例總和
        lv_list = ['400-600', '600-800', '800-1000', 'over 1000']
        holder_pct = target[target['level'].isin(lv_list)]['holding_shares_proportion'].sum()
        
    return round(avg_cost, 2), round(holder_pct, 2)

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
    df = df.ffill().bfill()
    
    # 乖離與量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 關鍵轉折位 (交叉點位)
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

# --- 2. 籌碼面數據獲取與初始化 (修正後版本) ---
    # 關鍵修正：先在 DataFrame 建立欄位並給予預設值，預防後續呼叫噴錯
# --- 修正後的推薦寫法片段 ---
    df["main_cost"] = np.nan
    df["holder_pct"] = 0.0
    # 先預設好變數，防止後面評分系統崩潰
    m_cost, h_pct = None, 0 
    last_idx = df.index[-1] # 提到前面定義

    if sid and token and not is_market:
        try:
            df_i, df_m, df_h = get_chip_details(sid, token)
            # 這裡回傳的 m_cost, h_pct 是區域變數
            m_cost, h_pct = calculate_main_cost_logic(df, df_i, df_m, df_h)
            
            df.at[last_idx, "main_cost"] = m_cost
            df.at[last_idx, "holder_pct"] = h_pct
        except Exception:
            pass

    # --- 3. 形態偵測與評分系統初始化 ---
    score = 50
    buy_pts, sell_pts = [], []
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    ma_list_short = [row["ma5"], row["ma10"], row["ma20"]]
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max(ma_list_short) - min(ma_list_short)) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    ma5_up = row["ma5"] > prev["ma5"]
    
    # 糾結判定 (用於 SSS 與 SS 級)
    max_ma_prev = max([prev["ma5"], prev["ma10"], prev["ma20"]])
    min_ma_prev = min([prev["ma5"], prev["ma10"], prev["ma20"]])
    was_tangling = (max_ma_prev - min_ma_prev) / prev["close"] < 0.03
    ma5_up = row["ma5"] > prev["ma5"]
    is_first_breakout = (was_tangling and row["close"] > max_ma_prev and row["vol_ratio"] > 1.2 and ma5_up)

    # 盤勢基礎判定
    if row["ma5"] > row["ma10"] > row["ma20"] and row["close"] > row["ma5"]:
        market_phase = "📈上漲盤 (多頭)"
    elif row["ma5"] < row["ma10"] < row["ma20"] and row["close"] < row["ma5"]:
        market_phase = "📉下跌盤 (空頭)"
    else:
        market_phase = "🍽️盤整盤 (橫盤)"
    df.at[last_idx, "market_phase"] = market_phase

# --- 4. 籌碼權重加分 (修正後的版本) ---
    # 確保使用前面 try 區塊定義的 m_cost 與 h_pct
    if m_cost is not None:  
        dist_to_cost = (row["close"] - m_cost) / m_cost
        if 0 <= dist_to_cost <= 0.05:
            score += 15
            buy_pts.append(f"🛡️ 靠近主力成本 ({m_cost})")
            
        # 修正：這裡原本可能誤寫成 holder_pct，改用 h_pct
        if h_pct > 70:
            score += 10
            buy_pts.append(f"💎 大戶重倉區 ({h_pct}%)")
            
        if row["close"] > m_cost and row["vol_ratio"] > 1.5:
            score += 10
            buy_pts.append("🚀 脫離成本區發動")

    # --- 5. 形態強度層級判定 (優先順序) ---
    pattern_name = market_phase
    pattern_desc = f"目前處於{market_phase}階段。"

    # [SSS] 🚀 噴發第一根
    is_first_breakout = (was_tangling and row["close"] > max_ma_prev and row["vol_ratio"] > 1.2 and ma5_up)
    
    # [其他特徵判定]
    is_long_red = (row["close"] > row["open"]) and ((row["close"] - row["open"]) / row["open"] > 0.03)
    is_vcp = row["vcp_check"]
    is_gap_up = row["open"] > prev["high"] * 1.005

    if is_first_breakout:
        score += 35
        pattern_name = "🚀 噴發第一根"
        pattern_desc = "SSS 級判定！均線糾結後首次帶量突破，能量完全釋放，行情起點。"
        buy_pts.append("噴發訊號")
    elif diff_long < 0.02 and row["close"] > row["ma5"] and ma5_up:
        score += 30
        pattern_name = "💎 鑽石眼"
        pattern_desc = "SS 級判定！五線合一超級共振，週期成本達成一致，發動令已下。"
        buy_pts.append("鑽石眼強勢點")
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        score += 25
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "S 級判定！克服所有長期壓力，進入主升段無壓力區。"
        buy_pts.append("主升段啟動")
    elif diff_short < 0.015 and row["close"] > row["ma5"] and ma5_up and row["close"] > row["open"]:
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

    # --- 6. 買賣點彙整偵測 ---
    recent_low = df["low"].tail(3).min()
    is_retrace = (market_phase == "📈上漲盤 (多頭)" and row["volume"] < row["vol_ma5"] and 0 <= (row["close"] - row["ma5"]) / row["ma5"] < 0.015)

    # 【買點】
    if row["close"] > prev["close"] and row["low"] >= recent_low: buy_pts.append("底部位階支撐(不創新低)")
    if is_retrace: buy_pts.append("量縮回踩5MA(買點)")
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死交關鍵位(上漲買入)")
    if is_gap_up: buy_pts.append("🚀多方跳空缺口")
    if is_vcp: buy_pts.append("🔋籌碼壓縮(VCP)")

    # 【賣點】
    if row["close"] < prev["close"] and row["high"] <= prev["high"]: sell_pts.append("頭部位階跌破(不創新高)")
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破黃金交叉關鍵位(下跌賣出)")

    # --- 7. 最終評分與結果存入 ---
    if buy_pts: score += 12 * len(set(buy_pts))
    if sell_pts: score -= 20 * len(set(sell_pts))
    if row["vol_ratio"] > 1.8: score += 10
    if is_gap_up: score += 10
    if is_vcp: score += 5
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    
    # 外部環境懲罰 (大盤)
    if not is_market and hasattr(st.session_state, 'market_score') and st.session_state.market_score < 40:
        score -= 20

    # 封裝標籤
    if is_vcp and ("噴發" in pattern_name or "眼" in pattern_name):
        pattern_name = "🔋 VCP + " + pattern_name

    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定"
    
    # 決定信號與建議
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
    # 1. 安全檢查：如果沒資料就回傳空圖
    if df is None or df.empty: return go.Figure()
    
    # 2. 準備資料
    df_plot = df.tail(100).copy()
    
    # --- 關鍵修正 A：必須在計算顏色和繪圖前填補空值 ---
    df_plot = df_plot.fillna(0) 
    
    # 3. 初始化圖表 (只定義這一次)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 4. 繪製 K 線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], 
        name="K線", increasing_line_color='#ff4b4b', decreasing_line_color='#28a745'
    ), row=1, col=1)
    
    # 5. 繪製 均線
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    # 6. 繪製 關鍵位
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)
    
    # 7. 標註 噴發訊號
    if "is_first_breakout" in df_plot.columns:
        breakouts = df_plot[df_plot["is_first_breakout"] == True]
        if not breakouts.empty:
            fig.add_trace(go.Scatter(x=breakouts["date"], y=breakouts["low"] * 0.96, mode="markers+text", marker=dict(symbol="triangle-up", size=15, color="#ff4b4b"), text="🚀", textposition="bottom center", name="噴發第一根"), row=1, col=1)

    # 8. 標註 發動訊號
    if "star_signal" in df_plot.columns:
        stars = df_plot[df_plot["star_signal"]]
        if not stars.empty:
            fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=12, color="#FFD700"), name="發動點"), row=1, col=1)
    
    # --- 關鍵修正 B：先算顏色，再畫 MACD ---
    colors = ['#ff4b4b' if v >= 0 else '#28a745' for v in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)
    
    # 9. 圖表佈局設定
    fig.update_layout(
        height=650, title=title, template="plotly_white", 
        xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10), 
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    
    return fig
    
# --- 7. Google 表單同步 ---
def sync_sheets():
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id: return
    try:
        # 1. 抓取雲端 CSV 資料
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(url)
        
        # 2. 定義內部的清洗函數
        def clean_col(name):
            if name in df_sheet.columns:
                # 修正：確保轉換為字串並移除各種空值字眼，最後去掉 NaN
                valid_series = df_sheet[name].astype(str).replace(['nan', 'None', 'NAT', 'nan.0'], np.nan).dropna()
                # 再次過濾掉空白字串
                valid_series = valid_series[valid_series.str.strip() != ""]
                # 處理 2330.0 這種浮點數字串，並用空白串接
                return " ".join(valid_series.apply(lambda x: x.split('.')[0].strip()))
            return ""
        
        # 3. 更新到 Session State (對應你表單的欄位名稱)
        st.session_state.search_codes = clean_col('snipe_list')
        st.session_state.inventory_codes = clean_col('inventory_list')
        
        # 4. 記錄系統日誌
        add_log("SYS", "SYSTEM", "INFO", "成功從 Google 表單同步數據")
        
    except Exception as e:
        st.error(f"同步失敗: {e}")
        add_log("SYS", "SYSTEM", "ERROR", f"雲端同步失敗: {str(e)}")

if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# --- 8. 指揮中心 UI ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    st.session_state.enable_discord = st.toggle("📢 開啟 Discord 訊息推送", value=st.session_state.enable_discord)
    
    if st.button("🔄 手動同步雲端清單"):
        sync_sheets()
        st.rerun()
        
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)

    auto_monitor = st.checkbox("🔄 開啟全自動盤中監控", value=True)
    analyze_btn = st.button("🚀 立即執行掃描", use_container_width=True)
    st.info("💡 盤中自動監控：週一至週五 09:00~13:35。")

    
    
    st.info(f"系統時間: {get_taiwan_time().strftime('%H:%M:%S')}\n市場狀態: {'🔴開盤中' if is_market_open() else '🟢已收盤'}")

# --- 9. 執行掃描邏輯 ---
def perform_scan(manual_trigger=False):  # <--- 已加入 manual_trigger 參數
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    now = get_taiwan_time()
    st.markdown(f"### 📡 掃描時間：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    # 1. 優先渲染大盤分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        score = m_last["score"]
        if score >= 80: cmd, clz, tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強。"
        elif score >= 60: cmd, clz, tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中。"
        elif score >= 40: cmd, clz, tip = "Neutral 觀望", "neutral-signal", "🌪 盤勢震盪中。"
        elif score >= 20: cmd, clz, tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱。"
        else: cmd, clz, tip = "💀 強力賣出", "sell-signal", "🚨 極高風險。"
        
        c1, c2 = st.columns([1, 2])
        with c1: st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
        with c2: st.markdown(f"<div class='status-card {clz}'>{cmd} | {tip} (評分: {score})</div>", unsafe_allow_html=True)
        with st.expander("📊 查看加權指數 (大盤) 詳細分析圖表"):
            st.plotly_chart(plot_advanced_chart(m_df, "TAIEX 加權指數"), use_container_width=True)

    # 2. 處理個股
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        
        for future in as_completed(future_to_sid): # 建議加上 as_completed 提高效率
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None: continue
                
                # 執行策略分析 (這會用到我們剛才修正的 analyze_strategy)
                df = analyze_strategy(df, sid=sid, token=fm_token, is_market=False)
                last = df.iloc[-1]
                
                # 取得股票名稱
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                is_inv, is_snipe = sid in inv_list, sid in snipe_list
                
                # 訊號分級邏輯
                sig_type = last.get('sig_type', 'HOLD')
                sig_lvl = f"{sig_type}_{'BOOM' if (sig_type=='BUY' and last.get('vol_ratio', 0)>1.8) else 'NOR'}"
                
                # --- 這裡就是你問的修改點：資料清洗與格式化 ---
                raw_main_cost = last.get('main_cost', np.nan)
                raw_holder_pct = last.get('holder_pct', np.nan)
                
                # 預先格式化好字串，這樣下方 Discord 和 UI 顯示時就不會噴錯
                main_cost_val = f"{float(raw_main_cost):.2f}" if pd.notnull(raw_main_cost) else "無數據"
                holder_val = f"{float(raw_holder_pct):.1f}%" if pd.notnull(raw_holder_pct) else "無數據"
                current_price = f"{float(last['close']):.2f}" if 'close' in last else "---"
                vol_ratio_val = f"{float(last['vol_ratio']):.2f}" if 'vol_ratio' in last else "1.00"

                old_sig = st.session_state.notified_status.get(sid)
                old_date = st.session_state.notified_date.get(sid)
                old_price = st.session_state.last_notified_price.get(sid, last['close'])
                price_drop = (last['close'] - old_price) / old_price < -0.02 
                
                # --- 判定觸發 ---
                if manual_trigger or old_date != today_str or old_sig != sig_lvl or price_drop:
                    should_send = False
                    msg_header = ""

                    if is_inv and sig_type == "SELL":
                        should_send = True
                        msg_header = f"🩸 **【庫存風險警示】**"
                    elif is_snipe and ("BUY" in sig_type or last.get("is_first_breakout", False)):
                        should_send = True
                        if last.get("is_first_breakout"):
                            msg_header = "🚀 **【 噴發第一根確認 】**\n均線糾結慣性改變，請立即追蹤！"
                        elif "量縮回踩" in last['pattern']:
                            msg_header = "📉 **【 強勢股回踩買點 】**\n縮量測支撐，留意低吸機會。"
                        elif last["vol_ratio"] > 1.8:
                            msg_header = f"🔥 **【 狙擊目標爆量 】**\n動能達 {vol_ratio_val}x 全面點火，準備開火！"
                        else:
                            msg_header = "🏹 **【 買點訊號觸發 】**\n訊號已達標，準備執行交易計畫。"

                    if should_send:
                        if not manual_trigger:
                            st.session_state.notified_status[sid] = sig_lvl
                            st.session_state.notified_date[sid] = today_str
                            st.session_state.last_notified_price[sid] = last['close']
                        
                        add_log(sid, name, "BUY" if ("BUY" in sig_type or last.get("is_first_breakout")) else "SELL", f"{last['warning']} | {last['pattern']}", last['score'], last['vol_ratio'])

                        if st.session_state.get("enable_discord", False) and (manual_trigger or is_market_open()):
                            # --- 這裡直接套用上面做好的 main_cost_val ---
                            discord_msg = (
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"{msg_header} {'(手動掃描)' if manual_trigger else ''}\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"**標的：** `{sid} {name}`\n"
                                f"**評分：** `{last['score']} 分` \n"
                                f"**形態：** `{last['pattern']}`\n"
                                f"**現價：** `{current_price}` (量比: `{vol_ratio_val}x`)\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"🛡️ **籌碼監控：**\n"
                                f"● 主力成本：`{main_cost_val}`\n"
                                f"● 大戶持股：`{holder_val}`\n\n"
                                f"💡 **核心解讀：**\n"
                                f"{last['pattern_desc']}\n\n"
                                f"🔍 **關鍵買賣點：**\n"
                                f"`{last['warning']}`\n\n"
                                f"📍 **{last['pos_advice']}**\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"⏰ 通知時間: {get_taiwan_time().strftime('%H:%M:%S')}"
                            )
                            send_discord_message(discord_msg)

                # 存入處理後的列表供下方 UI 渲染
                    processed_stocks.append({
                    "df": df, "last": last, "sid": sid, "name": name, 
                    "is_inv": is_inv, "is_snipe": is_snipe, 
                    "score": last.get("score", 0), 
                    "warning": last.get("warning", "---"), 
                    "pattern": last.get("pattern", "---"), 
                    "pattern_desc": last.get("pattern_desc", ""),
                    "main_cost_val": main_cost_val, # UI 顯示專用
                    "holder_val": holder_val       # UI 顯示專用
                })
                
            except Exception as e:
                st.error(f"處理 {sid} 時發生錯誤: {e}")
    # 3. 顯示區
    st.subheader("🔥 狙擊目標監控 (按分數強弱排序)")
    
    # 這裡加入一個過濾：確保 item 裡面的 df 不是 None 才進行排序與顯示
    snipe_targets = [s for s in processed_stocks if s["is_snipe"] and s.get("df") is not None]
    snipe_targets = sorted(snipe_targets, key=lambda x: x.get("score", 0), reverse=True)
    
    if not snipe_targets:
        st.info("🎯 目前狙擊清單尚無數據（或掃描中），請確認代號是否正確。")
    
    for item in snipe_targets:
        # 使用 .get() 確保即使 key 消失也不會報錯
        last = item.get("last")
        sid = item.get("sid")
        name = item.get("name")
        df = item.get("df")
        
        # 額外保險：如果這支股票分析失敗(last是空的)，就跳過不顯示
        if last is None or df is None:
            continue
        
        # --- 新增：等級顏色判定 ---
# --- 修正後的等級與字色判定 ---
        pattern = item['pattern']
        if "🚀" in pattern: rank_tag, tag_clr, txt_clr = "SSS 級", "#ff4b4b", "white"
        elif "💎" in pattern: rank_tag, tag_clr, txt_clr = "SS 級", "#ffa500", "white"
        elif "🕳️" in pattern: rank_tag, tag_clr, txt_clr = "S 級", "#f1c40f", "black" # 黃底黑字
        elif "🟡" in pattern: rank_tag, tag_clr, txt_clr = "A 級", "#2ecc71", "black" # 綠底黑字
        else: rank_tag, tag_clr, txt_clr = "B 級", "#3498db", "white"

        is_boom = ("BUY" in last["sig_type"] and last["vol_ratio"] > 1.8)
        border_clr = "#ff4b4b" if "BUY" in last["sig_type"] else ("#28a745" if "SELL" in last["sig_type"] else "#ccc")
        
        st.markdown(f"""
        <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border_clr}; margin-bottom:10px; text-align:left; padding: 15px; background: #f8f9fa; border-radius: 5px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:1.2em;">
                    <b>🎯 {sid} {name}</b> 
                    <span style="font-size:0.8em; background:{tag_clr}; color:{txt_clr}; padding:2px 8px; border-radius:4px; margin-left:10px;">{rank_tag}</span>
                </div>
                <div><span style="background:{border_clr}; color:white; padding:4px 15px; border-radius:20px; font-weight:bold;">戰鬥評分: {last['score']}</span></div>
            </div>
            
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top:10px; padding:10px; background:white; border-radius:5px;">
                <div>📍 <b>現價：</b>{last['close']:.2f} (量比: {last['vol_ratio']:.2f}x)</div>
                <div>🛡️ <b>主力成本：</b>{item['main_cost_val']}</div>
                <div>📊 <b>大戶持股：</b>{item['holder_val']}</div>
                <div>⚠️ <b>關鍵提醒：</b>{last['warning']}</div>
            </div>
            
            <div style="font-size:0.95em; margin-top:10px; color:#333; line-height:1.5;">
                <b>💡 形態解讀：</b>{item['pattern_desc']}<br>
                <b>💰 資金建議：</b><span style="color:#d35400; font-weight:bold;">{last['pos_advice']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} {name} 分析圖表", expanded=("🚀" in pattern)):
            # 確保這裡傳入的 df 是正確的
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {name}"), use_container_width=True)

    st.divider()
    st.subheader("📦 庫存持股監控")
    inventory_targets = sorted([s for s in processed_stocks if s["is_inv"]], key=lambda x: x["score"], reverse=True)
    for item in inventory_targets:
        last, sid, name, df = item["last"], item["sid"], item["name"], item["df"]
        
        # 庫存警示色：分數低於 50 變橘，低於 30 變紅
        health_clr = "#28a745" if last['score'] >= 60 else ("#ffa500" if last['score'] >= 40 else "#ff4b4b")
        
        st.markdown(f"""
        <div class="dashboard-box" style="border-left: 10px solid {health_clr}; margin-bottom:10px; text-align:left; padding: 15px; background: #fdfdfe; border-radius: 5px;">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div style="font-size:1.1em;"><b>📦 {sid} {name} | 現價: {last['close']:.2f} | {item['pattern']}</b></div>
                <div><span style="background:{health_clr}; color:white; padding:4px 15px; border-radius:20px; font-weight:bold;">健康度: {last['score']}</span></div>
            </div>
            <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top:10px; padding:10px; background:#f0f2f6; border-radius:5px;">
                <div>🏠 <b>主力成本：</b>{item['main_cost_val']}</div>
                <div>📈 <b>5MA 乖離：</b>{last['bias_5']:.2f}%</div>
            </div>
            <div style="font-size:0.9em; margin-top:8px; color:#555;">
                <b>🛡️ 風險狀態:</b> <span style="font-weight:bold; color:{health_clr};">{last['pos_advice']}</span> | 提醒: {last['warning']}<br>
                <b>💡 形態解讀：</b>{item['pattern_desc']}
            </div>
        </div>
        """, unsafe_allow_html=True)
        with st.expander(f"查看 {sid} {name} 分析圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {name}"), use_container_width=True)

    st.divider()
    st.write("### 📜 戰情即時日誌")
    log_content = "".join(st.session_state.event_log)
    st.markdown(f"<div class='log-container'>{log_content}</div>", unsafe_allow_html=True)

# --- 10. 主循環邏輯 ---
placeholder = st.empty()

if analyze_btn:
    # 手動點擊：強行執行，傳入 True 以無視開盤限制並強制推送訊息
    with placeholder.container(): 
        perform_scan(manual_trigger=True)

elif auto_monitor:
    # 全自動模式
    if is_market_open():
        with placeholder.container(): 
            perform_scan(manual_trigger=False)
        
        # 修正點：縮短 sleep 時間，讓 UI 保持活性
        st.caption(f"🔄 盤中自動監控中... 下次掃描預計於 {interval} 分鐘後 (或手動刷新)")
        st.info(f"最後更新時間: {get_taiwan_time().strftime('%H:%M:%S')}")
        
        # 這裡建議 sleep 10-30 秒即可，太長會讓側邊欄按鈕卡住
        time.sleep(10) 
        st.rerun()
    else:
        # 非開盤時間：執行一次靜默掃描顯示資訊，然後進入休眠
        with placeholder.container(): 
            perform_scan(manual_trigger=False)
        st.warning("🌙 目前非台灣股市開盤時間 (09:00~13:30)，自動監控已進入休眠。")
        # 非開盤時間不需要 rerun，節省效能

else:
    # 未開啟自動，也沒按按鈕：只執行一次靜默掃描，讓畫面有資料
    with placeholder.container(): 
        perform_scan(manual_trigger=False)
    st.info("💡 自動監控已關閉，請點擊「立即執行掃描」或開啟自動監控。")