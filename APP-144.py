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
st.set_page_config(layout="wide", page_title="海海股狙擊手 Pro Max V3", page_icon="🏹")

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
        color: #e2e8f0; padding: 20px; border-radius: 12px; height: 400px; overflow-y: scroll; border: 1px solid #334155;
    }
    .log-entry { border-bottom: 1px solid #334155; padding: 8px 0; font-size: 0.9em; }
    .log-time { color: #38bdf8; font-weight: bold; margin-right: 10px; }
    .log-tag { padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 5px; font-weight: bold; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #64748b; color: white; }
    .highlight-snipe { background-color: #fff5f5; border: 2px solid #ff4b4b !important; animation: pulse-red 2s infinite; }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.4); }
        70% { box-shadow: 0 0 0 10px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
states = [
    ('notified_status', {}), ('last_notified_price', {}), ('notified_date', {}),
    ('event_log', []), ('sid_map', {}), ('search_codes', ""), ('inventory_codes', ""),
    ('first_sync_done', False), ('market_score', 50), ('enable_discord', True)
]
for key, val in states:
    if key not in st.session_state: st.session_state[key] = val

# --- 3. 核心工具模組 ---
def get_taiwan_time(): return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start, end = datetime.strptime("09:00", "%H:%M").time(), datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start <= now.time() <= end

def get_yf_ticker(sid):
    if sid == "TAIEX": return "^TWII"
    if sid in st.session_state.sid_map: return st.session_state.sid_map[sid]
    for suffix in [".TW", ".TWO"]:
        ticker = f"{sid}{suffix}"
        try:
            if yf.Ticker(ticker).fast_info.get('lastPrice') is not None:
                st.session_state.sid_map[sid] = ticker
                return ticker
        except: continue
    return f"{sid}.TW"

def send_discord_message(msg):
    if not st.session_state.get("enable_discord", True): return
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        try: requests.post(webhook_url, json={"content": msg}, timeout=10)
        except: pass

def add_log(sid, name, tag_type, msg, score=None, vol_ratio=None):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-buy" if tag_type == "BUY" else ("tag-sell" if tag_type == "SELL" else "tag-info")
    score_html = f" | 評分: <b>{score}</b>" if score is not None else ""
    vol_html = f" | 量比: <b>{vol_ratio:.2f}x</b>" if vol_ratio is not None else ""
    log_html = f"<div class='log-entry'><span class='log-time'>[{ts}]</span> <span class='log-tag {tag_class}'>{tag_type}</span> <b>{sid} {name}</b> -> {msg}{score_html}{vol_html}</div>"
    st.session_state.event_log.insert(0, log_html)
    if len(st.session_state.event_log) > 100: st.session_state.event_log.pop()

# --- 4. 海海策略：自動選股邏輯 (YoY 30% + 144MA + 40W) ---
@st.cache_data(ttl=86400)
def get_all_taiwan_stock_codes():
    try:
        df_twse = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=2")[0]
        list_twse = [c.split('　')[0] + ".TW" for c in df_twse[0] if len(c.split('　')[0]) == 4]
        df_otc = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=4")[0]
        list_otc = [c.split('　')[0] + ".TWO" for c in df_otc[0] if len(c.split('　')[0]) == 4]
        return list_twse + list_otc
    except: return ["2330.TW", "2317.TW", "3131.TWO", "6830.TWO"]

def check_haihai_fundamental(sid, token):
    try:
        r = requests.get(BASE_URL, params={"dataset": "TaiwanStockMonthRevenue", "data_id": sid, "token": token}, timeout=5).json()
        df = pd.DataFrame(r['data'])
        if len(df) >= 13:
            curr, prev = df.iloc[-1]['revenue'], df.iloc[-13]['revenue']
            yoy = ((curr - prev) / prev) * 100
            yoy_total = df.iloc[-1]['revenue_year_growth']
            if yoy >= 30 and yoy_total > 0: return True, round(yoy, 2)
    except: pass
    return False, 0

def run_haihai_auto_scan(token):
    all_codes = get_all_taiwan_stock_codes()
    batch_size = 200
    potential_list = []
    p_bar = st.progress(0, text="正在進行技術面初篩...")
    
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        data = yf.download(batch, period="260d", interval="1d", group_by='ticker', threads=True, progress=False)
        for ticker in batch:
            try:
                df = data[ticker].dropna()
                if len(df) < 200: continue
                c = df['Close']
                ma5, ma10, ma20 = c.rolling(5).mean().iloc[-1], c.rolling(10).mean().iloc[-1], c.rolling(20).mean().iloc[-1]
                ma144, ma200 = c.rolling(144).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
                dist = (max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / c.iloc[-1]
                # 技術初篩：站上144MA與200MA(40週) 且 糾結 < 5%
                if c.iloc[-1] > ma144 and c.iloc[-1] > ma200 and dist < 0.05:
                    potential_list.append(ticker.split('.')[0])
            except: continue
        p_bar.progress(min((i + batch_size) / len(all_codes), 1.0))
    
    final_hits = []
    st.toast(f"技術面達標 {len(potential_list)} 檔，檢查財報中...")
    for sid in potential_list:
        is_good, _ = check_haihai_fundamental(sid, token)
        if is_good: final_hits.append(sid)
        time.sleep(0.05)
    return final_hits

# --- 5. 數據獲取與分析 (整合原本 V2 邏輯) ---
def calculate_est_volume(current_vol):
    now = get_taiwan_time()
    passed = (now.hour * 60 + now.minute) - 540
    return current_vol * (270 / (passed + 10)) if 5 < passed < 270 else current_vol

@st.cache_data(ttl=30 if is_market_open() else 3600)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockPrice", "data_id": sid, "start_date": (datetime.now() - timedelta(days=500)).strftime("%Y-%m-%d"), "token": token}, timeout=15).json()
        df = pd.DataFrame(res.get("data", []))
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)
        
        if is_market_open() or sid == "TAIEX":
            yt = yf.download(get_yf_ticker(sid), period="2d", interval="1m", progress=False)
            if not yt.empty:
                last_p = float(yt['Close'].iloc[-1])
                today_yt = yt[yt.index >= get_taiwan_time().replace(hour=9, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S')]
                if not today_yt.empty:
                    d_vol, d_high, d_low = int(today_yt['Volume'].sum()), float(today_yt['High'].max()), float(today_yt['Low'].min())
                    if df.iloc[-1]['date'].date() != get_taiwan_time().date():
                        df = pd.concat([df, pd.DataFrame([df.iloc[-1]])], ignore_index=True)
                        df.at[df.index[-1], 'date'] = pd.Timestamp(get_taiwan_time().date())
                    idx = df.index[-1]
                    df.at[idx, 'close'], df.at[idx, 'high'], df.at[idx, 'low'], df.at[idx, 'volume'] = last_p, d_high, d_low, d_vol
                    df.at[idx, 'est_volume'] = calculate_est_volume(d_vol)
        if 'est_volume' not in df.columns: df['est_volume'] = df['volume']
        return df
    except: return None

def analyze_strategy(df, is_market=False):
    if df is None or len(df) < 180: return None
    for m in [5, 10, 20, 55, 60, 144, 200]: df[f"ma{m}"] = df["close"].rolling(m).mean()
    
    # MACD
    e1, e2 = df['close'].ewm(span=12).mean(), df['close'].ewm(span=26).mean()
    df['macd'] = e1 - e2
    df['signal_line'] = df['macd'].ewm(span=9).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 乖離與量比
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["est_volume"] / df["vol_ma5"].replace(0, np.nan)
    
    last_idx, row, prev = df.index[-1], df.iloc[-1], df.iloc[-2]
    
    # 形態判定
    ma_list = [row["ma5"], row["ma10"], row["ma20"]]
    dist = (max(ma_list) - min(ma_list)) / row["close"]
    market_phase = "📈上漲盤" if row["ma5"] > row["ma10"] > row["ma20"] else ("📉下跌盤" if row["ma5"] < row["ma10"] < row["ma20"] else "🍽️盤整盤")
    
    # 海海噴發判定
    is_boom = (dist < 0.03 and row["close"] > max(ma_list) and row["vol_ratio"] > 1.2 and row["ma5"] > prev["ma5"])
    
    pattern = "🚀 噴發第一根" if is_boom else ("💎 鑽石眼" if dist < 0.02 and row["close"] > row["ma5"] else market_phase)
    
    # 評分與訊號
    score = 50 + (20 if is_boom else 0) + (10 if row["vol_ratio"] > 1.5 else 0) + (10 if row["close"] > row["ma144"] else 0)
    df.at[last_idx, "score"], df.at[last_idx, "pattern"], df.at[last_idx, "sig_type"] = min(score, 100), pattern, ("BUY" if is_boom or score > 70 else "HOLD")
    df.at[last_idx, "warning"] = "量增突破" if is_boom else "趨勢觀察"
    df.at[last_idx, "pos_advice"] = "建議配置: 10-15%" if score > 70 else "建議配置: 5%"
    df.at[last_idx, "pattern_desc"] = "符合海海策略噴發型態" if is_boom else "均線整理中"
    df.at[last_idx, "bias_5"] = ((row["close"] - row["ma5"]) / row["ma5"]) * 100
    
    return df

# --- 6. 繪圖與同步 ---
def plot_advanced_chart(df, title=""):
    d = df.tail(100)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    fig.add_trace(go.Candlestick(x=d["date"], open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="K線"), row=1, col=1)
    for m, c in zip([5, 20, 60, 144], ['#2980b9', '#e67e22', '#9b59b6', '#34495e']):
        fig.add_trace(go.Scatter(x=d["date"], y=d[f"ma{m}"], name=f"{m}MA", line=dict(color=c, width=1.5)), row=1, col=1)
    fig.add_trace(go.Bar(x=d["date"], y=d["hist"], name="MACD", marker_color=['#ff4b4b' if v >= 0 else '#28a745' for v in d["hist"]]), row=2, col=1)
    fig.update_layout(height=600, title=title, template="plotly_white", xaxis_rangeslider_visible=False)
    return fig

def sync_sheets():
    sid = st.secrets.get("MONITOR_SHEET_ID")
    if not sid: return
    try:
        df = pd.read_csv(f"https://docs.google.com/spreadsheets/d/{sid}/export?format=csv")
        st.session_state.search_codes = " ".join(df['snipe_list'].dropna().astype(str).apply(lambda x: x.split('.')[0]))
        st.session_state.inventory_codes = " ".join(df['inventory_list'].dropna().astype(str).apply(lambda x: x.split('.')[0]))
        add_log("SYS", "SHEETS", "INFO", "雲端清單同步成功")
    except: st.error("同步失敗")

# --- 7. 主程式 UI 邏輯 ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    st.session_state.enable_discord = st.toggle("📢 Discord 推送", value=st.session_state.enable_discord)
    
    st.divider()
    st.subheader("🤖 AI 自動選股")
    if st.button("🌟 執行海海策略全市場掃描", use_container_width=True):
        if not fm_token: st.error("請輸入 Token")
        else:
            with st.status("海海分析師掃描中...") as s:
                hits = run_haihai_auto_scan(fm_token)
                if hits:
                    st.session_state.search_codes = " ".join(hits)
                    s.update(label=f"✅ 發現 {len(hits)} 檔黑馬", state="complete")
                    st.rerun()
                else: s.update(label="查無符合標的", state="error")
    
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    analyze_btn = st.button("🚀 立即手動掃描", use_container_width=True)

def perform_scan(manual=False):
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    # 大盤
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df, is_market=True)
        st.metric("加權指數", f"{m_df.iloc[-1]['close']:.2f}", f"{m_df.iloc[-1]['close']-m_df.iloc[-2]['close']:.2f}")
    
    # 個股
    processed = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(get_stock_data, sid, fm_token): sid for sid in all_codes}
        for f in futures:
            sid = futures[f]
            df = f.result()
            if df is not None:
                df = analyze_strategy(df)
                last = df.iloc[-1]
                processed.append({"sid": sid, "df": df, "last": last, "is_snipe": sid in snipe_list})
                
                # Discord 推送 (簡化判定)
                if manual and last['sig_type'] == "BUY":
                    send_discord_message(f"🏹 訊號觸發: {sid} | 評分: {last['score']} | 形態: {last['pattern']}")

    # 顯示
    for item in sorted(processed, key=lambda x: x['last']['score'], reverse=True):
        c = "#ff4b4b" if item['last']['sig_type'] == "BUY" else "#ccc"
        with st.container():
            st.markdown(f"<div class='dashboard-box' style='border-left:10px solid {c}; text-align:left; margin-bottom:10px;'>"
                        f"<b>{item['sid']} | 評分: {item['last']['score']} | {item['last']['pattern']}</b><br>"
                        f"提醒: {item['last']['warning']} | {item['last']['pos_advice']}</div>", unsafe_allow_html=True)
            with st.expander("查看圖表"): st.plotly_chart(plot_advanced_chart(item['df'], item['sid']))

if not st.session_state.first_sync_done:
    sync_sheets(); st.session_state.first_sync_done = True

if analyze_btn: perform_scan(manual=True)
elif is_market_open(): perform_scan(); time.sleep(300); st.rerun()
else: st.info("目前非開盤時間")