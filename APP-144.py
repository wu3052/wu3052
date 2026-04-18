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

# --- 1. 配置與樣式 ---
st.set_page_config(layout="wide", page_title="強勢回檔狙擊手 V4", page_icon="🏹")

# --- 2. 修正後的自動選股邏輯 (解決 0 檔問題) ---
@st.cache_data(ttl=86400)
def get_all_taiwan_stock_codes():
    try:
        # 抓取上市櫃代碼
        df1 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=2")[0]
        list1 = [c.split('　')[0] for c in df1[0] if len(c.split('　')[0]) == 4]
        df2 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=4")[0]
        list2 = [c.split('　')[0] for c in df2[0] if len(c.split('　')[0]) == 4]
        return list1 + list2
    except: return ["2330", "2317", "2454", "3131", "6830", "1513", "1519"]

def run_auto_scan_strategy():
    all_codes = get_all_taiwan_stock_codes()
    hits = []
    p_bar = st.progress(0, text="🔍 正在逐一掃描全市場 (確保不漏接)...")
    
    # 這裡縮小範圍先測試前 300 檔，或直接全掃 (建議全掃時增加 time.sleep)
    # 為了避免 0 檔，我們改用單筆快速獲取，穩定性最高
    total = len(all_codes)
    
    # 建立一個顯示區給用戶看進度
    status_msg = st.empty()
    
    for i, sid in enumerate(all_codes):
        if i % 50 == 0:
            p_bar.progress(i / total)
            status_msg.write(f"目前檢查到: {sid}")
            
        try:
            # 確保獲取足夠長度的數據計算 200MA (40週)
            ticker = f"{sid}.TW" if int(sid) < 8000 else f"{sid}.TWO" # 簡單初步分類
            df = yf.download(ticker, period="300d", interval="1d", progress=False, show_errors=False)
            
            if df.empty or len(df) < 200:
                # 換另一個市場試試
                ticker = f"{sid}.TWO" if ".TW" in ticker else f"{sid}.TW"
                df = yf.download(ticker, period="300d", interval="1d", progress=False, show_errors=False)
                if df.empty: continue

            c = df['Close']
            # 計算均線 (使用 numpy 轉換確保維度正確)
            close_vals = c.values.flatten()
            m5 = pd.Series(close_vals).rolling(5).mean().iloc[-1]
            m10 = pd.Series(close_vals).rolling(10).mean().iloc[-1]
            m20 = pd.Series(close_vals).rolling(20).mean().iloc[-1]
            m200 = pd.Series(close_vals).rolling(200).mean().iloc[-1]
            last_p = close_vals[-1]
            
            # --- 嚴格執行你的三大指令 ---
            # 1. 股價 > 20MA
            # 2. 股價 > 200MA (40週)
            # 3. 5MA < 10MA (短線回檔)
            if last_p > m20 and last_p > m200 and m5 < m10:
                hits.append(sid)
                add_log(sid, "掃描命中", "BUY", "符合回檔策略")
        except:
            continue
            
    p_bar.progress(1.0)
    status_msg.empty()
    return hits

# --- 3. 繪圖 (加入 120 天觀測期與盤整區概念) ---
def plot_chart(df, title):
    # 鎖定 120 天 K 線圖
    d = df.tail(120) 
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    
    # K線
    fig.add_trace(go.Candlestick(x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"], name="K線"), row=1, col=1)
    
    # 均線
    for m, c in [(5, '#1f77b4'), (10, '#ff7f0e'), (20, '#2ca02c'), (200, '#d62728')]:
        ma_line = d["Close"].rolling(m).mean()
        fig.add_trace(go.Scatter(x=d.index, y=ma_line, name=f"{m}MA", line=dict(color=c, width=1.5)), row=1, col=1)
    
    # 成交量
    fig.add_trace(go.Bar(x=d.index, y=d["Volume"], name="成交量", marker_color="#bdc3c7"), row=2, col=1)
    
    fig.update_layout(height=600, title=title, template="plotly_white", xaxis_rangeslider_visible=False)
    return fig

# --- (其餘 Session State 與 UI 邏輯保持不變) ---
# ... (此處省略部分重複的 UI 代碼，請沿用上一版框架) ...
