import streamlit as st
import twstock
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. 頁面配置與進階 CSS ---
st.set_page_config(layout="wide", page_title="股票狙擊手 Pro Max V2 - 形態篩選版", page_icon="🏹")

st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; font-size: 1.2em; text-align: center; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .neutral-signal { background-color: #6c757d; color: white; border-left: 8px solid #343a40; }
    .dashboard-box { background: #ffffff; padding: 20px; border-radius: 15px; border: 1px solid #e0e0e0; text-align: center; height: 100%; transition: 0.3s; }
    
    .log-container { 
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); 
        color: #e2e8f0; 
        padding: 20px; 
        border-radius: 12px; 
        font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; 
        height: 350px; 
        overflow-y: scroll; 
        border: 1px solid #334155;
        box-shadow: inset 0 2px 10px rgba(0,0,0,0.3);
        line-height: 1.6;
    }
    .log-entry { border-bottom: 1px solid #334155; padding: 8px 0; font-size: 0.9em; }
    .log-time { color: #38bdf8; font-weight: bold; margin-right: 10px; }
    .log-tag { padding: 2px 6px; border-radius: 4px; font-size: 0.8em; margin-right: 5px; font-weight: bold; }
    .tag-buy { background-color: #ef4444; color: white; }
    .tag-sell { background-color: #22c55e; color: white; }
    .tag-info { background-color: #64748b; color: white; }
    
    .stock-card {
        background-color: white;
        border-radius: 10px;
        padding: 15px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. Session State 初始化 ---
if 'event_log' not in st.session_state: st.session_state.event_log = []
if 'sid_map' not in st.session_state: st.session_state.sid_map = {}
if 'tab2_results' not in st.session_state: st.session_state.tab2_results = []

def get_taiwan_time():
    return datetime.utcnow() + timedelta(hours=8)

def is_market_open():
    now = get_taiwan_time()
    start_time = datetime.strptime("09:00", "%H:%M").time()
    end_time = datetime.strptime("13:35", "%H:%M").time()
    return 0 <= now.weekday() <= 4 and start_time <= now.time() <= end_time

def calculate_est_volume(current_vol):
    now = get_taiwan_time()
    current_minutes = now.hour * 60 + now.minute
    start_minutes = 9 * 60
    passed = current_minutes - start_minutes
    if passed <= 5: return current_vol * 3  
    if passed >= 270: return current_vol
    return current_vol * (270 / (passed + 10))

@st.cache_data(ttl=3600)
def get_stock_data(sid, token):
    try:
        res = requests.get(BASE_URL, params={
            "dataset": "TaiwanStockPrice", "data_id": sid,
            "start_date": (datetime.now() - timedelta(days=300)).strftime("%Y-%m-%d"),
            "token": token
        }, timeout=15).json()
        
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values("date").reset_index(drop=True)

        if is_market_open():
            try:
                realtime_data = twstock.realtime.get(sid)
                if realtime_data and realtime_data['success']:
                    real = realtime_data['realtime']
                    last_price = float(real['latest_trade_price']) if real['latest_trade_price'] != '-' else float(real['open'])
                    day_high = float(real['high']) if real['high'] != '-' else last_price
                    day_low = float(real['low']) if real['low'] != '-' else last_price
                    day_vol = int(real['accumulate_trade_volume']) * 1000 
                    
                    today_dt = pd.Timestamp(get_taiwan_time().date())
                    if df.iloc[-1]['date'].date() == today_dt.date():
                        idx = df.index[-1]
                    else:
                        new_row = df.iloc[-1].copy()
                        new_row['date'] = today_dt
                        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
                        idx = df.index[-1]
                    
                    df.at[idx, 'close'] = last_price
                    df.at[idx, 'high'] = day_high
                    df.at[idx, 'low'] = day_low
                    df.at[idx, 'volume'] = day_vol
                    df.at[idx, 'est_volume'] = calculate_est_volume(day_vol)
                else:
                    df['est_volume'] = df['volume']
            except Exception:
                df['est_volume'] = df['volume']
        else:
            df['est_volume'] = df['volume']
            
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        df['volume'] = df['volume'].fillna(0)
        df['est_volume'] = df['est_volume'].fillna(df['volume'])
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].ffill()
        return df
    except Exception:
        return None

# --- 3. 新增選股策略判定核心：MACD上穿0軸/回踩 + 25日線支持 ---
def check_macd_ma25_strategy(df):
    if df is None or len(df) < 60:
        return False, {}

    # 1. 技術指標計算
    df['ma25'] = df['close'].rolling(25).mean()
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    
    # MACD 計算 (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['dif'] = exp1 - exp2
    df['macd_signal'] = df['dif'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['dif'] - df['macd_signal']
    
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    recent_10 = df.iloc[-10:]
    recent_20 = df.iloc[-20:]

    # --- 條件 1: 站上/回踩 25 日線 ---
    # 近 20 天內曾高於 25 日線，且當前股價 > 25日線 * 0.98 (支撐區附近止跌)
    has_stood_ma25 = (recent_20['close'] > recent_20['ma25']).any()
    near_ma25_support = curr['close'] >= curr['ma25'] * 0.97 and (curr['low'] <= curr['ma25'] * 1.02)
    cond_ma25 = has_stood_ma25 and near_ma25_support

    # --- 條件 2: MACD 上穿 0 軸 & 近期回踩 0 軸黏合 ---
    # 近 30 天 DIF 曾大於 0 (上穿0軸)
    dif_above_zero = (df['dif'].tail(30) > 0).any()
    # DIF 近期回踩至 0 軸附近 (-0.5 ~ 0.8 之間)
    dif_near_zero = abs(curr['dif']) <= (curr['close'] * 0.015) or (-0.3 <= curr['dif'] <= 0.8)
    # 雙線/柱體黏合或金叉（DIF 向上轉折或近 3 天內有金叉）
    macd_golden_cross = (curr['dif'] > curr['macd_signal']) or (curr['macd_hist'] > prev['macd_hist'])
    cond_macd = dif_above_zero and dif_near_zero and macd_golden_cross

    # --- 條件 3: 帶量陽線突破 ---
    is_red_candle = curr['close'] > curr['open']  # 紅棒
    vol_magnified = (curr['est_volume'] > curr['vol_ma5'] * 1.1) or (curr['volume'] > prev['volume'] * 1.2) # 放量
    price_pct = ((curr['close'] - prev['close']) / prev['close']) * 100
    cond_breakout = is_red_candle and vol_magnified and (price_pct > 0.5)

    is_matched = cond_ma25 and cond_macd and cond_breakout

    details = {
        "close": curr['close'],
        "pct": price_pct,
        "ma25": curr['ma25'],
        "dif": curr['dif'],
        "macd_hist": curr['macd_hist'],
        "vol_ratio": curr['est_volume'] / (curr['vol_ma5'] + 1e-5),
        "is_matched": is_matched
    }

    return is_matched, details
    # --- 4. 側邊欄與 API 設定 ---
st.sidebar.title("🏹 股票狙擊手 V2")
finmind_token = st.sidebar.text_input("FinMind Token", value="", type="password")

if not finmind_token:
    st.info("💡 請在側邊欄輸入 FinMind API Token 以啟用系統數據讀取。")
    st.stop()

# --- 5. 主分頁架構 ---
tab1, tab2 = st.tabs(["📊 個人化持股監控 (Tab 1)", "🎯 MACD 0軸/25日線 形態選股 (Tab 2)"])

# ==========================================
# Tab 1: 原有監控系統邏輯 (可整合原本功能)
# ==========================================
with tab1:
    st.header("📊 個人化持股/關注清單即時監控")
    monitor_sids = st.text_input("請輸入欲監控的股票代碼 (以半形逗號分隔)", value="2330,2317,2454,2308")
    
    if st.button("執行持股分析", key="btn_tab1"):
        sid_list = [s.strip() for s in monitor_sids.split(",") if s.strip()]
        progress_bar = st.progress(0)
        
        for idx, sid in enumerate(sid_list):
            df = get_stock_data(sid, finmind_token)
            if df is not None and not df.empty:
                curr = df.iloc[-1]
                prev = df.iloc[-2]
                pct = ((curr['close'] - prev['close']) / prev['close']) * 100
                
                col1, col2, col3, col4 = st.columns(4)
                col1.metric(f"股票代碼: {sid}", f"{curr['close']:.2f}", f"{pct:+.2f}%")
                col2.metric("最高價", f"{curr['high']:.2f}")
                col3.metric("最低價", f"{curr['low']:.2f}")
                col4.metric("當前/預估成交量", f"{int(curr['est_volume']):,}")
            progress_bar.progress((idx + 1) / len(sid_list))
        st.success("監控數據更新完成！")

# ==========================================
# Tab 2: 0軸回踩與 25 日線支持選股系統
# ==========================================
with tab2:
    st.header("🎯 MACD 0軸回踩與 25 日線支撐 - 帶量陽線選股")
    st.caption("策略邏輯：尋找股價站上/回踩 25 日線，MACD 雙線在 0 軸附近黏合或金叉，且今日出現放量紅棒突破的潛力標的。")

    col_input, col_action = st.columns([3, 1])
    with col_input:
        scan_pool = st.text_area(
            "掃描股票池 (代碼請用逗號、分號或換行隔開)", 
            value="2330, 2317, 2454, 2308, 3037, 2382, 3231, 2376, 6669, 3661, 3443, 6274, 3035, 2303, 2408",
            height=100
        )
    with col_action:
        st.write("##")
        start_scan = st.button("🚀 開始形態選股", type="primary", use_container_width=True)

    if start_scan:
        # 清理輸入的股票代碼
        sids = re.split(r'[,;\s\n]+', scan_pool.strip())
        sids = [s for s in sids if s.isdigit()]
        
        if not sids:
            st.warning("⚠️ 請輸入有效的股票代碼！")
        else:
            st.session_state.tab2_results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total_stocks = len(sids)
            matched_count = 0
            
            # 使用多線程加快抓取與分析速度
            def worker(sid):
                df = get_stock_data(sid, finmind_token)
                if df is not None:
                    matched, details = check_macd_ma25_strategy(df)
                    if matched:
                        details['sid'] = sid
                        details['df'] = df
                        return details
                return None

            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(worker, sid): sid for sid in sids}
                for i, future in enumerate(as_completed(futures)):
                    sid = futures[future]
                    status_text.text(f"🔍 正在分析 {sid} ({i+1}/{total_stocks})...")
                    res = future.result()
                    if res:
                        st.session_state.tab2_results.append(res)
                        matched_count += 1
                    progress_bar.progress((i + 1) / total_stocks)
            
            status_text.empty()
            progress_bar.empty()
            st.success(f"🎉 掃描完成！共分析 {total_stocks} 檔股票，符合「0軸回踩+25日線支撐」形態共有 {matched_count} 檔。")

    # 展示選股結果與圖表
    if st.session_state.tab2_results:
        st.subheader("📌 符合條件標的列表")
        
        # 轉換成 DataFrame 展示摘要表格
        summary_data = []
        for r in st.session_state.tab2_results:
            summary_data.append({
                "股票代碼": r['sid'],
                "當前股價": f"{r['close']:.2f}",
                "今日漲跌幅": f"{r['pct']:+.2f}%",
                "25日線 (MA25)": f"{r['ma25']:.2f}",
                "MACD DIF": f"{r['dif']:.3f}",
                "MACD 柱狀體": f"{r['macd_hist']:.3f}",
                "預估放大倍數": f"{r['vol_ratio']:.2f}x"
            })
        
        st.dataframe(pd.DataFrame(summary_data), use_container_width=True)
        
        st.markdown("---")
        st.subheader("📈 符合形態標的 - K線與 MACD 技術圖表")
        
        # 渲染每張符合股票的 Plotly 詳細圖表
        for r in st.session_state.tab2_results:
            sid = r['sid']
            df = r['df'].tail(90) # 顯示最近 90 個交易日
            
            with st.expander(f"🔍 查看 {sid} 技術圖表分析 (股價: {r['close']:.2f} | 漲幅: {r['pct']:+.2f}%)", expanded=True):
                # 建立 3 個子圖：K線與均線 / 成交量 / MACD
                fig = make_subplots(
                    rows=3, cols=1, 
                    shared_xaxes=True, 
                    vertical_spacing=0.03,
                    row_heights=[0.5, 0.2, 0.3],
                    subplot_titles=(f"{sid} 股價與 25日均線", "成交量與預估量", "MACD 指標")
                )
                
                # 1. K線圖與 MA25
                fig.add_trace(go.Candlestick(
                    x=df['date'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
                    name="K線"
                ), row=1, col=1)
                
                fig.add_trace(go.Scatter(
                    x=df['date'], y=df['ma25'], line=dict(color='orange', width=2), name="25日線 (MA25)"
                ), row=1, col=1)
                
                # 2. 成交量圖
                colors = ['red' if c >= o else 'green' for c, o in zip(df['close'], df['open'])]
                fig.add_trace(go.Bar(
                    x=df['date'], y=df['volume'], marker_color=colors, name="成交量"
                ), row=2, col=1)
                
                # 3. MACD 圖
                fig.add_trace(go.Scatter(
                    x=df['date'], y=df['dif'], line=dict(color='blue', width=1.5), name="DIF"
                ), row=3, col=1)
                fig.add_trace(go.Scatter(
                    x=df['date'], y=df['macd_signal'], line=dict(color='red', width=1.5), name="DEM (MACD)"
                ), row=3, col=1)
                
                hist_colors = ['red' if h >= 0 else 'green' for h in df['macd_hist']]
                fig.add_trace(go.Bar(
                    x=df['date'], y=df['macd_hist'], marker_color=hist_colors, name="MACD柱體"
                ), row=3, col=1)
                
                # Layout 配置
                fig.update_layout(
                    height=650,
                    xaxis_rangeslider_visible=False,
                    margin=dict(l=20, r=20, t=40, b=20),
                    template="plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)

# --- 6. 系統日誌與底欄 ---
with st.expander("📋 系統即時執行日誌", expanded=False):
    st.markdown('<div class="log-container">', unsafe_allow_html=True)
    if not st.session_state.event_log:
        st.markdown('<div class="log-entry"><span class="log-time">系統狀態</span>無最新事件</div>', unsafe_allow_html=True)
    for log in reversed(st.session_state.event_log[-20:]):
        st.markdown(f'<div class="log-entry"><span class="log-time">{log["time"]}</span> {log["msg"]}</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
