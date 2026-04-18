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

# --- 1. 頁面配置與進階 CSS ---
st.set_page_config(layout="wide", page_title="台股回檔狙擊手 Pro Max", page_icon="🏹")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .status-card { padding: 15px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; text-align: center; border: 1px solid #ddd; }
    .hit-card { background-color: #fff; border-left: 8px solid #ffcc00; padding: 15px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .log-container { 
        background: #1e293b; color: #e2e8f0; padding: 15px; border-radius: 10px; height: 300px; overflow-y: auto; font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)

# --- 2. 核心邏輯函數 ---
def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

@st.cache_data(ttl=86400)
def get_all_taiwan_stock_codes():
    """獲取台股上市櫃所有代碼"""
    try:
        df1 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=2")[0]
        list1 = [c.split('　')[0] for c in df1[0] if len(c.split('　')[0]) == 4]
        df2 = pd.read_html("http://isin.twse.com.tw/isin/C_public.jsp?strMode=4")[0]
        list2 = [c.split('　')[0] for c in df2[0] if len(c.split('　')[0]) == 4]
        return sorted(list(set(list1 + list2)))
    except:
        return ["2330", "2317", "1513", "1519", "3131", "6830"]

def fetch_and_analyze(sid):
    """單一標的獲取與三大指令分析"""
    try:
        # 嘗試兩個市場後綴
        for suffix in [".TW", ".TWO"]:
            ticker = f"{sid}{suffix}"
            df = yf.download(ticker, period="350d", interval="1d", progress=False, show_errors=False)
            if not df.empty and len(df) >= 200:
                break
        
        if df.empty or len(df) < 200: return None
        
        # 數據清洗 (處理 yfinance 可能的 MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 指標計算
        close = df['Close']
        df['MA5'] = close.rolling(5).mean()
        df['MA10'] = close.rolling(10).mean()
        df['MA20'] = close.rolling(20).mean()
        df['MA200'] = close.rolling(200).mean() # 40週線
        
        last = df.iloc[-1]
        # 三大核心指令過濾
        # 1. 股價 > 20MA
        # 2. 股價 > 40週MA (200MA)
        # 3. 5MA < 10MA (短線回檔)
        is_hit = (last['Close'] > last['MA20']) and \
                 (last['Close'] > last['MA200']) and \
                 (last['MA5'] < last['MA10'])
        
        return {"df": df, "is_hit": is_hit, "last": last}
    except:
        return None

# --- 3. Sidebar 控制中心 ---
with st.sidebar:
    st.header("🏹 狙擊控制台")
    mode = st.radio("掃描模式", ["測試熱門股", "全市場掃描 (較慢)"])
    
    st.divider()
    if st.button("🚀 開始執行掃描", use_container_width=True):
        st.session_state.run_scan = True
    
    st.write("### 策略邏輯說明")
    st.caption("1. 股價 > 20MA (波段偏多)")
    st.caption("2. 股價 > 200MA (長線 40 週趨勢向上)")
    st.caption("3. 5MA < 10MA (短線修正找進場點)")

# --- 4. 主頁面內容 ---
st.title("🏹 台股強勢回檔自動化系統")

if 'run_scan' in st.session_state and st.session_state.run_scan:
    all_codes = get_all_taiwan_stock_codes()
    
    # 決定要掃描的名單
    if mode == "測試熱門股":
        target_codes = ["2330", "1513", "1519", "3131", "6830", "2317", "2454", "2308", "2603", "2368"]
    else:
        target_codes = all_codes[:500] # 全市場模式先掃前 500 檔以確保效能
    
    hits = []
    progress_text = st.empty()
    bar = st.progress(0)
    
    # 執行掃描
    for i, sid in enumerate(target_codes):
        progress_text.text(f"🔍 正在掃描 ({i+1}/{len(target_codes)}): {sid}")
        bar.progress((i + 1) / len(target_codes))
        
        res = fetch_and_analyze(sid)
        if res and res['is_hit']:
            hits.append((sid, res['df'], res['last']))
    
    bar.empty()
    progress_text.empty()

    # 顯示結果
    if not hits:
        st.warning("⚠️ 掃描完成：目前市場環境中沒有符合「強勢回檔」條件的標的。")
        st.info("這通常代表市場目前正處於「全面強勢噴出」或「全面走弱跌破 200MA」的狀態。")
    else:
        st.success(f"✅ 成功找到 {len(hits)} 檔符合條件的標的！")
        
        for sid, df, last in hits:
            with st.container():
                st.markdown(f"""
                <div class="hit-card">
                    <span style="font-size:1.2em;">🎯 <b>{sid}</b></span> | 
                    現價: <b>{float(last['Close']):.2f}</b> | 
                    20MA: {float(last['MA20']):.2f} | 
                    40週線: {float(last['MA200']):.2f}
                </div>
                """, unsafe_allow_html=True)
                
                # 繪製 120 天 K 線圖
                d = df.tail(120)
                fig = make_subplots(rows=1, cols=1)
                fig.add_trace(go.Candlestick(
                    x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], name="K線"
                ))
                # 疊加均線
                fig.add_trace(go.Scatter(x=d.index, y=d['MA5'], name="5MA", line=dict(color='#1f77b4', width=1)))
                fig.add_trace(go.Scatter(x=d.index, y=d['MA10'], name="10MA", line=dict(color='#ff7f0e', width=1)))
                fig.add_trace(go.Scatter(x=d.index, y=d['MA20'], name="20MA", line=dict(color='#2ca02c', width=2)))
                fig.add_trace(go.Scatter(x=d.index, y=d['MA200'], name="40週線", line=dict(color='#d62728', width=2, dash='dash')))
                
                fig.update_layout(
                    height=500, 
                    xaxis_rangeslider_visible=False, 
                    template="plotly_white",
                    margin=dict(l=10, r=10, t=30, b=10)
                )
                st.plotly_chart(fig, use_container_width=True)
                st.divider()

else:
    st.info("👈 請在左側點擊「開始執行掃描」按鈕啟動系統。")
    st.write("系統將會自動檢索台股數據，並篩選出長線趨勢向上（站穩 40 週線）且短線回檔的黑馬股。")

# --- 5. 頁尾 ---
st.caption(f"最後同步時間: {get_taiwan_time().strftime('%Y-%m-%d %H:%M:%S')} (台北時區)")
