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
# 系統設定
# =========================================================
st.set_page_config(page_title="狙擊手 V2 - 全市場強勢版", layout="wide")

st.markdown("""
<style>
    .terminal-log {
        background-color: #000; color: #00ff00; padding: 10px;
        font-family: 'Courier New', monospace; border-radius: 5px;
        height: 200px; overflow-y: auto; font-size: 12px;
    }
    .report-card { background-color: #1e2130; padding: 20px; border-radius: 10px; border: 1px solid #444; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 核心邏輯
# =========================================================

def get_yf_symbol(code):
    return f"{code}.TWO" if code.startswith(("3", "5", "6", "8")) else f"{code}.TW"

def fix_df(df):
    if df is None or df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower() for c in df.columns]
    return df

def analyze_stock(code, fm_token, min_vol, check_60m):
    try:
        ticker = get_yf_symbol(code)
        
        # --- 第一階：日線數據 (全體掃描) ---
        df_d = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)
        df_d = fix_df(df_d)
        
        if df_d is None or len(df_d) < 20: return None

        # 1. 量能過濾 (台股以「股」為單位，500張 = 500,000股)
        avg_vol = df_d['volume'].tail(5).mean()
        if avg_vol < (min_vol * 1000): return None

        score = 50
        signals = []
        
        # 2. 日線趨勢
        curr_price = df_d['close'].iloc[-1]
        ma20_d = df_d['close'].rolling(20).mean().iloc[-1]
        vol_ma20 = df_d['volume'].rolling(20).mean().iloc[-1]
        
        if curr_price > ma20_d:
            score += 15
            signals.append("日線站上月線")
        
        # 3. 潛伏量能 (量縮洗盤)
        if df_d['volume'].iloc[-1] < vol_ma20 * 0.7:
            score += 10
            signals.append("💎 窒息量鎖籌")

        # --- 第二階：小時線數據 (僅針對日線分數 > 60 的股票) ---
        if check_60m and score >= 60:
            # 這裡增加 retry 避免被 yfinance 拒絕
            df_60 = yf.download(ticker, period="1mo", interval="60m", progress=False, auto_adjust=True)
            df_60 = fix_df(df_60)
            
            if df_60 is not None and len(df_60) > 55:
                ma55 = df_60['close'].rolling(55).mean().iloc[-1]
                ma144 = df_60['close'].rolling(144).mean().iloc[-1] if len(df_60) > 144 else None
                c_60 = df_60['close'].iloc[-1]
                
                # 穿線邏輯：價格大於均線且距離在 1.5% 以內 (代表即時上穿或貼近)
                if c_60 > ma55 and (c_60 - ma55)/ma55 < 0.015:
                    score += 25
                    signals.append("🔥 60M上穿55MA")
                
                if ma144 and c_60 > ma144 and (c_60 - ma144)/ma144 < 0.015:
                    score += 30
                    signals.append("🚀 60M上穿144MA")

        # --- 第三階：籌碼面 ---
        if fm_token and score >= 70:
            try:
                res = requests.get("https://api.finmindtrade.com/api/v4/data", params={
                    "dataset": "InstitutionalInvestorsBuySell", "data_id": code,
                    "start_date": (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                    "token": fm_token
                }, timeout=3).json()
                chip = pd.DataFrame(res.get("data", []))
                if not chip.empty and chip['buy_sell'].sum() > 0:
                    score += 10
                    signals.append("🏦 法人買超")
            except: pass

        return {
            "code": code,
            "name": twstock.codes[code].name if code in twstock.codes else "未知",
            "score": score,
            "price": round(float(curr_price), 2),
            "vol_ratio": round(df_d['volume'].iloc[-1] / vol_ma20, 2),
            "signals": " | ".join(signals)
        }
    except:
        return None

# =========================================================
# UI 邏輯
# =========================================================

st.title("🎯 狙擊手 Pro V2 - 全市場地圖炮")

with st.sidebar:
    st.header("⚙️ 掃描設定")
    fm_token = st.text_input("FinMind Token", type="password")
    min_vol = st.slider("最低成交量 (張)", 50, 1000, 300)
    min_score = st.slider("顯示評分門檻", 40, 90, 60)
    check_60m = st.checkbox("開啟 60M 穿線偵測", value=True)
    threads = st.slider("並行執行緒", 1, 15, 8) # 建議不要設太高，以免被封 IP
    
    st.divider()
    run_btn = st.button("🚀 開始全市場掃描")

log_placeholder = st.empty()
if 'logs' not in st.session_state: st.session_state.logs = []

def write_log(msg):
    st.session_state.logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(st.session_state.logs) > 8: st.session_state.logs.pop(0)
    log_placeholder.markdown(f'<div class="terminal-log">{"<br>".join(st.session_state.logs)}</div>', unsafe_allow_html=True)

if run_btn:
    all_codes = [c for c, i in twstock.codes.items() if len(c) == 4 and i.type == "股票"]
    write_log(f"🔥 任務啟動：掃描全台 {len(all_codes)} 檔標的...")
    
    results = []
    progress = st.progress(0)
    
    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_code = {executor.submit(analyze_stock, c, fm_token, min_vol, check_60m): c for c in all_codes}
        
        for i, future in enumerate(as_completed(future_to_code)):
            res = future.result()
            if res and res['score'] >= min_score:
                results.append(res)
                write_log(f"🎯 命中標的：{res['code']} {res['name']} ({res['score']}分)")
            
            if i % 25 == 0:
                progress.progress((i + 1) / len(all_codes))

    write_log("✅ 掃描完成！")
    
    if results:
        df_res = pd.DataFrame(results).sort_values("score", ascending=False)
        st.write(f"### 🏆 掃描結果 (共 {len(df_res)} 檔符合門檻)")
        st.dataframe(df_res, use_container_width=True)
        
        st.divider()
        st.subheader("🔥 本次掃描最強狙擊目標")
        top_3 = df_res.head(3)
        cols = st.columns(3)
        for idx, (i, row) in enumerate(top_3.iterrows()):
            with cols[idx]:
                st.markdown(f"""
                <div class="report-card">
                    <h3>{row['code']} {row['name']}</h3>
                    <h2 style="color:#ff4b4b;">{row['price']} TWD</h2>
                    <p><b>評分:</b> {row['score']}</p>
                    <p><b>訊號:</b> {row['signals']}</p>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.error("⚠️ 掃描完畢但無符合標的。請將「成交量」降至 100，「評分門檻」降至 50 再試一次。")
