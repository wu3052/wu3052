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
    # 解決需求 2: 強制判斷 enable_discord 狀態
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
        return df
    except Exception as e:
        print(f"Error fetching {sid}: {e}")
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# --- 5. 核心策略分析 (需求 3: 增加多空盤勢判斷及量縮回踩邏輯) ---
def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 180: return None
    
    # 均線計算
    for ma in [5, 10, 20, 55, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
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

    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 盤勢階段判定 (解決需求 3) ---
    # 判斷標準：依據均線排列與斜率
    is_up_trend = row["close"] > row["ma20"] and row["ma20"] > row["ma60"] and row["ma60"] > prev["ma60"]
    is_down_trend = row["close"] < row["ma20"] and row["ma20"] < row["ma60"] and row["ma60"] < prev["ma60"]
    
    if is_up_trend:
        market_type = "📈 上漲盤 (多頭市場)"
        market_desc = "市場情緒樂觀，低點不破前低、高點更過前高。股票越來越貴，建議找尋回踩買點順勢而為。"
    elif is_down_trend:
        market_type = "📉 下跌盤 (空頭市場)"
        market_desc = "市場情緒悲觀，賣壓沉重，高點不過前高、低點續破前低。即便反彈也難扭轉跌勢，建議保留現金觀望。"
    else:
        market_type = "🌪 盤整盤 (橫盤市場)"
        market_desc = "多空力道旗鼓相當，股價在箱型內震盪。買家不追高，賣家不賤賣，等待均線糾結後的方向突破。"

    # --- 形態偵測邏輯 ---
    ma_list_short = [row["ma5"], row["ma10"], row["ma20"]]
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    diff_short = (max(ma_list_short) - min(ma_list_short)) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    
    ma5_up = row["ma5"] > prev["ma5"]
    max_ma_prev = max([prev["ma5"], prev["ma10"], prev["ma20"]])
    min_ma_prev = min([prev["ma5"], prev["ma10"], prev["ma20"]])
    was_tangling = (max_ma_prev - min_ma_prev) / prev["close"] < 0.03

    is_first_breakout = (was_tangling and row["close"] > max_ma_prev and row["vol_ratio"] > 1.2 and ma5_up)
    
    pattern_name = market_type
    pattern_desc = market_desc

    # 組合新形態邏輯 (保留原本)
    if is_first_breakout:
        pattern_name = "🚀 噴發第一根"
        pattern_desc = "均線糾結後首次帶量突破，慣性徹底改變，極具爆發力的進場點。"
    # 新增: 上漲盤量縮回踩 5MA
    elif is_up_trend and abs(row["close"] - row["ma5"])/row["ma5"] < 0.015 and row["volume"] < row["vol_ma5"]*0.8:
        pattern_name = "🔄 上漲回踩 (量縮買點)"
        pattern_desc = "上漲趨勢中的黃金位！第一時間沒買到，目前回踩 5MA 且量能萎縮，是優質的二段進場點。"
    elif diff_long < 0.02 and row["close"] > row["ma5"] and ma5_up:
        pattern_name = "💎 鑽石眼"
        pattern_desc = "「四線或五線合一」且 5MA 轉強，是「超級飆股」噴發前的訊號。"
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "成功克服了市場的所有長期壓力，是「主升段」的開始，「勇敢加碼」。"
    elif diff_short < 0.015 and row["close"] > row["ma5"] and ma5_up and row["close"] > row["open"]:
        pattern_name = "🟡 黃金眼"
        pattern_desc = "均線將同步向上發散，「三均線整齊排列」，「底部翻多」的最強訊號。"
    elif row["ma5"] > row["ma10"] and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        pattern_name = "📐 黃金三角眼"
        pattern_desc = "多頭一浪啟動！形成堅實支撐三角區，標誌空頭盤整結束，「試單進場點」。"
    
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc

    # --- 買賣點與位階判斷 ---
    buy_pts, sell_pts = [], []
    recent_low = df["low"].tail(3).min()
    is_price_up = row["close"] > prev["close"]
    is_price_down = row["close"] < prev["close"]

    if is_price_up and row["low"] >= recent_low: buy_pts.append("底部位階支撐(1日不創新低)")
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA(買點)")
    if "回踩" in pattern_name: buy_pts.append("量縮回踩5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA(買點)")
    if row["star_signal"]: buy_pts.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("站上死亡交叉關鍵位(上漲買入)")

    if is_price_down and row["high"] <= prev["high"]: sell_pts.append("頭部位階跌破(1日不創新高)")
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]: sell_pts.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破黃金交叉關鍵位(下跌賣出)")

    # --- 評分邏輯 ---
    score = 50
    if buy_pts: score += 15 * len(buy_pts)
    if sell_pts: score -= 20 * len(sell_pts)
    if row["vol_ratio"] > 1.8: score += 10
    if is_up_trend: score += 10
    if is_down_trend: score -= 15
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "趨勢穩定中"
    
    sig = "HOLD"
    if buy_pts: sig = "BUY"
    if sell_pts: sig = "SELL"
    df.at[last_idx, "sig_type"] = sig
    
    risk_volatility = (row["atr"] / row["close"]) * 100
    pos_advice = "建議配置: 15~20% (穩健)" if risk_volatility < 1.5 else ("建議配置: 8~12% (標準)" if risk_volatility < 3.0 else "建議配置: 3~5% (高波動)")
    df.at[last_idx, "pos_advice"] = pos_advice
    
    return df

