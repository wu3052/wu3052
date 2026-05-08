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

# =========================================================
# 系統設定與美化
# =========================================================
st.set_page_config(page_title="狙擊手 V2 - 60分K戰情室", layout="wide")

st.markdown("""
<style>
    .main { background-color: #0e1117; color: #fafafa; }
    .terminal-log {
        background-color: #000; color: #00ff00; padding: 10px;
        font-family: 'monospace'; border-radius: 5px;
        height: 200px; overflow-y: auto; font-size: 12px;
    }
    .signal-card {
        padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b;
        background: #1e2130; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 數據核心引擎
# =========================================================

def get_yf_symbol(code):
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

@st.cache_data(ttl=3600)
def get_all_codes():
    return [c for c, i in twstock.codes.items() if len(c) == 4 and i.type == "股票"]

def analyze_strategy(code, fm_token, min_vol):
    try:
        ticker = get_yf_symbol(code)
        
        # 1. 抓取日線數據 (分析主力潛伏)
        df_d = yf.download(ticker, period="8mo", interval="1d", progress=False, auto_adjust=True)
        if df_d.empty or len(df_d) < 144: return None
        
        # 2. 抓取 60 分鐘數據 (分析關鍵均線突破)
        # 注意：yfinance 的 60m 數據最多提供最近 730 天
        df_60m = yf.download(ticker, period="1mo", interval="60m", progress=False, auto_adjust=True)
        if df_60m.empty or len(df_60m) < 144: return None

        # 修正 MultiIndex
        for df in [df_d, df_60m]:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.columns = [str(c).lower() for c in df.columns]

        # 基礎過濾：成交量
        avg_vol_d = df_d['volume'].tail(5).mean()
        if avg_vol_d < (min_vol * 1000): return None

        score = 50
        signals = []

        # --- [60分鐘圖分析] 即時上穿偵測 ---
        df_60m["ma55"] = df_60m["close"].rolling(55).mean()
        df_60m["ma144"] = df_60m["close"].rolling(144).mean()
        
        c_60 = df_60m["close"].iloc[-1]
        p_60 = df_60m["close"].iloc[-2]
        ma55_60 = df_60m["ma55"].iloc[-1]
        ma144_60 = df_60m["ma144"].iloc[-1]

        # 偵測：即時上穿或在 1% 準備突破
        if p_60 < ma144_60 and c_60 >= ma144_60:
            score += 30
            signals.append("🔥 60K 突破 144MA")
        elif 0 < (ma144_60 - c_60) / ma144_60 < 0.01:
            score += 15
            signals.append("⏳ 60K 即將挑戰 144MA")

        if p_60 < ma55_60 and c_60 >= ma55_60:
            score += 20
            signals.append("🚀 60K 突破 55MA")

        # --- [日線分析] 主力與動能 ---
        df_d["ma20"] = df_d["close"].rolling(20).mean()
        df_d["vol_ma20"] = df_d["volume"].rolling(20).mean()
        
        row_d = df_d.iloc[-1]
        prev_d = df_d.iloc[-2]

        # 主力潛伏：量縮洗盤
        if row_d["close"] > row_d["ma20"] and row_d["volume"] < row_d["vol_ma20"] * 0.7:
            score += 15
            signals.append("💎 日線窒息量")

        # 法人籌碼
        if fm_token:
            try:
                res = requests.get("https://api.finmindtrade.com/api/v4/data", params={
                    "dataset": "InstitutionalInvestorsBuySell", "data_id": code,
                    "start_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "token": fm_token
                }, timeout=3).json()
                if sum([x['buy_sell'] for x in res.get("data", [])]) > 0:
                    score += 10
                    signals.append("🏦 法人挺進")
            except: pass

        return {
            "code": code,
            "name": twstock.codes[code].name,
            "score": score,
            "close": round(float(c_60), 2),
            "signals": " | ".join(signals),
            "vol_ratio": round(row_d["volume"] / row_d["vol_ma20"], 2)
        }
    except: return None

# =========================================================
# UI 與主程式
# =========================================================

st.title("🏹 股票狙擊手 V2 - 60分K跨週期監控")

with st.sidebar:
    st.header("⚙️ 狙擊參數")
    fm_token = st.text_input("FinMind Token", type="password")
    min_vol = st.slider("日均量門檻 (張)", 100, 2000, 500)
    target_score = st.slider("綜合評分門檻", 50, 95, 75)
    threads = st.slider("掃描線程", 5, 20, 10)
    
    st.divider()
    run_all = st.button("🚀 開啟全市場 60K 地圖炮")

log_box = st.empty()
if 'logs' not in st.session_state: st.session_state.logs = []

def logger(msg):
    st.session_state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(st.session_state.logs) > 8: st.session_state.logs.pop(0)
    log_box.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.logs)}</div>', unsafe_allow_html=True)

if run_all:
    codes = get_all_codes()
    logger(f"全台股地圖炮啟動... 預計掃描 {len(codes)} 檔")
    
    results = []
    progress = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_map = {executor.submit(analyze_strategy, c, fm_token, min_vol): c for c in codes}
        
        for i, future in enumerate(as_completed(future_map)):
            res = future.result()
            if res and res['score'] >= target_score:
                results.append(res)
                logger(f"🎯 發現強勢訊號：{res['code']} {res['name']} ({res['score']}分)")
            
            if i % 30 == 0:
                progress.progress((i + 1) / len(codes))

    st.divider()
    if results:
        df_res = pd.DataFrame(results).sort_values("score", ascending=False)
        st.subheader(f"📊 今日狙擊清單 (符合條件: {len(df_res)} 檔)")
        st.dataframe(df_res, use_container_width=True)
        
        # 顯示前三名詳細數據
        cols = st.columns(3)
        for idx, row in df_res.head(3).iterrows():
            with cols[idx]:
                st.markdown(f"""
                <div class="signal-card">
                    <h4>{row['code']} {row['name']}</h4>
                    <h2 style='color:#ff4b4b'>{row['score']} 分</h2>
                    <p>當前價: {row['close']}</p>
                    <p style='font-size: 12px;'>{row['signals']}</p>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.error("掃描完成，目前市場無標的符合 60K 關鍵均線突破或即將挑戰的門檻。")
