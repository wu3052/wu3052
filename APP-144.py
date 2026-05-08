import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# =========================================================
# 系統基礎設定
# =========================================================
st.set_page_config(page_title="狙擊手 Pro Max V2 - 全市場地圖炮", layout="wide", page_icon="📡")

st.markdown("""
<style>
    .main { background-color: #0e1117; color: #fafafa; }
    .terminal-log {
        background-color: #000; color: #00ff00; padding: 10px;
        font-family: 'Courier New', monospace; border-radius: 5px;
        height: 250px; overflow-y: auto; border: 1px solid #333;
    }
    .stButton>button { width: 100%; border-radius: 20px; background-color: #ff4b4b; color: white; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 核心引擎功能
# =========================================================

def get_yf_symbol(code):
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

@st.cache_data(ttl=3600)
def get_all_taiwan_symbols():
    """獲取全台股清單"""
    codes = []
    for code, info in twstock.codes.items():
        if len(code) == 4 and info.type == "股票":
            codes.append(code)
    return sorted(codes)

def fetch_and_analyze(code, fm_token):
    """單股分析核心 (供多線程調用)"""
    try:
        ticker = get_yf_symbol(code)
        # 抓取較短時間進行快速初篩
        df = yf.download(ticker, period="8mo", interval="1d", progress=False, auto_adjust=True)
        if df.empty or len(df) < 60: return None
        
        df.columns = [str(c).lower() for c in df.columns]
        
        # 排除殭屍股 (5日均量小於 100 張)
        if df['volume'].tail(5).mean() < 100000: return None
        
        # --- 技術指標計算 ---
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 50
        signals = []
        
        # 技術面初篩邏輯
        # 1. 潛伏換手偵測
        is_churning = (row["volume"] > row["vol_ma20"] * 1.2) and (abs(row["close"] - prev["close"])/prev["close"] < 0.015)
        if is_churning: 
            score += 20
            signals.append("💎 主力換手")
            
        # 2. 均線多頭/糾結
        ma_gap = max(row["ma5"], row["ma20"], row["ma60"]) / min(row["ma5"], row["ma20"], row["ma60"])
        if ma_gap < 1.03: 
            score += 15
            signals.append("🧬 均線糾結")
            
        # 3. 突破偵測
        if row["close"] > df["high"].rolling(20).max().shift(1):
            score += 25
            signals.append("🚀 突破前高")

        # --- 第一階段過濾：技術分不到 65 分的不抓籌碼以節省時間/流量 ---
        if score < 65: return None

        # --- 第二階段：籌碼面 (FinMind) ---
        if fm_token:
            try:
                url = "https://api.finmindtrade.com/api/v4/data"
                params = {"dataset": "InstitutionalInvestorsBuySell", "data_id": code, 
                          "start_date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"), "token": fm_token}
                res = requests.get(url, params=params, timeout=5).json()
                chip_df = pd.DataFrame(res.get("data", []))
                if not chip_df.empty:
                    # 判斷近 3 日是否有法人買盤
                    recent_buy = chip_df.tail(6)['buy_sell'].sum()
                    if recent_buy > 0:
                        score += 15
                        signals.append("🏦 法人進駐")
            except: pass

        return {
            "code": code,
            "name": twstock.codes[code].name,
            "score": score,
            "signals": " | ".join(signals),
            "close": round(float(row["close"]), 2),
            "vol_ratio": round(row["volume"] / row["vol_ma20"], 2)
        }
    except: return None

# =========================================================
# UI 介面實作
# =========================================================

st.title("📡 股票狙擊手 V2：全台股即時掃描")
st.caption("自動掃描全台 1,700+ 標的，尋找主力潛伏與噴發前兆")

with st.sidebar:
    st.header("⚙️ 地圖炮設定")
    fm_token = st.text_input("FinMind Token", type="password")
    thread_count = st.slider("併發執行緒數量", 5, 20, 10, help="越高越快，但容易被 yfinance 封鎖")
    min_score = st.slider("最低顯示評分", 60, 90, 70)
    
    st.divider()
    start_all_scan = st.button("🔥 開啟全台股地圖炮 (約需 2-3 分鐘)")

# 戰情 log
log_container = st.empty()
if 'full_logs' not in st.session_state: st.session_state.full_logs = []

def write_log(msg):
    st.session_state.full_logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(st.session_state.full_logs) > 8: st.session_state.full_logs.pop(0)
    log_container.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.full_logs)}</div>', unsafe_allow_html=True)

# =========================================================
# 執行全市場掃描
# =========================================================

if start_all_scan:
    all_codes = get_all_taiwan_symbols()
    write_log(f"🚀 初始化完成，準備掃描全台 {len(all_codes)} 檔股票...")
    
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 使用 ThreadPoolExecutor 進行多線程掃描
    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = {executor.submit(fetch_and_analyze, code, fm_token): code for code in all_codes}
        
        for i, future in enumerate(as_completed(futures)):
            code = futures[future]
            try:
                data = future.result()
                if data and data['score'] >= min_score:
                    results.append(data)
                    write_log(f"🎯 發現強勢股: {data['code']} {data['name']} (評分: {data['score']})")
            except Exception as e:
                pass
            
            # 每掃 50 檔更新一次進度條，避免過度重新渲染
            if i % 20 == 0:
                progress = (i + 1) / len(all_codes)
                progress_bar.progress(progress)
                status_text.text(f"掃描進度: {i+1} / {len(all_codes)}")

    write_log("✅ 全市場掃描完成！")
    
    if results:
        res_df = pd.DataFrame(results).sort_values("score", ascending=False)
        
        st.write(f"### 🏆 全市場強勢選股清單 (共 {len(res_df)} 檔)")
        st.dataframe(res_df, use_container_width=True)
        
        # 視覺化看板
        st.divider()
        cols = st.columns(min(len(res_df), 3))
        for idx, row in res_df.head(6).iterrows():
            with cols[idx % 3]:
                st.metric(f"{row['code']} {row['name']}", f"{row['close']} TWD", f"{row['score']} 分")
                st.caption(f"訊號: {row['signals']}")
                
    else:
        st.warning("⚠️ 掃描完成，但沒有標的符合您的評分門檻。請調低「最低顯示評分」再試一次。")

else:
    st.info("💡 點擊左側按鈕開始掃描全台股。注意：全市場掃描極為耗費系統資源，建議在盤中或盤後數據更新後執行。")
