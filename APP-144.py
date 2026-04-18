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
st.set_page_config(layout="wide", page_title="強勢回檔狙擊手 V3", page_icon="🏹")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; font-size: 1.2em; text-align: center; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .neutral-signal { background-color: #6c757d; color: white; border-left: 8px solid #343a40; }
    .dashboard-box { background: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #e0e0e0; text-align: left; margin-bottom: 10px; transition: 0.3s; }
    .log-container { 
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
        color: #e2e8f0; padding: 20px; border-radius: 12px; height: 350px; overflow-y: scroll; border: 1px solid #334155;
    }
    .log-entry { border-bottom: 1px solid #334155; padding: 8px 0; font-size: 0.85em; }
    .log-time { color: #38bdf8; font-weight: bold; margin-right: 10px; }
    .log-tag { padding: 2px 6px; border-radius: 4px; font-size: 0.75em; margin-right: 5px; font-weight: bold; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #64748b; color: white; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
if 'event_log' not in st.session_state: st.session_state.event_log = []
if 'search_codes' not in st.session_state: st.session_state.search_codes = ""
if 'inventory_codes' not in st.session_state: st.session_state.inventory_codes = ""
if 'market_score' not in st.session_state: st.session_state.market_score = 50

# --- 3. 核心工具 ---
def get_taiwan_time(): return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start, end = datetime.strptime("09:00", "%H:%M").time(), datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start <= now.time() <= end

def get_yf_ticker(sid):
    if sid == "TAIEX": return "^TWII"
    return f"{sid}.TW" if len(sid) == 4 else f"{sid}.TWO"

def add_log(sid, name, tag_type, msg):
    ts = get_taiwan_time().strftime("%H:%M:%S")
    tag_class = "tag-buy" if tag_type == "BUY" else ("tag-sell" if tag_type == "SELL" else "tag-info")
    log_html = f"<div class='log-entry'><span class='log-time'>[{ts}]</span> <span class='log-tag {tag_class}'>{tag_type}</span> <b>{sid} {name}</b> -> {msg}</div>"
    st.session_state.event_log.insert(0, log_html)

# --- 4. 自動選股邏輯 (20MA+40W+回檔) ---
@st.cache_data(ttl=86400)
def get_all_taiwan_stock_codes():
    try:
        # 抓取上市櫃代碼
        df1 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=2")[0]
        list1 = [c.split('　')[0] for c in df1[0] if len(c.split('　')[0]) == 4]
        df2 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=4")[0]
        list2 = [c.split('　')[0] for c in df2[0] if len(c.split('　')[0]) == 4]
        return list1 + list2
    except: return ["2330", "2317", "2454", "3131", "6830"]

def run_auto_scan_strategy():
    all_codes = get_all_taiwan_stock_codes()
    batch_size = 150
    hits = []
    p_bar = st.progress(0, text="🔍 全市場回檔標的掃描中...")
    
    # 使用 yfinance 批次下載加速
    for i in range(0, len(all_codes), batch_size):
        batch = all_codes[i:i+batch_size]
        tickers = [f"{c}.TW" for c in batch] + [f"{c}.TWO" for c in batch]
        data = yf.download(tickers, period="300d", interval="1d", group_by='ticker', threads=True, progress=False)
        
        for sid in batch:
            try:
                # 判斷是在 TW 還是 TWO
                df = data[f"{sid}.TW"].dropna() if not data[f"{sid}.TW"].dropna().empty else data[f"{sid}.TWO"].dropna()
                if len(df) < 200: continue
                
                c = df['Close']
                m5, m10, m20, m200 = c.rolling(5).mean().iloc[-1], c.rolling(10).mean().iloc[-1], c.rolling(20).mean().iloc[-1], c.rolling(200).mean().iloc[-1]
                last_p = c.iloc[-1]
                
                # 指令邏輯：1.價>20MA 2.價>200MA(40週) 3.5MA<10MA
                if last_p > m20 and last_p > m200 and m5 < m10:
                    hits.append(sid)
            except: continue
        p_bar.progress(min((i + batch_size) / len(all_codes), 1.0))
    return hits

# --- 5. 數據分析與繪圖 ---
@st.cache_data(ttl=60)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockPrice", "data_id": sid, "start_date": (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d"), "token": token}, timeout=10).json()
        df = pd.DataFrame(res.get("data", []))
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        
        # 盤中即時數據更新
        if is_market_open() or sid == "TAIEX":
            yt = yf.download(get_yf_ticker(sid), period="1d", interval="1m", progress=False)
            if not yt.empty:
                last_p = float(yt['Close'].iloc[-1])
                if df.iloc[-1]['date'].date() != get_taiwan_time().date():
                    new_row = df.iloc[-1].copy()
                    new_row['date'] = pd.Timestamp(get_taiwan_time().date())
                    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                df.at[df.index[-1], 'close'] = last_p
        
        # 計算均線
        for m in [5, 10, 20, 60, 200]: df[f"ma{m}"] = df["close"].rolling(m).mean()
        return df
    except: return None

def plot_chart(df, title):
    d = df.tail(80)
    fig = make_subplots(rows=1, cols=1)
    fig.add_trace(go.Candlestick(x=d["date"], open=d["open"], high=d["high"], low=d["low"], close=d["close"], name="K線"))
    colors = {'ma5': '#1f77b4', 'ma10': '#ff7f0e', 'ma20': '#2ca02c', 'ma200': '#d62728'}
    for ma, clr in colors.items():
        fig.add_trace(go.Scatter(x=d["date"], y=d[ma], name=ma.upper(), line=dict(color=clr, width=1.5)))
    fig.update_layout(height=450, title=title, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=40, b=10))
    return fig

# --- 6. UI 配置 ---
with st.sidebar:
    st.header("🏹 狙擊指揮中心")
    fm_token = st.text_input("FinMind Token", value=st.secrets.get("FINMIND_TOKEN", ""), type="password")
    
    st.divider()
    st.subheader("🤖 自動選股器")
    st.info("條件：價 > 20MA & 40週線，且 5MA < 10MA (回檔中)")
    if st.button("🌟 執行全市場回檔掃描", use_container_width=True):
        with st.status("掃描中...") as s:
            hits = run_auto_scan_strategy()
            st.session_state.search_codes = " ".join(hits)
            s.update(label=f"✅ 完成！發現 {len(hits)} 檔標的", state="complete")
            st.rerun()

    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.search_codes)
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.inventory_codes)
    scan_btn = st.button("🚀 開始分析清單標的", use_container_width=True)

