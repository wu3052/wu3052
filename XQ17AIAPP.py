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

# ==============================================================================
# 1. 頁面配置與進階 CSS 視覺控制 (包含所有自定義動畫與卡片樣式)
# ==============================================================================
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max V2", page_icon="🏹")

st.markdown("""
<style>
    /* 主背景與全域字體 */
    .main { background-color: #f8f9fa; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    
    /* 指標卡片樣式 */
    .stMetric { 
        background-color: white; 
        padding: 20px; 
        border-radius: 12px; 
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #eee;
    }
    
    /* 狀態顯示卡 */
    .status-card { 
        padding: 25px; 
        border-radius: 15px; 
        margin-bottom: 20px; 
        font-weight: 800; 
        font-size: 1.3em; 
        text-align: center; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
    }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 10px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 10px solid #155724; }
    .neutral-signal { background-color: #6c757d; color: white; border-left: 10px solid #343a40; }
    
    /* 個股儀表板方塊 */
    .dashboard-box { 
        background: #ffffff; 
        padding: 25px; 
        border-radius: 18px; 
        border: 1px solid #e0e0e0; 
        margin-bottom: 15px;
        transition: transform 0.2s, box-shadow 0.2s; 
    }
    .dashboard-box:hover {
        transform: translateY(-3px);
        box-shadow: 0 6px 15px rgba(0,0,0,0.1);
    }
    
    /* 戰情日誌風格 */
    .log-container { 
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
        color: #f1f5f9; 
        padding: 25px; 
        border-radius: 15px; 
        height: 450px; 
        overflow-y: scroll; 
        border: 2px solid #334155;
        box-shadow: inset 0 2px 15px rgba(0,0,0,0.5);
        line-height: 1.8;
    }
    .log-entry { 
        border-bottom: 1px solid #1e293b; 
        padding: 10px 0; 
        font-size: 0.95em;
        display: flex;
        align-items: center;
    }
    .log-time { color: #38bdf8; font-family: 'Courier New', monospace; font-weight: bold; margin-right: 15px; }
    .log-tag { padding: 3px 8px; border-radius: 6px; font-size: 0.75em; margin-right: 10px; font-weight: 900; text-transform: uppercase; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #64748b; color: white; }
    
    /* 爆量閃爍動畫 */
    .highlight-snipe { 
        background-color: #fff5f5; 
        border: 3px solid #ff4b4b !important; 
        animation: pulse-red 2s infinite; 
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.6); }
        70% { box-shadow: 0 0 0 15px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
</style>
""", unsafe_allow_html=True)

# 定義常數
BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# ==============================================================================
# 2. 初始化 Session State (確保跨執行狀態持久化)
# ==============================================================================
if 'notified_status' not in st.session_state:
    st.session_state.notified_status = {}
if 'last_notified_price' not in st.session_state:
    st.session_state.last_notified_price = {}
if 'notified_date' not in st.session_state:
    st.session_state.notified_date = {} 
if 'event_log' not in st.session_state:
    st.session_state.event_log = []
if 'sid_map' not in st.session_state:
    st.session_state.sid_map = {}
if 'search_codes' not in st.session_state:
    st.session_state.search_codes = ""
if 'inventory_codes' not in st.session_state:
    st.session_state.inventory_codes = ""
if 'first_sync_done' not in st.session_state:
    st.session_state.first_sync_done = False
if 'market_score' not in st.session_state:
    st.session_state.market_score = 50

# ==============================================================================
# 3. 核心工具模組 (時間、市場判斷、網路請求)
# ==============================================================================
def get_taiwan_time():
    """獲取當前台北時間"""
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    """判斷台股是否在交易時段內"""
    now = get_taiwan_time()
    # 周一到周五
    if now.weekday() > 4:
        return False
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    current_time = now.time()
    return start_time <= current_time <= end_time

def get_yf_ticker(sid):
    """將台股代碼轉換為 Yahoo Finance 格式並快取"""
    if sid in st.session_state.sid_map:
        return st.session_state.sid_map[sid]
    
    # 嘗試上市代碼
    ticker_tw = f"{sid}.TW"
    t_tw = yf.Ticker(ticker_tw)
    try:
        if t_tw.fast_info.get('previous_close') is not None:
            st.session_state.sid_map[sid] = ticker_tw
            return ticker_tw
    except:
        pass
        
    # 嘗試上櫃代碼
    ticker_two = f"{sid}.TWO"
    t_two = yf.Ticker(ticker_two)
    try:
        if t_two.fast_info.get('previous_close') is not None:
            st.session_state.sid_map[sid] = ticker_two
            return ticker_two
    except:
        pass
        
    return ticker_tw

