import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time

# =========================================================
# 系統基礎設定
# =========================================================
st.set_page_config(
    page_title="股票狙擊手 Pro Max V2 - 主力潛伏版",
    layout="wide",
    page_icon="🏹"
)

# 終端機風格 CSS 強化版
st.markdown("""
<style>
    .main { background-color: #0e1117; color: #fafafa; }
    .stMetric { background-color: #1e2130; padding: 15px; border-radius: 10px; border: 1px solid #444; }
    .terminal-log {
        background-color: #000;
        color: #00ff00;
        padding: 15px;
        font-family: 'Courier New', monospace;
        border-radius: 5px;
        height: 150px;
        overflow-y: auto;
        border: 1px solid #333;
        margin-bottom: 20px;
    }
    .status-card {
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
        border-left: 5px solid #ff4b4b;
        background: #262730;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 數據獲取模組
# =========================================================

def get_yf_symbol(code):
    code = str(code)
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

@st.cache_data(ttl=3600)
def build_stock_pool():
    pool = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == "股票":
            pool.append(code)
    return sorted(pool)

def get_history_data(code):
    try:
        ticker = get_yf_symbol(code)
        df = yf.download(ticker, period="1y", interval="1d", progress=False, auto_adjust=True)
        if df.empty: return None
        df.columns = [str(c).lower() for c in df.columns]
        return df.dropna()
    except: return None

def get_finmind_chip(code, token):
    """
    偵測主力潛伏的核心：三大法人買賣超連續性
    """
    if not token: return None
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        params = {
            "dataset": "InstitutionalInvestorsBuySell",
            "data_id": code,
            "start_date": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
            "token": token
        }
        res = requests.get(url, params=params, timeout=10).json()
        df_chip = pd.DataFrame(res.get("data", []))
        
        if df_chip.empty: return None
        
        # 整理外資與投信數據
        pivot = df_chip.pivot(index='date', columns='name', values='buy_sell').fillna(0)
        
        # 計算最近 5 天外資與投信合計
        recent_5 = pivot.tail(5)
        total_buy = recent_5.sum().sum()
        
        # 判斷是否連續買進 (主力潛伏關鍵指標)
        is_cont_buy = (recent_5.sum(axis=1) > 0).sum() >= 3 # 5天內有3天以上是買超
        
        return {"total_5d": total_buy, "is_cont_buy": is_cont_buy}
    except: return None

# =========================================================
# 核心分析引擎 (主力潛伏邏輯強化)
# =========================================================

def analyze_stock_v2(df, chip_info=None):
    try:
        if len(df) < 60: return None
        
        # 指標計算
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
        df["vol_ma5"] = df["volume"].rolling(5).mean()
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        
        # 波動率 (VCP 邏輯)
        df["range"] = (df["high"] - df["low"]) / df["close"]
        df["vcp_tightness"] = df["range"].rolling(10).mean() < df["range"].rolling(40).mean() * 0.8
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 50 # 基礎分
        signals = []
        
        # 1. 主力潛伏判定 - 【量能換手】
        # 成交量是 20 天平均的 1.2~2 倍，但股價沒動 (跌幅或漲幅小於 1.5%)
        if (row["volume"] > row["vol_ma20"] * 1.2) and (abs(row["close"] - prev["close"])/prev["close"] < 0.015):
            score += 20
            signals.append("💎 主力換手潛伏")

        # 2. 籌碼判定 - 【法人偷偷買】
        if chip_info:
            if chip_info["is_cont_buy"]:
                score += 25
                signals.append("🏦 法人連續吸籌")
            if chip_info["total_5d"] > 0:
                score += 10
                signals.append("📈 籌碼趨於集中")

        # 3. VCP 緊縮判定
        if row["vcp_tightness"]:
            score += 15
            signals.append("🤐 波動高度壓縮")

        # 4. 噴發前兆 (均線糾結)
        ma_gap = max(row["ma5"], row["ma20"], row["ma60"]) / min(row["ma5"], row["ma20"], row["ma60"])
        if ma_gap < 1.03: # 均線距離在 3% 以內
            score += 15
            signals.append("🧬 均線糾結")

        # 5. 突破偵測 (噴發第一根)
        if row["close"] > df["high"].rolling(20).max().shift(1) and row["volume"] > row["vol_ma5"] * 1.5:
            score += 30
            signals.append("🚀 狙擊點：噴發第一根")

        # 綜合位階判定
        stage = "盤整中"
        if "狙擊點" in "".join(signals): stage = "發動突破"
        elif "潛伏" in "".join(signals) or "吸籌" in "".join(signals): stage = "主力潛伏"
        elif row["ma5"] > row["ma20"] > row["ma60"]: stage = "多頭趨勢"

        return {
            "score": score,
            "stage": stage,
            "signals": " | ".join(signals),
            "close": round(float(row["close"]), 2),
            "vol_ratio": round(row["volume"] / row["vol_ma20"], 2)
        }
    except: return None

# =========================================================
# Streamlit UI 介面
# =========================================================

st.title("🏹 股票狙擊手 Pro Max V2")
st.subheader("專注「主力潛伏」與「噴發第一根」偵測系統")

with st.sidebar:
    st.header("⚙️ 掃描參數")
    fm_token = st.text_input("FinMind Token", type="password", help="用於獲取三大法人籌碼數據")
    scan_count = st.number_input("掃描個股數量 (建議 100-300)", 20, 1000, 100)
    mode = st.selectbox("選股模式", ["全部掃描", "僅看主力潛伏", "僅看突破噴發"])
    start_btn = st.button("🔍 開始戰情掃描")

log_placeholder = st.empty()
if 'log_history' not in st.session_state: st.session_state.log_history = []

def add_log(msg):
    now = datetime.now().strftime("%H:%M:%S")
    st.session_state.log_history.append(f"[{now}] {msg}")
    if len(st.session_state.log_history) > 5: st.session_state.log_history.pop(0)
    log_placeholder.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.log_history)}</div>', unsafe_allow_html=True)

# =========================================================
# 執行掃描
# =========================================================

if start_btn:
    add_log("系統初始化... 讀取台股代碼池...")
    full_pool = build_stock_pool()
    target_pool = full_pool[:scan_count]
    
    results = []
    progress_bar = st.progress(0)
    
    for i, code in enumerate(target_pool):
        progress_bar.progress((i + 1) / len(target_pool))
        
        # 抓取數據
        df = get_history_data(code)
        if df is None: continue
        
        # 只有評分潛力高的才去抓 FinMind 節省 API (或根據需求調整)
        chip = None
        if fm_token:
            chip = get_finmind_chip(code, fm_token)
            time.sleep(0.1) # 簡單頻率限制
            
        analysis = analyze_stock_v2(df, chip)
        
        if analysis:
            # 模式過濾
            if mode == "僅看主力潛伏" and analysis["stage"] != "主力潛伏": continue
            if mode == "僅看突破噴發" and analysis["stage"] != "發動突破": continue
            if analysis["score"] < 60: continue # 過濾弱勢股
            
            info = twstock.codes.get(code)
            analysis["code"] = code
            analysis["name"] = info.name if info else "Unknown"
            results.append(analysis)
            add_log(f"發現目標：{code} {analysis['name']} (評分: {analysis['score']})")

    # 顯示結果
    if results:
        res_df = pd.DataFrame(results).sort_values("score", ascending=False)
        
        # 分欄顯示數據
        st.write("### 🎯 掃描戰果報告")
        st.dataframe(res_df[["code", "name", "score", "stage", "close", "vol_ratio", "signals"]], use_container_width=True)
        
        st.divider()
        st.write("### 📈 重點標的 K 線分析")
        for _, row in res_df.head(5).iterrows():
            with st.expander(f"【{row['stage']}】 {row['code']} {row['name']} - 評分: {row['score']}"):
                df_plot = get_history_data(row["code"]).tail(100)
                
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
                fig.add_trace(go.Candlestick(x=df_plot.index, open=df_plot['open'], high=df_plot['high'], low=df_plot['low'], close=df_plot['close'], name="K線"), row=1, col=1)
                
                # 均線
                for m in [5, 20, 60]:
                    ma_line = df_plot['close'].rolling(m).mean()
                    fig.add_trace(go.Scatter(x=df_plot.index, y=ma_line, name=f"{m}MA", line=dict(width=1)), row=1, col=1)
                
                # 成交量
                fig.add_trace(go.Bar(x=df_plot.index, y=df_plot['volume'], name="成交量", marker_color='orange'), row=2, col=1)
                
                fig.update_layout(height=500, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.error("❌ 掃描範圍內未發現符合條件的標的，請嘗試增加掃描數量或更換模式。")

else:
    st.info("💡 請在左側輸入 FinMind Token 並按下『開始戰情掃描』。本系統將自動過濾出具備「大戶吸籌」與「噴發前兆」的台股標的。")
