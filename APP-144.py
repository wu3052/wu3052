import streamlit as st
import pandas as pd
import pandas_ta as ta
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from FinMind.data import DataLoader
import twstock
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import time

# --- 系統配置與初始化 ---
st.set_page_config(page_title="股票狙擊手 Pro Max V2", layout="wide")

# 套用終端機風格 CSS
st.markdown("""
    <style>
    .terminal-log {
        background-color: #0e1117;
        color: #00ff00;
        font-family: 'Courier New', Courier, monospace;
        padding: 10px;
        border-radius: 5px;
        height: 200px;
        overflow-y: auto;
        border: 1px solid #444;
    }
    .pulse-card {
        padding: 20px;
        border-radius: 10px;
        border: 2px solid #ff4b4b;
        animation: pulse 2s infinite;
    }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0.7); }
        70% { box-shadow: 0 0 0 10px rgba(255, 75, 75, 0); }
        100% { box-shadow: 0 0 0 0 rgba(255, 75, 75, 0); }
    }
    </style>
    """, unsafe_allow_html=True)

# --- 核心數據類別 ---
class SniperEngine:
    def __init__(self, api_token, discord_url):
        self.api_token = api_token
        self.discord_url = discord_url
        self.dl = DataLoader()
        if api_token:
            self.dl.login_token(api_token)

    def get_market_status(self):
        """獲取大盤(加權指數)狀態"""
        # 這裡簡化以台積電(2330)或主要指數代替大盤邏輯
        try:
            df = self.dl.taiwan_stock_daily(stock_id='0050', start_date=(datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d'))
            current_price = df['close'].iloc[-1]
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            score = 80 if current_price > ma20 else 30
            status = "多頭" if score > 50 else "空頭"
            return score, status
        except:
            return 50, "數據讀取中"

    def fetch_data(self, stock_id):
        """縫合歷史與即時數據"""
        # 1. 歷史數據 (FinMind)
        start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        df_hist = self.dl.taiwan_stock_daily(stock_id=stock_id, start_date=start_date)
        df_hist = df_hist[['date', 'open', 'max', 'min', 'close', 'Trading_Volume']]
        df_hist.columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        df_hist['date'] = pd.to_datetime(df_hist['date'])
        
        # 2. 即時數據 (twstock) - 僅在盤中生效
        try:
            realtime_data = twstock.realtime.get(stock_id)
            if realtime_data['success']:
                rt = realtime_data['info']
                now_price = float(realtime_data['realtime']['latest_trade_price'])
                # 簡易縫合邏輯
                last_row = {
                    'date': datetime.now(),
                    'open': float(realtime_data['realtime']['open']),
                    'high': float(realtime_data['realtime']['high']),
                    'low': float(realtime_data['realtime']['low']),
                    'close': now_price,
                    'volume': int(realtime_data['realtime']['accumulated_trade_volume']) * 1000
                }
                df_hist = pd.concat([df_hist, pd.DataFrame([last_row])], ignore_index=True)
        except:
            pass
        
        return df_hist

    def calculate_indicators(self, df):
        """F-003: 技術指標運算體系"""
        # 均線族
        for ma in [5, 10, 20, 55, 60, 144, 200]:
            df[f'MA{ma}'] = ta.sma(df['close'], length=ma)
        
        # MACD
        macd = ta.macd(df['close'])
        df = pd.concat([df, macd], axis=1)
        
        # VCP 壓縮度 (HL Range)
        df['volatility'] = (df['high'] - df['low']) / df['close']
        df['vcp_check'] = df['volatility'].rolling(10).mean()
        
        # ATR (倉位建議)
        df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        return df

    def analyze_strategy(self, df, market_score):
        """F-004: 綜合評分系統"""
        score = 50
        signals = []
        
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 大盤避險原則
        if market_score < 40:
            return 20, ["⚠️ 大盤風險高，建議避險暫緩"]

        # 1. 均線邏輯
        if last['close'] > last['MA5']: score += 12
        if last['MA5'] > last['MA10'] > last['MA20']: score += 15
        
        # 2. 突破偵測 (噴發第一根)
        if last['close'] > last['MA20'] and prev['close'] <= prev['MA20'] and last['volume'] > prev['volume'] * 1.5:
            score += 25
            signals.append("🚀 噴發第一根")
            
        # 3. VCP 壓縮判定
        if last['vcp_check'] < prev['vcp_check'] * 0.9:
            score += 10
            signals.append("💎 鑽石眼 (波動壓縮)")

        # 4. 扣分邏輯
        if last['close'] < last['MA10']: score -= 20
        
        # 倉位建議 (基於 ATR)
        risk_per_share = last['ATR'] * 2
        position_size = "10%" if score > 70 else "5%"
        
        return score, signals, position_size

# --- UI 介面實作 ---

# 側邊欄控制區
with st.sidebar:
    st.header("🎛️ 狙擊手控制台")
    api_token = st.text_input("FinMind Token", type="password")
    webhook_url = st.text_input("Discord Webhook URL", type="password")
    
    st.divider()
    auto_refresh = st.toggle("Auto Refresh (60s)")
    discord_notify = st.checkbox("開啟 Discord 通知")
    
    target_stocks = st.text_area("監控清單 (代碼以逗號隔開)", "2330,2317,2454,3037,1513,2308")
    stock_list = [s.strip() for s in target_stocks.split(",")]
    
    scan_btn = st.button("🚀 開始全線掃描", use_container_width=True)

# 實例化引擎
engine = SniperEngine(api_token, webhook_url)

# 主要顯示區域
st.title("🏹 股票狙擊手 Pro Max V2")

# F-001: 市場概況
m_score, m_status = engine.get_market_status()
col1, col2, col3 = st.columns(3)
col1.metric("大盤戰情評分", f"{m_score} 分", delta="多方占優" if m_score > 50 else "空方警戒")
col2.metric("當前市場位階", m_status)
col3.metric("監控個股數量", len(stock_list))

# 戰情日誌
st.subheader("📡 實時戰情日誌")
log_container = st.empty()
if 'logs' not in st.session_state:
    st.session_state.logs = []

def update_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {msg}")
    if len(st.session_state.logs) > 8: st.session_state.logs.pop(0)
    log_content = "<br>".join(st.session_state.logs)
    log_container.markdown(f'<div class="terminal-log">{log_content}</div>', unsafe_allow_html=True)

# 掃描邏輯
if scan_btn:
    update_log("系統啟動：開始執行多線程掃描...")
    
    results = []
    
    # 這裡演示單股詳細分析，實際可用 ThreadPoolExecutor 優化
    for symbol in stock_list:
        try:
            df = engine.fetch_data(symbol)
            df = engine.calculate_indicators(df)
            score, signals, pos = engine.analyze_strategy(df, m_score)
            
            results.append({
                "代碼": symbol,
                "評分": score,
                "訊號": " | ".join(signals),
                "建議倉位": pos,
                "df": df
            })
            
            if score > 70:
                update_log(f"🔥 發現目標！ {symbol} 評分: {score} - {signals}")
                if discord_notify and webhook_url:
                    requests.post(webhook_url, json={"content": f"🎯 【狙擊訊號】{symbol} | 評分: {score} | 訊號: {signals}"})
            else:
                update_log(f"掃描中: {symbol} 正常")
        except Exception as e:
            update_log(f"❌ {symbol} 數據處理錯誤: {str(e)}")

    # 顯示狙擊卡片
    st.divider()
    high_score_stocks = [r for r in results if r['評分'] > 65]
    if high_score_stocks:
        st.subheader("🎯 優先狙擊目標")
        cols = st.columns(len(high_score_stocks))
        for i, stock in enumerate(high_score_stocks):
            with cols[i]:
                st.markdown(f"""
                <div class="pulse-card">
                    <h3>{stock['代碼']}</h3>
                    <h2 style='color:#ff4b4b'>{stock['評分']} 分</h2>
                    <p>{stock['訊號']}</p>
                    <strong>建議倉位: {stock['建議倉位']}</strong>
                </div>
                """, unsafe_allow_html=True)

    # F-005: 視覺化圖表
    st.divider()
    st.subheader("📊 關鍵位戰情圖表")
    for stock in results:
        with st.expander(f"查看 {stock['代碼']} 詳細分析圖表 (評分: {stock['評分']})"):
            df = stock['df'].tail(100)
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
            
            # K 線與均線
            fig.add_trace(go.Candlestick(x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name="K線"), row=1, col=1)
            for ma in [5, 20, 60]:
                fig.add_trace(go.Scatter(x=df['date'], y=df[f'MA{ma}'], name=f'MA{ma}', line=dict(width=1.5)), row=1, col=1)
            
            # MACD
            colors = ['red' if val >= 0 else 'green' for val in df['MACDh_12_26_9']]
            fig.add_trace(go.Bar(x=df['date'], y=df['MACDh_12_26_9'], marker_color=colors, name="MACD"), row=2, col=1)
            
            fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

# 自動重新整理邏輯
if auto_refresh:
    time.sleep(60)
    st.rerun()
