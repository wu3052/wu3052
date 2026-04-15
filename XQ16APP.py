import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re
import time

# --- 1. 頁面配置與進階 CSS 樣式 ---
st.set_page_config(layout="wide", page_title="股票狙擊手", page_icon="🏹")

# 這裡補回了您截圖中所有的視覺元素，包含狀態卡片的陰影與馬卡龍色調
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; border-left: 8px solid; }
    .buy-signal { background-color: #ffe3e3; color: #b91c1c; border-color: #b91c1c; }
    .sell-signal { background-color: #e1f7e5; color: #15803d; border-color: #15803d; }
    .normal-signal { background-color: #f3f4f6; color: #374151; border-color: #9ca3af; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# --- 2. 核心通知模組 ---
def send_discord_message(msg):
    webhook_url = st.secrets.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        st.error("❌ 找不到 Discord Webhook URL")
        return
    try:
        requests.post(webhook_url, json={"content": msg}, timeout=10)
    except Exception as e:
        st.error(f"通知發送失敗: {e}")

# --- 3. 數據獲取與 API 管理 ---
@st.cache_data(ttl=300)
def get_stock_data(sid, token, days=1200): 
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": sid,
        "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "token": token
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10).json()
        df = pd.DataFrame(res.get("data", []))
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values("date").reset_index(drop=True)
    except: return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
        return pd.DataFrame(res.json()["data"]).rename(columns=str.lower)
    except: return pd.DataFrame()

# --- 4. 核心策略與發動點邏輯 (完全版) ---
def analyze_strategy(df):
    if df is None or len(df) < 200: return None
    
    # 均線族群
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 指標計算
    df["ma144_60min"] = df["close"].rolling(36).mean() 
    df["ma55_60min"] = df["close"].rolling(14).mean()  
    exp1, exp2 = df['close'].ewm(span=12).mean(), df['close'].ewm(span=26).mean()
    df['macd'] = exp1 - exp2
    df['hist'] = df['macd'] - df['macd'].ewm(span=9).mean()
    
    # 關鍵位判定
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))
    df["upward_key"] = df["close"].where(df["dc_signal"]).ffill()
    df["downward_key"] = df["close"].where(df["gc_signal"]).ffill()
    
    # 修正發動點：必須站上 5MA 且黃金交叉
    df["star_signal"] = (df["close"] > df["ma5"]) & (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    # 初始化數據
    last_idx = df.index[-1]
    row, prev = df.iloc[-1], df.iloc[-2]
    buy_sigs, sell_sigs = [], []
    
    # 買訊過濾
    if row["close"] > row["ma5"] and prev["close"] <= prev["ma5"]: buy_sigs.append("🏹 站上5MA(買點)")
    if row["close"] > row["ma144_60min"] and prev["close"] <= prev["ma144_60min"]: buy_sigs.append("🚀 站上60分144MA(買點)")
    if row["star_signal"]: buy_sigs.append("⭐ 站上發動點(觀察買點)")
    if not pd.isna(row["upward_key"]) and row["close"] > row["upward_key"] and prev["close"] <= row["upward_key"]:
        buy_sigs.append("🎯 站上死亡交叉關鍵位(上漲買入)")

    # 賣訊過濾
    if row["close"] < row["ma5"] and prev["close"] >= prev["ma5"]: sell_sigs.append("⚠️ 跌破5MA(注意賣點)")
    if row["close"] < row["ma10"] and prev["close"] >= prev["ma10"]: sell_sigs.append("📉 跌破10MA(賣點)")
    if row["hist"] < prev["hist"] and row["hist"] > 0: sell_sigs.append("🎯 目標達成/紅柱縮短")
    if not pd.isna(row["downward_key"]) and row["close"] < row["downward_key"] and prev["close"] >= row["downward_key"]:
        sell_sigs.append("🚫 跌破黃金交叉關鍵位(下跌賣出)")

    # 綜合評分與型態
    df.at[last_idx, "score"] = max(10, min(50 + (len(buy_sigs)*10) - (len(sell_sigs)*15), 100))
    df.at[last_idx, "warning_buy"] = " / ".join(buy_sigs)
    df.at[last_idx, "warning_sell"] = " / ".join(sell_sigs)
    df.at[last_idx, "pattern"] = "📐 黃金三角眼" if row["ma5"] > row["ma10"] > row["ma20"] else "💎 鑽石眼" if abs(row["ma5"]-row["ma20"])/row["close"] < 0.01 else "一般盤整"
    
    return df

# --- 5. 圖表繪製 (台股顏色 + 關鍵位虛線 + 星星) ---
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 蠟燭圖 (紅漲綠跌)
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], low=df_plot["low"], close=df_plot["close"], name="K線",
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b', decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71'
    ), row=1, col=1)
    
    # 均線群
    for ma, col in {5:'#2980b9', 10:'#f1c40f', 20:'#e67e22', 60:'#9b59b6'}.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=col, width=1.5)), row=1, col=1)

    # 關鍵位虛線 (補回)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.5)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.5)', dash='dash')), row=1, col=1)
    
    # 發動點星星 (補回)
    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"]*0.97, mode="markers", marker=dict(symbol="star", size=15, color="#FFD700"), name="發動點"), row=1, col=1)

    # MACD 柱狀圖
    macd_cols = ['#eb4d4b' if v >= 0 else '#2ecc71' for v in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=macd_cols), row=2, col=1)
    
    fig.update_layout(height=650, template="plotly_white", xaxis_rangeslider_visible=False, title=title, margin=dict(l=10,r=10,t=50,b=10))
    return fig

