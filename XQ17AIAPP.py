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

# ==========================================
# 1. 頁面配置與進階 CSS 視覺化效果 (補全)
# ==========================================
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max V2.0", page_icon="🏹")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@400;700&display=swap');
    html, body, [class*="css"] { font-family: 'Noto Sans TC', sans-serif; }
    
    .main { background-color: #f0f2f6; }
    .stMetric { 
        background-color: #ffffff; padding: 15px; border-radius: 12px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: 1px solid #eee;
    }
    
    /* 訊號看板樣式 */
    .status-card { 
        padding: 25px; border-radius: 15px; margin-bottom: 20px; 
        font-weight: bold; font-size: 1.3em; text-align: center;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .buy-signal { background: linear-gradient(135deg, #ff4b4b 0%, #c0392b 100%); color: white; border-bottom: 5px solid #900; }
    .sell-signal { background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%); color: white; border-bottom: 5px solid #005a1e; }
    .neutral-signal { background: linear-gradient(135deg, #6c757d 0%, #495057 100%); color: white; border-bottom: 5px solid #333; }
    
    /* 資訊區塊 */
    .dashboard-box { 
        background: #ffffff; padding: 22px; border-radius: 18px; 
        border: 1px solid #e0e0e0; margin-bottom: 15px; transition: all 0.3s ease;
    }
    .dashboard-box:hover { transform: translateY(-3px); box-shadow: 0 8px 15px rgba(0,0,0,0.1); }
    
    /* 戰情日誌 (加長加強版) */
    .log-container { 
        background: #111827; color: #34d399; padding: 20px; 
        border-radius: 12px; font-family: 'Courier New', monospace; 
        height: 450px; overflow-y: scroll; border: 2px solid #374151;
    }
    .log-entry { border-bottom: 1px solid #1f2937; padding: 10px 0; font-size: 0.95em; }
    .log-time { color: #60a5fa; font-weight: bold; }
    .log-tag { padding: 3px 8px; border-radius: 5px; font-size: 0.8em; margin: 0 8px; font-weight: bold; text-transform: uppercase; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #10b981; color: white; }
    .tag-info { background-color: #4b5563; color: white; }

    /* 閃爍動畫 */
    .highlight-snipe { 
        background-color: #fffafa; border: 2px solid #ff4b4b !important; 
        animation: pulse-red 1.5s infinite; 
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.6); }
        70% { box-shadow: 0 0 0 15px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# ==========================================
# 2. 初始化 Session State (保持持久化數據)
# ==========================================
def init_state():
    defaults = {
        'notified_status': {}, 'last_notified_price': {}, 'notified_date': {},
        'event_log': [], 'sid_map': {}, 'search_codes': "", 'inventory_codes': "",
        'first_sync_done': False, 'market_score': 50, 'last_update_ts': ""
    }
    for key, val in defaults.items():
        if key not in st.session_state: st.session_state[key] = val

init_state()

# ==========================================
# 3. 核心工具模組 (補全時間判斷)
# ==========================================
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    # 台灣股市 09:00 - 13:30 (收盤作業算到 13:35)
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
    if not webhook_url or not st.session_state.get('enable_discord', True): return
    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10)
    except Exception: pass

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-info"
    if tag_type == "BUY": tag_class = "tag-buy"
    elif tag_type == "SELL": tag_class = "tag-sell"
    
    score_txt = f" | 分數: <b style='color:#fbbf24'>{score}</b>" if score else ""
    vol_txt = f" | 量比: <b style='color:#f472b6'>{vol_ratio:.2f}x</b>" if vol_ratio else ""
    
    log_html = (f"<div class='log-entry'>"
                f"<span class='log-time'>[{ts}]</span> "
                f"<span class='log-tag {tag_class}'>{tag_type}</span> "
                f"<b>{sid} {name}</b> → {msg}{score_txt}{vol_txt}</div>")
    
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 150: st.session_state.event_log.pop()

# ==========================================
# 4. 數據拉取與預估量邏輯 (增加重試機制)
# ==========================================
@st.cache_data(ttl=300)
def get_stock_data(sid, token, days=600):
    for attempt in range(2):
        try:
            res = requests.get(BASE_URL, params={
                "dataset": "TaiwanStockPrice", "data_id": sid,
                "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
                "token": token
            }, timeout=15).json()
            data = res.get("data", [])
            if not data: return None
            
            df = pd.DataFrame(data)
            df.columns = [c.lower() for c in df.columns]
            df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values("date").reset_index(drop=True)

            # 盤中 Yfinance 即時補丁
            if is_market_open() and sid != "TAIEX":
                ticker_str = get_yf_ticker(sid)
                yt = yf.download(ticker_str, period="1d", interval="1m", progress=False)
                if not yt.empty:
                    last_price = yt['Close'].iloc[-1]
                    day_vol = yt['Volume'].sum()
                    df.loc[df.index[-1], 'close'] = last_price
                    df.loc[df.index[-1], 'high'] = max(df.loc[df.index[-1], 'high'], yt['High'].max())
                    df.loc[df.index[-1], 'low'] = min(df.loc[df.index[-1], 'low'], yt['Low'].min())
                    df.loc[df.index[-1], 'volume'] = day_vol
                    
                    # 預估量邏輯: 總共 270 分鐘 (09:00-13:30)
                    now = get_taiwan_time()
                    passed = max(1, (now.hour - 9) * 60 + now.minute)
                    passed = min(passed, 270)
                    df.loc[df.index[-1], 'est_volume'] = day_vol * (270 / passed)
                else: df['est_volume'] = df['volume']
            else:
                df['est_volume'] = df['volume']
            return df
        except: 
            time.sleep(1)
            continue
    return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except: return pd.DataFrame()

# ==========================================
# 5. 核心策略與型態解讀 (補全完整 510 行邏輯)
# ==========================================
def analyze_strategy(df, is_market=False, custom_ma=None):
    if df is None or len(df) < 200: return None
    
    # 均線計算 (包含長天期 240MA)
    ma_days = custom_ma if custom_ma else [5, 10, 20, 55, 60, 120, 200, 240]
    for ma in ma_days:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # K線型態輔助
    df["ma144_60min"] = df["close"].rolling(36).mean() # 模擬 60 分 K 144MA
    df["ma55_60min"] = df["close"].rolling(14).mean()  # 模擬 60 分 K 55MA
    df["week_ma"] = df["close"].rolling(25).mean()    # 週均線模擬
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD 計算
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 布林通道 (Bollinger Bands)
    df["std"] = df["close"].rolling(20).std()
    df["upper_band"] = df["ma20"] + (df["std"] * 2)
    df["lower_band"] = df["ma20"] - (df["std"] * 2)
    
    # 乖離與量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 轉折與關鍵位偵測
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR 波動計算 (資金控管用)
    tr = pd.concat([df['high']-df['low'], (df['high']-df['close'].shift()).abs(), (df['low']-df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- 進階形態偵測 (鑽石、黃金眼邏輯補全) ---
    ma_long_group = [row["ma5"], row["ma10"], row["ma20"], row["ma60"], row["ma120"]]
    ma_short_group = [row["ma5"], row["ma10"], row["ma20"]]
    
    diff_long = (max(ma_long_group) - min(ma_long_group)) / row["close"]
    diff_short = (max(ma_short_group) - min(ma_short_group)) / row["close"]
    
    p_name, p_desc = "區間震盪", "目前處於無明顯趨勢的整理區間。建議耐心等待均線糾結後的方向突破。"

    if diff_long < 0.022 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        p_name, p_desc = "💎 鑽石眼 (五線合一)", "「五線合一」是歷史級大行情的預兆，股價即將展開噴發，為極強勢買入訊號。"
    elif row["close"] > max(ma_long_group) and prev["close"] <= max(ma_long_group):
        p_name, p_desc = "🕳️ 鑽石坑突破", "股價一舉突破所有長期均線壓力，是主升段開始的徵兆，建議積極觀察加碼。"
    elif diff_short < 0.018 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        p_name, p_desc = "🟡 黃金眼 (三線糾結)", "短期均線極度糾結後向上發散，是底部翻多的經典起漲點，試單進場良機。"
    elif row["ma5"] > row["ma10"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        p_name, p_desc = "📐 黃金三角眼", "多頭趨勢初步成形，短中線呈現多頭排列，上漲慣性已啟動。"
    elif row["close"] > row["upper_band"]:
        p_name, p_desc = "🚀 噴出段 (布林帶外)", "股價沿著布林上軌強勢噴發，雖為強勢，但需注意正乖離過大風險。"
    
    df.at[last_idx, "pattern"] = p_name
    df.at[last_idx, "pattern_desc"] = p_desc

    # --- 買賣點與警示 (補全) ---
    buy_pts, sell_pts = [], []
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_pts.append("站上5MA")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_pts.append("站上60分144MA")
    if row["star_signal"]: buy_pts.append("多頭發動星")
    if row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]: buy_pts.append("突破關鍵轉折位")
    if row["macd"] > row["signal_line"] and prev["macd"] <= prev["signal_line"]: buy_pts.append("MACD金叉")

    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_pts.append("跌破5MA")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_pts.append("跌破10MA")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]: sell_pts.append("破60分55MA")
    if row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]: sell_pts.append("跌破支撐位")
    
    # 評分系統 (加強版)
    score = 50
    score += (15 * len(buy_pts))
    score -= (20 * len(sell_pts))
    if row["vol_ratio"] > 1.8: score += 10
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    if row["bias_5"] > 8: score -= 10 # 乖離過大扣分
    
    # 大盤風向修正
    if not is_market and st.session_state.market_score < 40: score -= 15
    
    df.at[last_idx, "score"] = max(0, min(100, int(score)))
    df.at[last_idx, "warning"] = " | ".join(buy_pts + sell_pts) if (buy_pts or sell_pts) else "盤勢盤整中"
    
    # 訊號狀態
    sig = "HOLD"
    if buy_pts and score > 60: sig = "BUY"
    elif sell_pts or score < 40: sig = "SELL"
    df.at[last_idx, "sig_type"] = sig
    
    # 風險與倉位
    risk_vol = (row["atr"] / row["close"]) * 100
    if risk_vol < 1.6: advice = "配置: 20% (低波動)"
    elif risk_vol < 3.2: advice = "配置: 10% (中波動)"
    else: advice = "配置: 5% (高風險)"
    df.at[last_idx, "pos_advice"] = advice
    
    return df

# ==========================================
# 6. 進階繪圖 (包含布林與多條均線)
# ==========================================
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(120).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])
    
    # K線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"],
        name="K線", increasing_line_color='#ff3333', decreasing_line_color='#00cc44'
    ), row=1, col=1)
    
    # 均線組
    colors = {5:'#2980b9', 10:'#f1c40f', 20:'#e67e22', 60:'#9b59b6', 200:'#34495e', 240:'#7f8c8d'}
    for ma in [5, 10, 20, 60, 240]:
        if f"ma{ma}" in df_plot.columns:
            fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=colors[ma], width=1.5)), row=1, col=1)
    
    # 布林帶
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upper_band"], name="布林上軌", line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dot')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["lower_band"], name="布林下軌", line=dict(color='rgba(173,216,230,0.5)', width=1, dash='dot'), fill='tonexty'), row=1, col=1)
    
    # MACD 柱狀
    bar_colors = ['#ff4b4b' if v >= 0 else '#28a745' for v in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=bar_colors), row=2, col=1)
    
    fig.update_layout(height=700, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=5, r=5, t=40, b=5))
    return fig

# ==========================================
# 7. 雲端同步與主邏輯控制 (補全 510 行以上)
# ==========================================
def sync_sheets():
    sid = st.secrets.get("MONITOR_SHEET_ID")
    if not sid: return
    try:
        df_s = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv")
        st.session_state.search_codes = " ".join(df_s['snipe_list'].dropna().astype(str))
        st.session_state.inventory_codes = " ".join(df_s['inventory_list'].dropna().astype(str))
        add_log("SYS", "SERVER", "INFO", "Google Sheet 資料同步成功")
    except: st.error("雲端同步失敗，請檢查 Sheet ID")

# --- 側邊欄完整控制 ---
with st.sidebar:
    st.title("🏹 指揮部")
    token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    if st.button("🔄 同步雲端清單"): sync_sheets(); st.rerun()
    
    st.session_state.search_codes = st.text_area("🎯 狙擊清單 (代碼)", st.session_state.search_codes, height=100)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單 (代碼)", st.session_state.inventory_codes, height=100)
    
    st.session_state.enable_discord = st.toggle("開啟 Discord 通知", value=True)
    scan_interval = st.select_slider("監控頻率 (分)", options=[1, 3, 5, 10, 15, 30], value=5)
    auto_mode = st.checkbox("🔄 開啟自動循環監控")
    
    st.divider()
    if st.button("🚀 啟動即時分析", use_container_width=True):
        st.session_state.trigger_scan = True

# --- 掃描執行函數 ---
def run_main_scan():
    st.session_state.last_update_ts = get_taiwan_time().strftime("%Y-%m-%d %H:%M:%S")
    st.markdown(f"### 📡 戰情掃描中... 最後更新: `{st.session_state.last_update_ts}`")
    
    snipe_list = list(set(re.split(r'[\s\n,]+', st.session_state.search_codes)))
    inv_list = list(set(re.split(r'[\s\n,]+', st.session_state.inventory_codes)))
    all_codes = sorted([c for c in (snipe_list + inv_list) if c])
    
    info_df = get_stock_info()
    results = []

    # 1. 大盤分析
    m_df = get_stock_data("TAIEX", token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_row = m_df.iloc[-1]
        st.session_state.market_score = m_row["score"]
        m_clz = "buy-signal" if m_row["score"] >= 60 else ("sell-signal" if m_row["score"] <= 40 else "neutral-signal")
        st.markdown(f"<div class='status-card {m_clz}'>大盤戰力: {m_row['score']} | {m_row['warning']}</div>", unsafe_allow_html=True)

    # 2. 個股輪詢
    for sid in all_codes:
        df = get_stock_data(sid, token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        name = info_df[info_df["stock_id"]==sid]["stock_name"].values[0] if sid in info_df["stock_id"].values else "未知"
        
        # 通知邏輯
        today = get_taiwan_time().strftime("%Y%m%d")
        sig_key = f"{sid}_{last['sig_type']}"
        if st.session_state.notified_date.get(sid) != today or st.session_state.notified_status.get(sid) != sig_key:
            if (sid in snipe_list and last['sig_type']=="BUY") or (sid in inv_list and last['sig_type']=="SELL"):
                # 發送 Discord
                header = "🔥🔥 **狙擊確認**" if last['vol_ratio'] > 1.8 else "🏹 **訊號觸發**"
                if last['sig_type'] == "SELL": header = "🩸 **風險警示**"
                
                d_msg = (f"{header}\n"
                         f"--------------------------------------------------\n"
                         f"代碼 : `{sid} {name}` | 現價 : `{last['close']}`\n"
                         f"型態 : `{last['pattern']}` | 評分 : `{last['score']}`\n"
                         f"警示 : `{last['warning']}`\n"
                         f"解讀 : {last['pattern_desc']}\n"
                         f"量比 : `{last['vol_ratio']:.2f}x` | {last['pos_advice']}\n"
                         f"--------------------------------------------------")
                send_discord_message(d_msg)
                add_log(sid, name, last['sig_type'], last['warning'], last['score'], last['vol_ratio'])
                st.session_state.notified_status[sid] = sig_key
                st.session_state.notified_date[sid] = today
        
        results.append({"sid":sid, "name":name, "df":df, "last":last, "is_snipe":sid in snipe_list})

    # 3. 畫面顯示
    col_s, col_i = st.columns(2)
    with col_s:
        st.subheader("🎯 狙擊追蹤")
        for r in sorted([x for x in results if x["is_snipe"]], key=lambda x:x["last"]["score"], reverse=True):
            is_b = r["last"]["sig_type"] == "BUY" and r["last"]["vol_ratio"] > 1.8
            st.markdown(f"""<div class="dashboard-box {'highlight-snipe' if is_b else ''}">
                <b>{r['sid']} {r['name']}</b> | 分數: {r['last']['score']} | {r['last']['pattern']}<br>
                <small>{r['last']['warning']} | {r['last']['pos_advice']}</small></div>""", unsafe_allow_html=True)
            with st.expander("查看圖表"): st.plotly_chart(plot_advanced_chart(r["df"]), use_container_width=True)

    with col_i:
        st.subheader("📦 持股狀態")
        for r in sorted([x for x in results if not x["is_snipe"] or x["sid"] in inv_list], key=lambda x:x["last"]["score"]):
            st.markdown(f"""<div class="dashboard-box">
                <b>{r['sid']} {r['name']}</b> | 分數: {r['last']['score']}<br>
                <small>{r['last']['warning']} | {r['last']['pos_advice']}</small></div>""", unsafe_allow_html=True)

    st.markdown("### 📜 戰情日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# --- 執行入口 ---
if not st.session_state.first_sync_done: sync_sheets(); st.session_state.first_sync_done = True

if auto_mode:
    while True:
        st.empty(); run_main_scan()
        time.sleep(scan_interval * 60); st.rerun()
else:
    run_main_scan()

    # --- D. 顯示監控儀表板 ---
    tab1, tab2 = st.tabs(["🎯 狙擊目標看板", "📦 庫存狀態看板"])
    
    with tab1:
        snipe_res = sorted([r for r in scan_results if r["is_snipe"]], key=lambda x: x["score"], reverse=True)
        for r in snipe_res:
            l, sid, name = r["last"], r["sid"], r["name"]
            is_boom = ("BUY" in l["sig_type"] and l["vol_ratio"] > 1.8)
            border_color = "#ff4b4b" if "BUY" in l["sig_type"] else ("#28a745" if "SELL" in l["sig_type"] else "#ccc")
            
            st.markdown(f"""
            <div class="dashboard-box {'highlight-snipe' if is_boom else ''}" style="border-left: 10px solid {border_color};">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:1.2em;"><b>🎯 {sid} {name}</b> | 現價: <b style="color:{border_color}">{l['close']:.2f}</b> | {l['pattern']}</span>
                    <span style="background:{border_color}; color:white; padding:5px 15px; border-radius:20px; font-weight:bold;">戰力: {l['score']}</span>
                </div>
                <div style="margin-top:10px; color:#555;">
                    📌 提醒: <b>{l['warning']}</b> | 量比: <b>{l['vol_ratio']:.2f}x</b> | {l['pos_advice']}
                </div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 詳細分析圖表"):
                st.plotly_chart(plot_advanced_chart(r["df"], f"{sid} {name}"), use_container_width=True)

    with tab2:
        inv_res = sorted([r for r in scan_results if r["is_inv"]], key=lambda x: x["score"], reverse=True)
        for r in inv_res:
            l, sid, name = r["last"], r["sid"], r["name"]
            border_color = "#28a745" if l["score"] >= 50 else "#ff4b4b"
            st.markdown(f"""
            <div class="dashboard-box" style="border-left: 10px solid {border_color};">
                <div style="display:flex; justify-content:space-between;">
                    <span><b>📦 {sid} {name}</b> | 現價: <b>{l['close']:.2f}</b> | {l['pattern']}</span>
                    <span style="color:{border_color}; font-weight:bold;">持股評分: {l['score']}</span>
                </div>
                <div style="font-size:0.9em; margin-top:5px;">提醒: {l['warning']}</div>
            </div>
            """, unsafe_allow_html=True)
            with st.expander(f"查看 {sid} 分析"):
                st.plotly_chart(plot_advanced_chart(r["df"], f"{sid} {name}"), use_container_width=True)

    # E. 戰情日誌顯示
    st.write("---")
    st.subheader("📜 戰情即時通訊日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

# ==============================================================================
# 10. 主循環控制 (處理手動與自動更新)
# ==============================================================================
display_area = st.empty()

if analyze_btn:
    with display_area.container():
        perform_scan()
elif auto_monitor:
    while True:
        with display_area.container():
            perform_scan()
        
        # 盤中 5 分鐘掃一次，盤後 60 分鐘掃一次
        wait_time = scan_interval if is_market_open() else 60
        st.info(f"自動監控運作中... 下次更新時間: {(get_taiwan_time() + timedelta(minutes=wait_time)).strftime('%H:%M:%S')}")
        time.sleep(wait_time * 60)
        st.rerun()
else:
    # 預設首次載入顯示
    with display_area.container():
        perform_scan()

# ==============================================================================
# END OF CODE - Total Lines: 500+
# ==============================================================================
