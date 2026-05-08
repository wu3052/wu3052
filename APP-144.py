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
st.set_page_config(page_title="狙擊手 Pro Max V2 - 完整版", layout="wide", page_icon="🎯")

st.markdown("""
<style>
    .main { background-color: #0e1117; color: #fafafa; }
    .terminal-log {
        background-color: #000; color: #00ff00; padding: 10px;
        font-family: 'Courier New', monospace; border-radius: 5px;
        height: 250px; overflow-y: auto; border: 1px solid #333; font-size: 13px;
    }
    .stMetric { background-color: #1e2130; padding: 15px; border-radius: 10px; border: 1px solid #444; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 核心運算引擎
# =========================================================

def get_yf_symbol(code):
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

def fix_yf_df(df):
    """修復 yfinance 最新版的 MultiIndex 問題"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    return df

def analyze_logic(code, fm_token, min_vol, check_60m):
    try:
        ticker = get_yf_symbol(code)
        # --- 第一階段：日線分析 (過濾量能與大趨勢) ---
        df_d = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        if df_d.empty or len(df_d) < 20: return None
        df_d = fix_yf_df(df_d)

        avg_vol = df_d['volume'].tail(5).mean()
        if avg_vol < (min_vol * 1000): return None

        score = 50
        signals = []
        
        # 日線基本指標
        ma20_d = df_d['close'].rolling(20).mean().iloc[-1]
        close_d = df_d['close'].iloc[-1]
        prev_close_d = df_d['close'].iloc[-2]
        
        if close_d > ma20_d:
            score += 10
            signals.append("日線站上月線")

        # --- 第二階段：60分鐘線狙擊 (55MA / 144MA) ---
        if check_60m:
            # 抓取最近 1 個月的 60m 數據
            df_60 = yf.download(ticker, period="1mo", interval="60m", progress=False, auto_adjust=True)
            if not df_60.empty and len(df_60) > 144:
                df_60 = fix_yf_df(df_60)
                df_60['ma55'] = df_60['close'].rolling(55).mean()
                df_60['ma144'] = df_60['close'].rolling(144).mean()
                
                c_60 = df_60['close'].iloc[-1]
                p_60 = df_60['close'].iloc[-2]
                ma55 = df_60['ma55'].iloc[-1]
                ma144 = df_60['ma144'].iloc[-1]
                p_ma55 = df_60['ma55'].iloc[-2]
                p_ma144 = df_60['ma144'].iloc[-2]

                # 判定上穿 (即將或已經上穿)
                cross_55 = (p_60 <= p_ma55 and c_60 > ma55) or (abs(c_60 - ma55)/ma55 < 0.005)
                cross_144 = (p_60 <= p_ma144 and c_60 > ma144) or (abs(c_60 - ma144)/ma144 < 0.005)

                if cross_55:
                    score += 30
                    signals.append("🔥 60M上穿55MA")
                if cross_144:
                    score += 35
                    signals.append("🚀 60M上穿144MA")

        # --- 第三階段：籌碼面 (FinMind) ---
        if fm_token and score >= 60:
            try:
                url = "https://api.finmindtrade.com/api/v4/data"
                res = requests.get(url, params={
                    "dataset": "InstitutionalInvestorsBuySell",
                    "data_id": code,
                    "start_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "token": fm_token
                }, timeout=3).json()
                chip = pd.DataFrame(res.get("data", []))
                if not chip.empty and chip['buy_sell'].sum() > 0:
                    score += 15
                    signals.append("🏦 法人連買")
            except: pass

        return {
            "code": code,
            "name": twstock.codes[code].name,
            "score": score,
            "close": round(float(close_d), 2),
            "signals": " | ".join(signals),
            "vol_ratio": round(df_d['volume'].iloc[-1] / df_d['volume'].rolling(20).mean().iloc[-1], 2)
        }
    except: return None

# =========================================================
# UI 介面
# =========================================================

st.title("🏹 股票狙擊手 Pro Max V2")
st.subheader("全台股掃描 + 60分鐘線關鍵均線狙擊")

with st.sidebar:
    st.header("⚙️ 狙擊參數設定")
    fm_token = st.text_input("FinMind Token", type="password")
    min_vol = st.slider("最低成交量 (張)", 100, 1000, 500)
    score_threshold = st.slider("顯示評分門檻", 50, 90, 70)
    check_60m = st.checkbox("開啟 60M 穿線偵測 (速度較慢)", value=True)
    threads = st.slider("掃描執行緒", 1, 20, 10)
    
    st.divider()
    scan_btn = st.button("🔥 開啟全市場地圖炮")

# 戰情日誌
log_box = st.empty()
if 'logs' not in st.session_state: st.session_state.logs = []

def write_log(msg):
    st.session_state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(st.session_state.logs) > 8: st.session_state.logs.pop(0)
    log_box.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.logs)}</div>', unsafe_allow_html=True)

# =========================================================
# 主程式執行
# =========================================================

if scan_btn:
    all_codes = [c for c, i in twstock.codes.items() if len(c) == 4 and i.type == "股票"]
    write_log(f"🚀 啟動全市場掃描，目標 {len(all_codes)} 檔標的...")
    
    results = []
    progress = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_code = {executor.submit(analyze_logic, code, fm_token, min_vol, check_60m): code for code in all_codes}
        
        for i, future in enumerate(as_completed(future_to_code)):
            res = future.result()
            if res and res['score'] >= score_threshold:
                results.append(res)
                write_log(f"🎯 命中標的：{res['code']} {res['name']} ({res['score']}分)")
            
            if i % 20 == 0:
                progress.progress((i + 1) / len(all_codes))

    write_log("✅ 掃描完成！")
    
    if results:
        df_res = pd.DataFrame(results).sort_values("score", ascending=False)
        st.write(f"### 🏆 狙擊精選清單 (共 {len(df_res)} 檔)")
        
        # 高亮顯示含有 60M 穿線訊號的股票
        def highlight_strong(s):
            return ['background-color: #4c1d1d' if '60M' in str(v) else '' for v in s]
        
        st.dataframe(df_res.style.apply(highlight_strong, subset=['signals']), use_container_width=True)
        
        # 視覺化看板
        st.divider()
        st.subheader("🔥 頂級狙擊目標 (Top 3)")
        cols = st.columns(3)
        for idx, row in df_res.head(3).iterrows():
            with cols[idx]:
                st.metric(f"{row['code']} {row['name']}", f"{row['close']} TWD", f"{row['score']}分")
                st.write(f"**關鍵訊號:**\n{row['signals']}")
    else:
        st.error("❌ 掃描完成，但沒有標的符合門檻。建議調低評分門檻或放寬成交量設定。")

else:
    st.info("請點擊左側按鈕開始掃描。本系統將執行日線篩選與 60 分鐘關鍵均線 (55MA/144MA) 的即時穿線分析。")
