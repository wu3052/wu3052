import streamlit as st
import twstock
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 頁面配置與進階 CSS (模仿影片風格) ---
st.set_page_config(layout="wide", page_title="AI 形態匹配與選股系統", page_icon="📈")

st.markdown("""
<style>
    /* 深色/科技感主題 */
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    
    /* 頂部 Tab 樣式 */
    .stTabs [data-baseweb="tab-list"] { gap: 10px; background-color: #161b22; padding: 10px; border-radius: 8px; }
    .stTabs [data-baseweb="tab"] { color: #8b949e; font-weight: bold; font-size: 1.05em; }
    .stTabs [aria-selected="true"] { color: #58a6ff !important; border-bottom: 2px solid #58a6ff; }
    
    /* 股票卡片風格 */
    .stock-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 15px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .stock-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #21262d;
        padding-bottom: 6px;
        margin-bottom: 8px;
    }
    .stock-title { font-size: 1.1em; font-weight: bold; color: #f0f6fc; }
    .stock-price-up { color: #ff7b72; font-weight: bold; font-size: 1.1em; }
    .stock-price-down { color: #3fb950; font-weight: bold; font-size: 1.1em; }
    
    /* 標籤樣式 */
    .tag-macd { background-color: #1f6beb; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
    .tag-vcp { background-color: #d29922; color: white; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 初始化 Session State ---
if 'sid_map' not in st.session_state: st.session_state.sid_map = {}
if 'search_results' not in st.session_state: st.session_state.search_results = []

# --- 3. 工具函數 ---
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

@st.cache_data(ttl=3600)
def get_stock_data(sid, token=""):
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
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        return None

# --- 4. 影片核心策略：MACD 0 軸回踩 & 25日線支撐 ---
def analyze_macd_pattern(df):
    if df is None or len(df) < 120: return None
    
    # 計算 25 日線 (影片提及之 25天線)
    df["ma25"] = df["close"].rolling(25).mean()
    df["ma5"] = df["close"].rolling(5).mean()
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    
    # 計算 MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['dif'] = exp1 - exp2
    df['dem'] = df['dif'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = (df['dif'] - df['dem']) * 2

    row = df.iloc[-1]
    prev = df.iloc[-2]
    prev_5 = df.iloc[-6:-1]

    # --- 影片條件比對 ---
    # 條件 1: 股價站在 25日線上方或回踩 25日線附近 (±2.5% 以內)
    c1_near_ma25 = abs(row["close"] - row["ma25"]) / row["ma25"] < 0.025 or row["close"] > row["ma25"]
    
    # 條件 2: DIF / MACD 近期曾上穿 0 軸且目前在 0 軸附近 (0 軸上方不遠或剛剛回踩 0 軸)
    c2_dif_near_zero = (abs(row["dif"]) < (row["close"] * 0.015)) or (row["dif"] > 0 and prev["dif"] < 0)
    
    # 條件 3: DIF 與 DEM 快慢線黏合 (距離極小)
    c3_lines_sticky = abs(row["dif"] - row["dem"]) < (row["close"] * 0.008)
    
    # 條件 4: 當日帶量陽線 (成交量高於5日均量且收紅K)
    c4_volume_up = (row["volume"] > row["vol_ma5"] * 1.2) and (row["close"] > row["open"])

    # 綜合條件分數判定
    matched = False
    match_score = 0
    if c1_near_ma25: match_score += 25
    if c2_dif_near_zero: match_score += 25
    if c3_lines_sticky: match_score += 25
    if c4_volume_up: match_score += 25

    if match_score >= 75:  # 滿足大部分條件即視為符合影片形態
        matched = True

    change_pct = ((row["close"] - prev["close"]) / prev["close"]) * 100

    return {
        "matched": matched,
        "score": match_score,
        "close": row["close"],
        "change_pct": change_pct,
        "vol_ratio": row["volume"] / row["vol_ma5"] if row["vol_ma5"] > 0 else 1,
        "df": df
    }

# --- 5. 繪製微型 K 線圖 (Plotly) ---
def plot_mini_chart(df, title_str):
    sub_df = df.tail(60).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])

    # K 線圖 + 25日線
    fig.add_trace(go.Candlestick(
        x=sub_df['date'], open=sub_df['open'], high=sub_df['high'],
        low=sub_df['low'], close=sub_df['close'], name="K線",
        increasing_line_color='#ff4d4d', decreasing_line_color='#00b060'
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=sub_df['date'], y=sub_df['ma25'], line=dict(color='#f1c40f', width=1.5), name="25MA"
    ), row=1, col=1)

    # MACD 柱狀圖
    colors = ['#ff4d4d' if h >= 0 else '#00b060' for h in sub_df['macd_hist']]
    fig.add_trace(go.Bar(
        x=sub_df['date'], y=sub_df['macd_hist'], marker_color=colors, name="MACD"
    ), row=2, col=1)

    fig.update_layout(
        title=dict(text=title_str, font=dict(size=14, color="#ffffff")),
        margin=dict(l=10, r=10, t=30, b=10),
        height=260,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        showlegend=False,
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=True, gridcolor='#21262d'),
        xaxis2=dict(showgrid=False, visible=False),
        yaxis2=dict(showgrid=False, visible=False)
    )
    return fig

# --- 6. 介面設計 ---
st.title("🏹 AI 形態配對與選股系統 (影片同款)")

# 頂部導航 Tab
tab1, tab2, tab3 = st.tabs(["📊 我的形態 (MACD0軸回踩)", "⭐ 自選股選股", "🔍 股票庫全掃描"])

with st.sidebar:
    st.header("⚙️ 參數設定")
    api_token = st.text_input("FinMind Token", value="", type="password")
    scan_limit = st.slider("掃描股票檔數上限", 10, 200, 50, step=10)
    st.markdown("---")
    st.info("💡 **策略說明**：匹配 25日線支撐 + MACD 突破 0 軸後回踩黏合，並於放量紅棒起漲時進行訊號提示。")

# --- TAB 1: 影片同款 形態搜尋 ---
with tab1:
    st.subheader("🎯 影片形態：MACD 上穿/回踩 0 軸 + 25日線發動點")
    
    col_input, col_btn = st.columns([3, 1])
    with col_input:
        stock_list_str = st.text_area("輸入掃描股票代碼 (以逗號分隔)", "2330, 2317, 2454, 2308, 3037, 2379, 3231, 2382, 3035, 6669")
    with col_btn:
        st.write("")
        st.write("")
        start_scan = st.button("🚀 開始形態匹配", use_container_width=True)

    if start_scan:
        sids = [s.strip() for s in stock_list_str.replace("，", ",").split(",") if s.strip()]
        results = []
        
        progress_bar = st.progress(0)
        with ThreadPoolExecutor(max_workers=5) as executor:
            future_to_sid = {executor.submit(get_stock_data, sid, api_token): sid for sid in sids}
            completed = 0
            for future in as_completed(future_to_sid):
                sid = future_to_sid[future]
                df = future.result()
                if df is not None:
                    res = analyze_macd_pattern(df)
                    if res and res["matched"]:
                        results.append((sid, res))
                completed += 1
                progress_bar.progress(completed / len(sids))

        st.session_state.search_results = results
        st.success(f"掃描完成！共找到 {len(results)} 檔符合【25MA + MACD 0軸回踩】形態的股票。")

    # 顯示結果網格 (卡片化，類似影片展現風格)
    if st.session_state.search_results:
        st.markdown("### 📋 匹配結果卡片覽")
        cols_per_row = 3
        results = st.session_state.search_results
        
        for i in range(0, len(results), cols_per_row):
            cols = st.columns(cols_per_row)
            for j in range(cols_per_row):
                if i + j < len(results):
                    sid, res = results[i + j]
                    with cols[j]:
                        pct_class = "stock-price-up" if res["change_pct"] >= 0 else "stock-price-down"
                        st.markdown(f"""
                        <div class="stock-card">
                            <div class="stock-header">
                                <span class="stock-title">{sid}</span>
                                <span class="{pct_class}">{res['close']:.2f} ({res['change_pct']:+.2f}%)</span>
                            </div>
                            <div>
                                <span class="tag-macd">MACD 0軸近點</span>
                                <span class="tag-vcp">量比 {res['vol_ratio']:.2f}x</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        fig = plot_mini_chart(res["df"], f"{sid} 走勢圖")
                        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.write("📌 **自選股監控**：可以在此輸入您長期追蹤的清單進行策略點位計算。")

with tab3:
    st.write("🔍 **全數據庫掃描**：搭配多線程對全台股進行形態比對。")