def send_discord_message(msg):
    """發送訊息至 Discord Webhook"""
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        payload = {"content": msg}
        requests.post(webhook_url, json=payload, timeout=10)
    except Exception as e:
        print(f"Discord 發送失敗: {e}")

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    """記錄至 UI 戰情日誌"""
    ts = get_taiwan_time().strftime("%H:%M:%S")
    
    if tag_type == "BUY":
        tag_class = "tag-buy"
    elif tag_type == "SELL":
        tag_class = "tag-sell"
    else:
        tag_class = "tag-info"
    
    score_info = f" | 戰鬥評分: <b style='color:#f87171'>{score}</b>" if score else ""
    vol_info = f" | 量比: <b style='color:#fbbf24'>{vol_ratio:.2f}x</b>" if vol_ratio else ""
    
    log_html = (
        f"<div class='log-entry'>"
        f"<span class='log-time'>[{ts}]</span> "
        f"<span class='log-tag {tag_class}'>{tag_type}</span> "
        f"<b>{sid} {name}</b>：{msg}{score_info}{vol_info}"
        f"</div>"
    )
    
    st.session_state.event_log.insert(0, log_html)
    # 限制日誌長度防止瀏覽器卡頓
    if len(st.session_state.event_log) > 100:
        st.session_state.event_log.pop()

# ==============================================================================
# 4. 數據獲取與即時量預估模組
# ==============================================================================
@st.cache_data(ttl=300)
def get_stock_data(sid, token):
    """結合 FinMind 歷史數據與 yfinance 即時數據"""
    try:
        # 1. 獲取 FinMind 歷史日K
        start_date = (datetime.now() - timedelta(days=600)).strftime("%Y-%m-%d")
        params = {
            "dataset": "TaiwanStockPrice",
            "data_id": sid,
            "start_date": start_date,
            "token": token
        }
        res = requests.get(BASE_URL, params=params, timeout=15).json()
        data = res.get("data", [])
        if not data:
            return None
            
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        # 2. 盤中即時數據校準
        if is_market_open() and sid != "TAIEX":
            ticker_str = get_yf_ticker(sid)
            # 使用 5 分鐘線來統計今日總量與最後價格
            yt = yf.download(ticker_str, period="1d", interval="5m", progress=False)
            if not yt.empty:
                last_price = yt['Close'].iloc[-1]
                day_high = yt['High'].max()
                day_low = yt['Low'].min()
                day_vol = yt['Volume'].sum()
                
                # 更新最後一筆數據為盤中最新狀態
                df.loc[df.index[-1], 'close'] = last_price
                df.loc[df.index[-1], 'high'] = max(df.loc[df.index[-1], 'high'], day_high)
                df.loc[df.index[-1], 'low'] = min(df.loc[df.index[-1], 'low'], day_low)
                df.loc[df.index[-1], 'volume'] = day_vol
                
                # 計算預估成交量 (依據開盤經過時間)
                now = get_taiwan_time()
                minutes_passed = (now.hour - 9) * 60 + now.minute
                if now.hour >= 13 and now.minute >= 30:
                    minutes_passed = 270
                minutes_passed = max(1, min(270, minutes_passed))
                
                df.loc[df.index[-1], 'est_volume'] = day_vol * (270 / minutes_passed)
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
    """獲取台股基本資料清單"""
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=15)
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