# --- 7. 執行分析 ---
def run_analysis():
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    
    if not all_codes:
        st.warning("請先執行掃描或在清單中輸入代碼。")
        return

    # 1. 大盤分析
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        last = m_df.iloc[-1]
        change = last['close'] - m_df.iloc[-2]['close']
        c1, c2 = st.columns([1, 2])
        c1.metric("加權指數", f"{last['close']:.2f}", f"{change:.2f}")
        status_text = "📈 多頭環境" if last['close'] > last['ma20'] else "📉 謹慎操作"
        c2.markdown(f"<div class='status-card neutral-signal'>{status_text} | 站穩 20MA 以上為佳</div>", unsafe_allow_html=True)

    # 2. 個股分析顯示
    st.subheader("🔥 標的深度監控")
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        
        last = df.iloc[-1]
        # 再次確認符合回檔條件 (黃色標示)
        is_retrace = last['ma5'] < last['ma10'] and last['close'] > last['ma20']
        border_clr = "#ffcc00" if is_retrace else "#28a745"
        
        st.markdown(f"""
        <div class="dashboard-box" style="border-left: 10px solid {border_clr};">
            <div style="display:flex; justify-content:space-between; padding: 10px;">
                <b>🎯 {sid} | 現價: {last['close']:.2f}</b>
                <span style="color:{border_clr}; font-weight:bold;">{'⚠️ 強勢回檔中' if is_retrace else '✅ 趨勢穩定'}</span>
            </div>
            <div style="font-size:0.85em; padding: 0 10px 10px 10px;">
                5MA: {last['ma5']:.2f} | 10MA: {last['ma10']:.2f} | 20MA: {last['ma20']:.2f} | 200MA: {last['ma200']:.2f}
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} 分析圖表"):
            st.plotly_chart(plot_chart(df, f"{sid} 技術分析"), use_container_width=True)

    st.divider()
    st.write("### 📜 戰情即時日誌")
    st.markdown(f"<div class='log-container'>{''.join(st.session_state.event_log)}</div>", unsafe_allow_html=True)

if scan_btn:
    run_analysis()
elif is_market_open() and st.session_state.search_codes:
    run_analysis()
    time.sleep(300)
    st.rerun()