def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], 
        name="K線", increasing_line_color='#ff4b4b', decreasing_line_color='#28a745'
    ), row=1, col=1)
    
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)
    
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.4)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.4)', dash='dash')), row=1, col=1)
    
    colors = ['#ff4b4b' if v >= 0 else '#28a745' for v in df_plot["hist"]]
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
    except Exception as e:
        st.error(f"同步失敗: {e}")

if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# --- 8. 指揮中心 UI ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    # 修改 1 & 2: Discord 推送控制
    st.session_state.enable_discord = st.toggle("📢 開啟 Discord 訊息推送", value=st.session_state.get("enable_discord", True))
    
    if st.button("🔄 手動同步雲端清單"):
        sync_sheets()
        st.rerun()
        
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    
    st.info("💡 盤中自動監控：週一至週五 09:00~13:35。")
    auto_monitor = st.checkbox("🔄 開啟全自動盤中監控", value=True)
    analyze_btn = st.button("🚀 立即執行掃描", use_container_width=True)
    
    st.info(f"系統時間: {get_taiwan_time().strftime('%H:%M:%S')}\n市場狀態: {'🔴開盤中' if is_market_open() else '🟢已收盤'}")

# --- 9. 修復 1: 確保置頂的大盤資訊不消失 ---
def show_market_dashboard():
    st.title("🏹 股票狙擊手 Pro Max V2")
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

# --- 10. 執行掃描邏輯 ---
def perform_scan():
    today_str = get_taiwan_time().strftime('%Y-%m-%d')
    st.markdown(f"### 📡 掃描時間：{get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')}")
    
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    processed_stocks = []

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_sid = {executor.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for future in future_to_sid:
            sid = future_to_sid[future]
            try:
                df = future.result()
                if df is None: continue
                df = analyze_strategy(df, is_market=False)
                last = df.iloc[-1]
                name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
                
                sig_type = last['sig_type']
                sig_lvl = f"{sig_type}_{'BOOM' if last['vol_ratio']>1.8 else 'NOR'}_{last['pattern']}"
                
                # Discord 推送與日誌紀錄
                if st.session_state.notified_status.get(sid) != sig_lvl:
                    if (sid in inv_list and sig_type == "SELL") or (sid in snipe_list and (sig_type == "BUY" or "回踩" in last['pattern'])):
                        msg = (f"🎯 **【狙擊訊號】**\n代碼 : `{sid} {name}`\n現價 : `{last['close']:.2f}`\n技術形態 : `{last['pattern']}`\n評分 : `{last['score']}`\n"
                               f"提醒 : `{last['warning']}`\n解讀 : {last['pattern_desc']}")
                        send_discord_message(msg)
                        add_log(sid, name, "BUY" if sig_type=="BUY" else "SELL", f"{last['warning']} | {last['pattern']}", last['score'], last['vol_ratio'])
                        st.session_state.notified_status[sid] = sig_lvl

                processed_stocks.append({"df": df, "last": last, "sid": sid, "name": name, "is_inv": sid in inv_list, "is_snipe": sid in snipe_list})
            except Exception: continue

    # 顯示結果
    for t_type, title in [("is_snipe", "🔥 狙擊目標監控"), ("is_inv", "📦 庫存持股監控")]:
        st.subheader(title)
        items = sorted([s for s in processed_stocks if s[t_type]], key=lambda x: x["last"]["score"], reverse=True)
        for item in items:
            last = item["last"]
            border_clr = "#ff4b4b" if "BUY" in last["sig_type"] else ("#28a745" if "SELL" in last["sig_type"] else "#ccc")
            st.markdown(f"""
            <div class="dashboard-box" style="border-left: 10px solid {border_clr}; margin-bottom:10px; text-align:left;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <div><b>🎯 {item['sid']} {item['name']} | 現價: {last['close']:.2f} | {last['pattern']}</b></div>
                    <div style="background:{border_clr}; color:white; padding:4px 15px; border-radius:20px;">評分: {last['score']}</div>
                </div>
                <div style="font-size:0.9em; margin-top:8px;">
                    <b>💡 形態解讀：</b>{last['pattern_desc']}<br>
                    <b>📍 {last['pos_advice']}</b> | 提醒: {last['warning']} | 預估量比: {last['vol_ratio']:.2f}x
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {item['sid']} 分析圖表"): st.plotly_chart(plot_advanced_chart(item["df"], f"{item['sid']} {item['name']}"), use_container_width=True)

    st.divider()
    st.write("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 11. 主循環 ---
show_market_dashboard()
placeholder = st.empty()

if analyze_btn or (auto_monitor and is_market_open()):
    with placeholder.container(): perform_scan()
    if auto_monitor and is_market_open():
        time.sleep(interval * 60)
        st.rerun()
elif auto_monitor and not is_market_open():
    with placeholder.container(): perform_scan()
    st.warning("🌙 市場休市中，自動監控休眠中。")
else:
    with placeholder.container(): perform_scan()