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
# 基本設定
# =========================================================
st.set_page_config(page_title="狙擊手 V2 - 修復版", layout="wide")

# 介面美化
st.markdown("""
<style>
    .terminal-log {
        background-color: #000; color: #00ff00; padding: 10px;
        font-family: 'monospace'; border-radius: 5px;
        height: 200px; overflow-y: auto; font-size: 12px;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 工具函數
# =========================================================

def get_yf_symbol(code):
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

@st.cache_data(ttl=3600)
def get_all_codes():
    return [c for c, i in twstock.codes.items() if len(c) == 4 and i.type == "股票"]

def analyze_logic(code, fm_token, min_vol):
    try:
        ticker = get_yf_symbol(code)
        # 抓取數據 (增加 retry 機制)
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        
        if df.empty: return ("SKIP", f"{code}: 抓不到資料")
        
        # --- 重要：修復 yfinance MultiIndex 問題 ---
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.columns = [str(c).lower() for c in df.columns]

        # 檢查成交量 (單位：股) -> 預設 50 張
        avg_vol = df['volume'].tail(5).mean()
        if avg_vol < (min_vol * 1000): 
            return ("SKIP", f"{code}: 成交量過低 ({int(avg_vol/1000)}張)")

        # --- 技術指標計算 ---
        df["ma5"] = df["close"].rolling(5).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["vol_ma20"] = df["volume"].rolling(20).mean()
        
        row = df.iloc[-1]
        prev = df.iloc[-2]
        
        score = 60  # 提高基礎分，避免門檻太高
        signals = []

        # 1. 主力吸籌偵測 (量增價穩)
        if (row["volume"] > row["vol_ma20"]) and (abs(row["close"] - prev["close"])/prev["close"] < 0.02):
            score += 15
            signals.append("💎 主力吸籌")

        # 2. 多頭位階
        if row["close"] > row["ma20"]:
            score += 10
            signals.append("📈 站上月線")

        # 3. 突破意圖
        if row["close"] >= df["high"].tail(10).max() * 0.98:
            score += 10
            signals.append("🚀 準備突破")

        # --- 籌碼面 (有 Token 才執行) ---
        if fm_token and score >= 65:
            try:
                url = "https://api.finmindtrade.com/api/v4/data"
                res = requests.get(url, params={
                    "dataset": "InstitutionalInvestorsBuySell",
                    "data_id": code,
                    "start_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "token": fm_token
                }, timeout=3).json()
                chip_data = pd.DataFrame(res.get("data", []))
                if not chip_data.empty and chip_data['buy_sell'].sum() > 0:
                    score += 10
                    signals.append("🏦 法人買超")
            except: pass

        return ("OK", {
            "code": code,
            "name": twstock.codes[code].name,
            "score": score,
            "close": round(float(row["close"]), 2),
            "vol_ratio": round(row["volume"] / row["vol_ma20"], 2),
            "signals": " | ".join(signals)
        })
    except Exception as e:
        return ("ERROR", f"{code}: {str(e)}")

# =========================================================
# UI 介面
# =========================================================

st.title("🏹 狙擊手 V2 全台股掃描器 (修復版)")

with st.sidebar:
    st.header("🔍 掃描設定")
    fm_token = st.text_input("FinMind Token (選填)", type="password")
    min_vol_input = st.slider("最低 5 日均量 (張)", 0, 500, 50)
    target_score = st.slider("顯示評分門檻", 50, 90, 70)
    threads = st.slider("掃描速度 (執行緒)", 1, 20, 10)
    
    st.divider()
    run_btn = st.button("🚀 開始全市場掃描")

log_box = st.empty()
if 'logs' not in st.session_state: st.session_state.logs = []

def logger(msg):
    st.session_state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(st.session_state.logs) > 10: st.session_state.logs.pop(0)
    log_box.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.logs)}</div>', unsafe_allow_html=True)

# =========================================================
# 執行邏輯
# =========================================================

if run_btn:
    all_codes = get_all_codes()
    logger(f"啟動！目標：全台 {len(all_codes)} 檔股票...")
    
    final_results = []
    progress = st.progress(0)
    
    # 多線程加速
    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_code = {executor.submit(analyze_logic, code, fm_token, min_vol_input): code for code in all_codes}
        
        for i, future in enumerate(as_completed(future_to_code)):
            status, data = future.result()
            
            if status == "OK" and data['score'] >= target_score:
                final_results.append(data)
                logger(f"🎯 命中標的：{data['code']} {data['name']} ({data['score']}分)")
            elif status == "ERROR":
                logger(f"⚠️ 錯誤：{data}")
            
            if i % 50 == 0:
                progress.progress((i + 1) / len(all_codes))

    logger("✅ 掃描任務完成！")
    
    if final_results:
        df_res = pd.DataFrame(final_results).sort_values("score", ascending=False)
        st.write(f"### 🏆 篩選結果 (共 {len(df_res)} 檔)")
        st.dataframe(df_res, use_container_width=True)
    else:
        st.error("❌ 依然找不到標的。建議：1. 調低評分門檻至 60。 2. 調低成交量張數。 3. 檢查網路是否連線。")
