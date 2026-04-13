import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import re

# --- 頁面配置 ---
st.set_page_config(layout="wide", page_title="股票狙擊手", page_icon="🏹")

# 自定義 CSS 樣式
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: white; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .status-card { padding: 20px; border-radius: 12px; margin-bottom: 20px; font-weight: bold; }
    .buy-signal { background-color: #ff4b4b; color: white; border-left: 8px solid #990000; }
    .sell-signal { background-color: #28a745; color: white; border-left: 8px solid #155724; }
    .info-tag { font-size: 0.85em; padding: 3px 8px; border-radius: 4px; margin-right: 5px; }
    .tag-blue { background-color: #e7f5ff; color: #1971c2; }
    .tag-purple { background-color: #f3f0ff; color: #6741d9; }
</style>
""", unsafe_allow_html=True)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 數據獲取模組
# =====================
@st.cache_data(ttl=3600)
def get_stock_data(sid, token, days=1200): 
    # 多抓一點數據以計算 200MA 與 週線
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": sid,
        "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "token": token
    }
    try:
        res = requests.get(BASE_URL, params=params).json()
        data = res.get("data", [])
        if not data: return None
        df = pd.DataFrame(data)
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max": "high", "min": "low", "trading_volume": "volume"})
        df['date'] = pd.to_datetime(df['date'])
        return df.sort_values("date").reset_index(drop=True)
    except:
        return None

@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"})
        df = pd.DataFrame(res.json()["data"])
        df.columns = [c.lower() for c in df.columns]
        return df
    except:
        return pd.DataFrame()

# =====================
# 🔹 核心策略分析模組
# =====================
def analyze_strategy(df):
    if df is None or len(df) < 200: return None
    
    # 1. 均線系統
    for ma in [5, 10, 20, 60, 200]:
        df[f"ma{ma}"] = df["close"].rolling(ma).mean()
    
    # 2. 週線檢查 (簡化版：使用 5MA 的 5 倍做參考)
    df["week_ma"] = df["close"].rolling(25).mean() 
    df["is_weekly_bull"] = (df["close"] > df["week_ma"]) & (df["week_ma"] > df["week_ma"].shift(5))

    # 3. MACD 計算
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['signal_line'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['hist'] = df['macd'] - df['signal_line']
    
    # 4. 乖離率 (BIAS)
    df["bias_20"] = ((df["close"] - df["ma20"]) / df["ma20"]) * 100

    # 5. 扣抵值預測 (40週線 = 200MA)
    df["ma200_deduct"] = df["close"].shift(200)
    
    # 6. 上漲關鍵位與下跌關鍵位 (取代舊版測高測低)
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    df["upward_key"] = np.nan
    df["downward_key"] = np.nan

    # 死亡交叉當日收盤為上漲關鍵位(買入突破點)；黃金交叉當日收盤為下跌關鍵位(賣出跌破點)
    df.loc[df["dc_signal"], "upward_key"] = df["close"]
    df.loc[df["gc_signal"], "downward_key"] = df["close"]

    # 向下填充延續線條
    df["upward_key"] = df["upward_key"].ffill()
    df["downward_key"] = df["downward_key"].ffill()

    # 7. 關鍵轉折點標記 (★ 符號邏輯) - 降低頻率版
    df["star_signal"] = False
    for i in range(1, len(df)):
        # 僅保留「黃金交叉第一天」且「股價站上5MA」，大幅降低頻繁出現的問題
        is_golden_cross = (df["ma5"].iloc[i] > df["ma10"].iloc[i]) and (df["ma5"].iloc[i-1] <= df["ma10"].iloc[i-1])
        if df["close"].iloc[i] > df["ma5"].iloc[i] and is_golden_cross:
            df.loc[df.index[i], "star_signal"] = True

    # 8. 狀態判定與警告
    df["warning"] = ""
    df["position_type"] = "觀察中"
    df["score"] = 50
    
    last_idx = df.index[-1]
    row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # MACD 縮短撤退提醒
    if row["hist"] > 0 and row["hist"] < prev_row["hist"] and row["close"] > row["ma5"]:
        df.at[last_idx, "warning"] = "🎯 目標達成，紅柱縮短，準備撤退"

    # 乖離率預警
    if row["bias_20"] > 10: df.at[last_idx, "warning"] += " ⚠️ 乖離過高"
    elif row["bias_20"] < -10: df.at[last_idx, "warning"] += " 📉 乖離過低"

    # 關鍵位突破/跌破提示
    if row["close"] > row["upward_key"] and prev_row["close"] <= prev_row["upward_key"]:
        df.at[last_idx, "warning"] += " 🚀 突破上漲關鍵位(買點)"
    elif row["close"] < row["downward_key"] and prev_row["close"] >= prev_row["downward_key"]:
        df.at[last_idx, "warning"] += " 🩸 跌破下跌關鍵位(賣點)"

    # 判定位置
    if row["close"] > row["ma200"] and row["ma5"] > row["ma60"]:
        if row["bias_20"] > 8: df.at[last_idx, "position_type"] = "超級噴發位"
        else: df.at[last_idx, "position_type"] = "主升段確認位"
        df.at[last_idx, "score"] = 85
    elif row["close"] > row["ma20"] and row["close"] < row["ma60"]:
        df.at[last_idx, "position_type"] = "底部起漲位"
        df.at[last_idx, "score"] = 70
    elif row["star_signal"]:
        df.at[last_idx, "position_type"] = "起漲發動位"
        df.at[last_idx, "score"] = 80

    # 型態標籤
    df["pattern"] = "一般盤整"
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    if ma_diff < 0.015: df.at[last_idx, "pattern"] = "💎 鑽石眼"
    elif row["ma5"] > row["ma10"] > row["ma20"]: df.at[last_idx, "pattern"] = "📐 黃金三角眼"
    elif row["low"] < row["ma20"] and row["close"] > row["ma20"]: df.at[last_idx, "pattern"] = "🕳️ 鑽石坑"

    return df

# =====================
# 📊 圖表繪製模組 (淺色質感版)
# =====================
def plot_advanced_chart(df, title=""):
    # 僅取最近 100 天展示
    df_plot = df.tail(100).copy()
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.05, row_heights=[0.7, 0.3])

    # 1. 蠟燭圖 (維持台股紅漲綠跌，但在淺色背景下調整飽和度)
    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], 
        low=df_plot["low"], close=df_plot["close"], name="K線",
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b', 
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71'
    ), row=1, col=1)

    # 2. 均線 (針對淺色背景調整顏色)
    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(
            x=df_plot["date"], y=df_plot[f"ma{ma}"], 
            name=f"{ma}MA", line=dict(color=color, width=1.5)
        ), row=1, col=1)

    # 3. 繪製上漲與下跌關鍵位
    fig.add_trace(go.Scatter(
        x=df_plot["date"], y=df_plot["upward_key"], 
        name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.5)', dash='dash') 
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df_plot["date"], y=df_plot["downward_key"], 
        name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.5)', dash='dash') 
    ), row=1, col=1)

# 4. 標註 ★ 符號 (取消輪廓線，純色)
    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(
        x=stars["date"], y=stars["low"] * 0.98,
        mode="markers", marker=dict(symbol="star", size=14, color="#FFD700"), # 純金色，無輪廓
        name="發動點"
    ), row=1, col=1)

    # 5. MACD 柱狀圖 (淺色質感)
    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)

    # --- 修改為淺色風格配置 ---
    fig.update_layout(
        title=title, 
        height=700, 
        template="plotly_white", # 切換為白色模板
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor='white',
        paper_bgcolor='white',
        font=dict(color='#2c3e50')
    )
    
    # 調整網格線顏色，使其柔和不刺眼
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0', linecolor='#bdc3c7')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0', linecolor='#bdc3c7')

    return fig

# =====================
# 🚀 主應用程式
# =====================
st.title("🏹 股票狙擊手")

with st.sidebar:
    st.header("🛡️ 資訊中心設定")
    fm_token = st.text_input("FinMind Token", type="password", help="請輸入您的 FinMind API Token")
    st.divider()
    search_codes = st.text_area("🎯 狙擊個股清單 (代碼間隔)", "2330 2317 2454 3008 3231")
    analyze_btn = st.button("🚀 執行全局掃描", use_container_width=True)
    st.info("系統將自動掃描週線多頭、均線發散、MACD動能與鑽石眼型態。")

if analyze_btn:
    # 準備一個清單收集所有評分結果
    scan_results = []

    # --- 1. 大盤戰情區 ---
    st.subheader(" 🌐 台股加權指數 (TAIEX)")
    m_df = get_stock_data("TAIEX", fm_token)
    if m_df is not None:
        m_df = analyze_strategy(m_df)
        m_last = m_df.iloc[-1]
        
        # 指令邏輯
        score = m_last["score"]
        if score >= 80: 
            cmd, cmd_class = "🚀 強力買進", "buy-signal"
            risk_tip = "🔥 市場動能極強，順勢操作。"
        elif score >= 60: 
            cmd, cmd_class = "📈 分批買進", "buy-signal"
            risk_tip = "⚖️ 穩定上漲中，注意支撐位。"
        elif score >= 40: 
            cmd, cmd_class = "🤏 少量買進", "buy-signal"
            risk_tip = "⚠️ 處於震盪區，嚴格執行停損。"
        elif score >= 20: 
            cmd, cmd_class = "📉 分批賣出", "sell-signal"
            risk_tip = "🛑 趨勢轉弱，回收資金。"
        else: 
            cmd, cmd_class = "💀 強力賣出", "sell-signal"
            risk_tip = "🚨 極高風險，建議空手觀察。"

        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
            st.write(f"**大盤風險提示：** {risk_tip}")
        with col2:
            st.markdown(f"""<div class='status-card {cmd_class}'>指揮官指令：{cmd}</div>""", unsafe_allow_html=True)
        
        with st.expander("查看大盤詳細 K 線圖 (下拉式)"):
            st.plotly_chart(plot_advanced_chart(m_df, "大盤 TAIEX 指數走勢"), use_container_width=True)
    
    st.divider()

    # --- 2. 個股狙擊掃描 ---
    st.subheader("🎯 目標個股深度分析")
    codes = re.split(r'[\s\n,]+', search_codes.strip())
    stock_info = get_stock_info()
    
    for sid in codes:
        if not sid: continue
        with st.spinner(f"分析中 {sid}..."):
            df = get_stock_data(sid, fm_token)
            if df is None or len(df) < 200: 
                st.warning(f"代碼 {sid} 數據不足或無效。")
                continue
                
            df = analyze_strategy(df)
            last = df.iloc[-1]
            s_name = stock_info.loc[stock_info["stock_id"] == sid, "stock_name"].values[0] if sid in stock_info["stock_id"].values else "未知"
            industry = stock_info.loc[stock_info["stock_id"] == sid, "industry_category"].values[0] if sid in stock_info["stock_id"].values else "N/A"
            
            # 加入評分表資料庫
            scan_results.append({
                "代碼": sid,
                "名稱": s_name,
                "收盤價": last['close'],
                "分數": last['score'],
                "型態": last['pattern'],
                "位階": last['position_type'],
                "戰情提醒": last['warning'] if last['warning'] else "趨勢穩定中"
            })

            # 計算建議區間 (基於最新關鍵位)
            buy_range = f"{last['upward_key']:.2f} 突破點" if not pd.isna(last['upward_key']) else "等待成形"
            stop_loss = f"{last['downward_key']:.2f} 跌破點" if not pd.isna(last['downward_key']) else "等待成形"
            
            # 卡片顏色
            border = "#ff4b4b" if last["score"] >= 70 else "#28a745" if last["score"] <= 30 else "#adb5bd"
            
            st.markdown(f"""
            <div style="background: white; padding: 20px; border-left: 10px solid {border}; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); margin-bottom: 15px;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <span style="font-size: 24px; font-weight: bold;">{sid} {s_name} <small style="font-size:16px; color:#666;">({last['close']:.2f})</small></span>
                    <span style="background:{border}; color:white; padding:5px 15px; border-radius:20px;">評分: {last['score']}</span>
                </div>
                <div style="margin-top: 10px;">
                    <span class="info-tag tag-blue">類股: {industry}</span>
                    <span class="info-tag tag-purple">型態: {last['pattern']}</span>
                    <span class="info-tag" style="background:#fff4e6; color:#d9480f;">位置: {last['position_type']}</span>
                </div>
                <div style="margin-top: 15px; display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;">
                    <div>🎯 <b>上漲關鍵位(買點):</b> <br>{buy_range}</div>
                    <div>🛡️ <b>下跌關鍵位(賣點):</b> <br>{stop_loss}</div>
                    <div>🚩 <b>戰情提醒:</b> <br><span style="color:#d9480f;">{last['warning'] if last['warning'] else '趨勢穩定中'}</span></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.expander(f"查看 {sid} {s_name} 戰情圖表 (含關鍵位/扣抵/發動點)"):
                st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name} 狙擊分析"), use_container_width=True)

    # --- 3. 產生排行榜清單 ---
    if scan_results:
        st.divider()
        st.subheader("🏆 股票評分排行榜")
        
        # 轉換為 DataFrame 並依分數遞減排序
        results_df = pd.DataFrame(scan_results)
        results_df = results_df.sort_values(by="分數", ascending=False).reset_index(drop=True)
        
        # 顯示 Dataframe
        st.dataframe(
            results_df.style.format({"收盤價": "{:.2f}"}),
            use_container_width=True,
            hide_index=True
        )

st.sidebar.markdown("---")
st.sidebar.caption("股票狙擊手 2026/04/13  實戰精簡版")