# ==============================================================================
# 5. 核心策略分析模組 (技術指標、形態、評分、買賣點)
# ==============================================================================
def analyze_strategy(df, is_market=False):
    """
    台股多因子技術分析系統
    包含：均線族、MACD、關鍵轉折位、ATR風險控管、形態偵測、量價評分
    """
    if df is None or len(df) < 200:
        return None
    
    # --- A. 技術指標計算 ---
    # 日線均線
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma55"] = df["close"].rolling(55).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    
    # 仿 60 分鐘線指標 (250分鐘/日 -> 參數約除以 4.1)
    df["ma144_60min"] = df["close"].rolling(36).mean()
    df["ma55_60min"] = df["close"].rolling(14).mean()
    
    # 週線趨勢判斷 (25日約等於 5週)
    df["week_ma"] = df["close"].rolling(25).mean()
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # MACD 計算
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與成交量比
    df["bias_5"] = ((df["close"] - df["ma5"]) / df["ma5"]) * 100
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # --- B. 關鍵位轉折偵測 ---
    # 尋找 5MA 與 10MA 的交叉作為支撐阻力參考位
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    
    # 記錄上一個死叉位置的股價作為突破參考
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    # 記錄上一個金叉位置的股價作為跌破參考
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    
    # 站上發動點訊號
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # ATR 資金控管指標
    h_l = df['high'] - df['low']
    h_c = (df['high'] - df['close'].shift()).abs()
    l_c = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev = df.iloc[-2]
    
    # --- C. 形態偵測邏輯 ---
    ma_list_long = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
    ma_short_group = [row["ma5"], row["ma10"], row["ma20"]]
    
    # 計算均線糾結度 (標準差比)
    diff_short = (max(ma_short_group) - min(ma_short_group)) / row["close"]
    diff_long = (max(ma_list_long) - min(ma_list_long)) / row["close"]
    
    pattern_name = "一般盤整"
    pattern_desc = "目前處於無明顯趨勢的整理區間。建議耐心等待均線糾結後的方向突破。"

    if diff_long < 0.02 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        pattern_name = "💎 鑽石眼"
        pattern_desc = "「四線或五線合一」是「超級飆股」的訊號，股價將展開「無壓力」的飆升。"
    elif row["close"] > max(ma_list_long) and prev["close"] <= max(ma_list_long):
        pattern_name = "🕳️ 鑽石坑"
        pattern_desc = "成功克服了市場的所有長期壓力，是「主升段」的開始，「勇敢加碼」。"
    elif diff_short < 0.015 and row["close"] > row["ma5"] and row["close"] > row["open"]:
        pattern_name = "🟡 黃金眼"
        pattern_desc = "均線將同步向上發散，「三均線整齊排列」，「底部翻多」的最強訊號。"
    elif row["ma5"] > row["ma10"] and row["ma5"] > row["ma20"] and prev["ma5"] <= prev["ma10"]:
        pattern_name = "📐 黃金三角眼"
        pattern_desc = "多頭一浪啟動！標誌空頭盤整結束與新上漲慣性開始，「試單進場點」。"
    
    df.at[last_idx, "pattern"] = pattern_name
    df.at[last_idx, "pattern_desc"] = pattern_desc

    # --- D. 買賣點與警告判定 ---
    buy_signals = []
    sell_signals = []
    
    # 買入條件清單
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]:
        buy_signals.append("站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]:
        buy_signals.append("站上60分144MA(買點)")
    if row["star_signal"]:
        buy_signals.append("站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]):
        if row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]:
            buy_signals.append("突破關鍵位(上漲買入)")

    # 賣出/警示條件清單
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]:
        sell_signals.append("跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]:
        sell_signals.append("跌破10MA(賣點)")
    if row["close"] < row["ma55_60min"] and prev["close"] >= prev["ma55_60min"]:
        sell_signals.append("跌破60分55MA(注意賣點)")
    if row["close"] < row["ma144_60min"] and prev["close"] >= prev["ma144_60min"]:
        sell_signals.append("跌破60分144MA(賣點)")
    if not pd.isna(row["downward_key"]):
        if row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]:
            sell_signals.append("跌破關鍵位(下跌賣出)")

    # --- E. 綜合戰鬥評分系統 (0-100) ---
    score = 50
    # 多頭加分
    score += (15 * len(buy_signals))
    if row["vol_ratio"] > 1.8: score += 10
    if row["close"] > row["ma200"]: score += 5
    if row["is_weekly_bull"]: score += 5
    # 空頭減分
    score -= (20 * len(sell_signals))
    # 大盤濾網
    if not is_market and st.session_state.market_score < 40:
        score -= 20
    
    df.at[last_idx, "score"] = max(0, min(100, score))
    df.at[last_idx, "warning"] = " | ".join(buy_signals + sell_signals) if (buy_signals or sell_signals) else "趨勢穩定中"
    
    # 決定訊號類型
    final_sig = "HOLD"
    if buy_signals: final_sig = "BUY"
    if sell_signals: final_sig = "SELL"
    # 防守邏輯：大盤太差時不建議買入
    if not is_market and st.session_state.market_score < 40 and final_sig == "BUY":
        final_sig = "HOLD (大盤避險)"
        
    df.at[last_idx, "sig_type"] = final_sig
    
    # 風險分級與部位建議
    risk_percent = (row["atr"] / row["close"]) * 100
    if risk_percent < 1.5:
        df.at[last_idx, "pos_advice"] = "建議配置: 15~20% (穩健型)"
        df.at[last_idx, "risk_lv"] = "low"
    elif risk_percent < 3.0:
        df.at[last_idx, "pos_advice"] = "建議配置: 8~12% (標準型)"
        df.at[last_idx, "risk_lv"] = "mid"
    else:
        df.at[last_idx, "pos_advice"] = "建議配置: 3~5% (高波動小心)"
        df.at[last_idx, "risk_lv"] = "high"
        
    return df