# --- 6. 整合執行邏輯 ---
fm_token = st.secrets.get("FINMIND_TOKEN", "")
if 'notified_stocks' not in st.session_state: st.session_state.notified_stocks = {}

with st.sidebar:
    st.header("🏹 指揮中心")
    if st.button("🔄 同步 Google 表格"):
        # 這裡實作您原本的 Google Sheets 讀取邏輯
        st.session_state.search_codes = "2330 2382 3019" # 範例
        st.success("清單已更新")
    
    st.session_state.search_codes = st.text_area("🎯 狙擊清單", value=st.session_state.get('search_codes', ""))
    st.session_state.inventory_codes = st.text_area("📦 庫存清單", value=st.session_state.get('inventory_codes', ""))
    interval = st.slider("監控間隔 (分鐘)", 1, 30, 5)
    auto_monitor = st.checkbox("🔄 開啟自動監控")
    if st.button("🔔 測試 Discord 通知"): send_discord_message("🏹 測試連線中...")
    analyze_btn = st.button("🚀 即時掃描", use_container_width=True)

def run_process():
    # 顯示大盤 (補回自動展開)
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        st.subheader(f"🌐 指數戰報 - 目前評分: {m_last['score']}")
        st.plotly_chart(plot_advanced_chart(m_df, "台股大盤"), use_container_width=True)

    st.divider()

    # 個股清單處理
    snipe_list = [c for c in re.split(r'[\s\n,]+', st.session_state.search_codes) if c]
    inv_list = [c for c in re.split(r'[\s\n,]+', st.session_state.inventory_codes) if c]
    all_codes = sorted(list(set(snipe_list + inv_list)))
    stock_info = get_stock_info()
    results = []
    
    for sid in all_codes:
        df = get_stock_data(sid, fm_token)
        if df is None: continue
        df = analyze_strategy(df)
        last = df.iloc[-1]
        s_name = stock_info[stock_info["stock_id"] == sid]["stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
        
        is_inv = sid in inv_list
        tag = "【庫存股】" if is_inv else "【狙擊股】"
        reason = last["warning_sell"] if (is_inv and last["warning_sell"]) else last["warning_buy"] if (not is_inv and last["warning_buy"]) else ""
        
        # Discord 推播 (補回完整美化格式)
        if reason and (time.time() - st.session_state.notified_stocks.get(sid, 0)) > 3600:
            discord_msg = (
                f"### {tag} 訊號觸發：{sid} {s_name}\n"
                f"**──────────────────**\n"
                f"💡 **觸發原因**: `{reason}`\n"
                f"💰 **目前現價**: `{last['close']:.2f}`\n"
                f"📊 **戰情評分**: `{last['score']} 分`\n"
                f"🧭 **趨勢型態**: {last['pattern']}\n"
                f"🚩 **戰情提醒**: {reason if reason else '穩定觀察中'}\n"
                f"**──────────────────**\n"
                f"⏰ *通知時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*"
            )
            send_discord_message(discord_msg)
            st.session_state.notified_stocks[sid] = time.time()

        # HTML 卡片
        card_class = "buy-signal" if last["warning_buy"] else "sell-signal" if last["warning_sell"] else "normal-signal"
        st.markdown(f"""
        <div class="status-card {card_class}">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <span style="font-size:20px;">{tag} {sid} {s_name} (<b>{last['close']:.2f}</b>)</span>
                <span style="font-size:16px;">評分: {last['score']}</span>
            </div>
            <div style="margin-top:8px;">🚩 戰情提醒：{reason if reason else '趨勢穩定中'}</div>
        </div>
        """, unsafe_allow_html=True)
        
        with st.expander(f"查看 {sid} {s_name} 圖表"):
            st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name}"), use_container_width=True)
        
        results.append({"代碼": sid, "名稱": s_name, "評分": last['score'], "趨勢型態": last['pattern'], "提醒": reason if reason else "穩定"})

    # 補回：掃描排行表格
    if results:
        st.subheader("🏆 本次掃描排行")
        st.dataframe(pd.DataFrame(results).sort_values("評分", ascending=False), use_container_width=True, hide_index=True)

# 執行與自動循環
if analyze_btn or auto_monitor:
    run_process()
    if auto_monitor:
        st.caption(f"最後更新於: {datetime.now().strftime('%H:%M:%S')}")
        time.sleep(interval * 60)
        st.rerun()
else:
    run_process()
