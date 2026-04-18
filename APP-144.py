import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import plotly.graph_objects as go

# --- 1. 頁面設定 ---
st.set_page_config(layout="wide", page_title="台股狙擊手 V6")

st.title("🏹 最終除錯版：強勢回檔篩選器")

# --- 2. 側邊欄控制 ---
with st.sidebar:
    st.header("控制台")
    # 建議先用這 5 檔測試，如果這 5 檔有出結果，代表程式沒問題，是全市場數據抓取被擋
    test_list = st.text_area("測試代碼 (以空格分開)", value="2330 1513 1519 3131 6830 2317")
    run_btn = st.button("🚀 執行單筆深入掃描")

# --- 3. 核心邏輯：單筆下載（成功率最高） ---
def scan_stock(sid):
    try:
        # 嘗試上市
        ticker = f"{sid}.TW"
        df = yf.download(ticker, period="350d", interval="1d", progress=False, show_errors=False)
        
        # 如果上市沒資料，試試上櫃
        if df.empty or len(df) < 200:
            ticker = f"{sid}.TWO"
            df = yf.download(ticker, period="350d", interval="1d", progress=False, show_errors=False)
            
        if df.empty or len(df) < 200:
            return None, f"{sid}: 找不到足夠數據(需200天以上)"

        # 【關鍵】強制簡化欄位，防止 MultiIndex 報錯
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 計算指標
        close = df['Close']
        df['MA5'] = close.rolling(5).mean()
        df['MA10'] = close.rolling(10).mean()
        df['MA20'] = close.rolling(20).mean()
        df['MA200'] = close.rolling(200).mean() # 40週線
        
        last = df.iloc[-1]
        
        # 你的三大指令
        cond1 = float(last['Close']) > float(last['MA20'])
        cond2 = float(last['Close']) > float(last['MA200'])
        cond3 = float(last['MA5']) < float(last['MA10'])
        
        is_hit = cond1 and cond2 and cond3
        return (df, is_hit), "成功"
        
    except Exception as e:
        return None, f"{sid}: 發生錯誤 {str(e)}"

# --- 4. 執行與顯示 ---
if run_btn:
    sids = test_list.split()
    hits_found = 0
    
    st.write("### 掃描進度報告")
    
    for sid in sids:
        with st.status(f"正在檢查 {sid}...", expanded=False) as status:
            result, msg = scan_stock(sid)
            
            if result:
                df, is_hit = result
                if is_hit:
                    hits_found += 1
                    status.update(label=f"✅ {sid} 符合條件！", state="complete")
                    
                    # 繪圖
                    d = df.tail(120) # 120天K線圖
                    fig = go.Figure()
                    fig.add_trace(go.Candlestick(x=d.index, open=d['Open'], high=d['High'], low=d['Low'], close=d['Close'], name="K線"))
                    fig.add_trace(go.Scatter(x=d.index, y=d['MA5'], name="5MA"))
                    fig.add_trace(go.Scatter(x=d.index, y=d['MA10'], name="10MA"))
                    fig.add_trace(go.Scatter(x=d.index, y=d['MA20'], name="20MA", line=dict(width=2)))
                    fig.add_trace(go.Scatter(x=d.index, y=d['MA200'], name="40週線", line=dict(dash='dash', width=2)))
                    
                    fig.update_layout(title=f"{sid} 符合回檔策略", xaxis_rangeslider_visible=False, height=500)
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    status.update(label=f"❌ {sid} 未達標 (可能沒回檔或趨勢不對)", state="error")
            else:
                status.update(label=f"⚠️ {msg}", state="error")
                
    if hits_found == 0:
        st.warning("掃描完畢，沒有任何標的符合條件。這代表你輸入的這些股票，目前『5MA > 10MA』或者『跌破均線』。")