# ==============================================================================
# 6. 進階圖表視覺化
# ==============================================================================
def plot_advanced_chart(df, title=""):
    """使用 Plotly 繪製包含均線、關鍵位與 MACD 的 K 線圖"""
    df_plot = df.tail(100).copy()
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.05, 
        row_heights=[0.75, 0.25]
    )
    
    # 1. 主圖：K線
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], 
        low=df_plot["low"], close=df_plot["close"],
        name="K線", 
        increasing_line_color='#ff4b4b', 
        decreasing_line_color='#28a745'
    ), row=1, col=1)
    
    # 2. 均線族
    ma_configs = [
        ("ma5", "#2980b9", 1.5), ("ma10", "#f1c40f", 1.5), 
        ("ma20", "#e67e22", 1.8), ("ma60", "#9b59b6", 2.0),
        ("ma200", "#34495e", 2.5)
    ]
    for col, color, width in ma_configs:
        if col in df_plot.columns:
            fig.add_trace(go.Scatter(
                x=df_plot["date"], y=df_plot[col], 
                name=col.upper(), 
                line=dict(color=color, width=width)
            ), row=1, col=1)
    
    # 3. 關鍵轉折虛線
    fig.add_trace(go.Scatter(
        x=df_plot["date"], y=df_plot["upward_key"], 
        name="上漲壓力位", 
        line=dict(color='rgba(235,77,75,0.4)', dash='dash')
    ), row=1, col=1)
    
    # 4. 副圖：MACD
    macd_colors = ['#ff4b4b' if val >= 0 else '#28a745' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(
        x=df_plot["date"], y=df_plot["hist"], 
        name="MACD柱狀", 
        marker_color=macd_colors
    ), row=2, col=1)
    
    fig.update_layout(
        height=700, 
        title=f"<b>{title} 技術分析分析圖</b>", 
        template="plotly_white", 
        xaxis_rangeslider_visible=False, 
        margin=dict(l=10, r=10, t=50, b=10)
    )
    return fig

# ==============================================================================
# 7. Google 表單雲端同步
# ==============================================================================
def sync_sheets():
    """從 Google Sheet 獲取監控與庫存清單"""
    sheet_id = st.secrets.get("MONITOR_SHEET_ID")
    if not sheet_id:
        return
    try:
        csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        df_sheet = pd.read_csv(csv_url)
        
        # 清理並組合清單
        if 'snipe_list' in df_sheet.columns:
            snipe_data = df_sheet['snipe_list'].dropna().astype(str).tolist()
            st.session_state.search_codes = " ".join([s.split('.')[0].strip() for s in snipe_data])
            
        if 'inventory_list' in df_sheet.columns:
            inv_data = df_sheet['inventory_list'].dropna().astype(str).tolist()
            st.session_state.inventory_codes = " ".join([s.split('.')[0].strip() for s in inv_data])
            
        add_log("SYS", "SYSTEM", "INFO", "✅ 已成功從 Google 表單同步清單資料")
    except Exception as e:
        st.error(f"Google 表單同步出錯: {e}")

# 初次執行同步
if not st.session_state.first_sync_done:
    sync_sheets()
    st.session_state.first_sync_done = True

# ==============================================================================
# 8. 側邊控制欄
# ==============================================================================
with st.sidebar:
    st.title("🏹 狙擊指揮中心")
    st.write("---")
    
    # API 配置
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    # 清單管理
    if st.button("🔄 同步 Google 雲端清單", use_container_width=True):
        sync_sheets()
        st.rerun()
        
    st.session_state.search_codes = st.text_area(
        "🎯 狙擊追蹤清單", 
        value=st.session_state.search_codes,
        help="輸入股票代碼，以空白或換行分隔"
    )
    
    st.session_state.inventory_codes = st.text_area(
        "📦 庫存監控清單", 
        value=st.session_state.inventory_codes
    )
    
    st.write("---")
    # 監控配置
    scan_interval = st.slider("自動監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動循環掃描")
    
    analyze_btn = st.button("🚀 啟動即時分析掃描", use_container_width=True)

# ==============================================================================
# 9. 核心掃描流程與 Discord 推送邏輯
# ==============================================================================
def perform_scan():
    """執行全清單掃描與訊號發送"""
    current_time_str = get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')
    today_date = get_taiwan_time().strftime('%Y-%m-%d')
    st.markdown(f"### 📡 系統狀態：正在掃描... | 最後更新：`{current_time_str}`")
    
    # 整理代碼清單
    snipe_list = [c.strip() for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c.strip()]
    inv_list = [c.strip() for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c.strip()]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    stock_info = get_stock_info()
    scan_results = []

    # A. 大盤分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        m_last = m_df.iloc[-1]
        st.session_state.market_score = m_last["score"]
        
        m_color = "buy-signal" if m_last["score"] >= 60 else ("sell-signal" if m_last["score"] <= 40 else "neutral-signal")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("加權指數", f"{m_last['close']:.0f}", f"{m_last['close']-m_df.iloc[-2]['close']:.1f}")
        with col2:
            st.markdown(f"<div class='status-card {m_color}'>大盤綜合評分: {m_last['score']} | {m_last['warning']}</div>", unsafe_allow_html=True)

    # B. 個股逐一掃描
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None:
            continue
            
        df = analyze_strategy(df)
        last = df.iloc[-1]
        
        # 獲取股名
        name_search = stock_info[stock_info["stock_id"] == sid]["stock_name"].values
        name = name_search[0] if len(name_search) > 0 else "未知"
        
        is_inv = sid in inv_list
        is_snipe = sid in snipe_list
        sig_type = last['sig_type']

        # --- C. 訊號觸發與通知判斷 ---
        # 組合唯一訊號標籤 (類型+是否爆量)
        sig_id = f"{sig_type}_{'BOOM' if (sig_type=='BUY' and last['vol_ratio']>1.8) else 'NOR'}"
        
        notified_sig = st.session_state.notified_status.get(sid)
        notified_date = st.session_state.notified_date.get(sid)

        # 滿足通知條件：當日未通知過此代碼，或訊號發生轉變
        should_notify = (notified_date != today_date) or (notified_sig != sig_id)
        
        if should_notify:
            # 判斷是否為關鍵訊號 (買狙擊清單，或賣庫存清單)
            is_critical_buy = (is_snipe and "BUY" in sig_type)
            is_critical_sell = (is_inv and sig_type == "SELL")
            
            if is_critical_buy or is_critical_sell:
                # 建立 Discord 訊息內容 (完整展開無刪減格式)
                header = "🔥🔥 **【 狙 擊 目 標 確 認 】** 🔥🔥" if last['vol_ratio'] > 1.8 else "🏹 **【 訊 號 觸 發 】**"
                if sig_type == "SELL":
                    header = "🩸 **【 庫 存 風 險 警 示 】**"
                
                content = (
                    f"{header}\n"
                    f"--------------------------------------------------------------------------------------------\n"
                    f"股價代碼 : `{sid} {name}`\n"
                    f"現價 : `{last['close']:.2f}`\n"
                    f"技術型態 : `{last['pattern']}`\n"
                    f"戰鬥評分: `{last['score']}`\n"
                    f"提醒: `{last['warning']}`\n"
                    f"💡 形態解讀：{last['pattern_desc']}\n"
                    f"📍 `{last['pos_advice']}`\n"
                    f"預估量比: `{last['vol_ratio']:.2f}x`\n"
                    f"--------------------------------------------------------------------------------------------"
                )
                
                send_discord_message(content)
                add_log(sid, name, "BUY" if "BUY" in sig_type else "SELL", f"{last['warning']} | {last['pattern']}", last['score'], last['vol_ratio'])
                
                # 更新通知狀態
                st.session_state.notified_status[sid] = sig_id
                st.session_state.notified_date[sid] = today_date

        scan_results.append({
            "df": df, "last": last, "sid": sid, "name": name, 
            "is_inv": is_inv, "is_snipe": is_snipe, "score": last["score"]
        })

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
