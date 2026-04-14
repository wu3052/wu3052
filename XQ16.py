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
# 🔹 數據獲取模組 (Token 從 Secrets 讀取)
# =====================

# 從 Secrets 安全獲取 Token
FM_TOKEN = st.secrets.get("FINMIND_TOKEN", "")

@st.cache_data(ttl=3600)
def get_stock_data(sid, token, days=1200): 
    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": sid,
        "start_date": (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d"),
        "token": token
    }
    try:
        res = requests.get(BASE_URL, params=params, timeout=10).json()
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
        res = requests.get(BASE_URL, params={"dataset": "TaiwanStockInfo"}, timeout=10)
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
    
    # 模擬 60分K 144MA (約等於日線 36MA)
    df["ma144_60min"] = df["close"].rolling(36).mean()
    
    # 2. 週線檢查
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

    # 5. 量能分析
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma5"].replace(0, np.nan)
    
    # 6. 關鍵位判定
    df["dc_signal"] = (df["ma5"] < df["ma10"]) & (df["ma5"].shift(1) >= df["ma10"].shift(1))
    df["gc_signal"] = (df["ma5"] > df["ma10"]) & (df["ma5"].shift(1) <= df["ma10"].shift(1))

    df["upward_key"] = np.nan
    df["downward_key"] = np.nan
    df.loc[df["dc_signal"], "upward_key"] = df["close"]
    df.loc[df["gc_signal"], "downward_key"] = df["close"]
    df["upward_key"] = df["upward_key"].ffill()
    df["downward_key"] = df["downward_key"].ffill()

    # 7. 關鍵轉折點標記
    df["star_signal"] = False
    for i in range(1, len(df)):
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

    warnings = []
    if row["close"] > row["ma144_60min"] and prev_row["close"] <= prev_row["ma144_60min"]: warnings.append("🚀 站上60分144MA(買點)")
    elif row["close"] < row["ma144_60min"] and prev_row["close"] >= prev_row["ma144_60min"]: warnings.append("🩸 跌破60分144MA(賣點)")
    if row["close"] > row["ma5"] and prev_row["close"] <= prev_row["ma5"]: warnings.append("🏹 站上5MA(買點)")
    elif row["close"] < row["ma5"] and prev_row["close"] >= prev_row["ma5"]: warnings.append("⚠️ 跌破5MA(注意賣點)")
    if row["close"] > row["ma10"] and prev_row["close"] <= prev_row["ma10"]: warnings.append("🔍 站上10MA(注意買點)")
    elif row["close"] < row["ma10"] and prev_row["close"] >= prev_row["ma10"]: warnings.append("🚨 跌破10MA(賣點)")

    if row["vol_ratio"] > 2.0: warnings.append("🔥 量能爆發(2倍均量)")
    elif row["vol_ratio"] > 1.5: warnings.append("⚡ 攻擊帶量")
    if row["hist"] > 0 and row["hist"] < prev_row["hist"]: warnings.append("🎯 目標達成/紅柱縮短")
    if row["bias_20"] > 10: warnings.append("⚠️ 乖離過高")
    elif row["bias_20"] < -10: warnings.append("📉 乖離過低")
    
    df.at[last_idx, "warning"] = " | ".join(warnings) if warnings else "趨勢穩定中"

    score_bonus = 5 if row["vol_ratio"] > 1.2 else 0
    if row["close"] > row["ma200"] and row["ma5"] > row["ma60"]:
        df.at[last_idx, "position_type"] = "超級噴發位" if row["bias_20"] > 8 else "主升段確認位"
        df.at[last_idx, "score"] = 85 + score_bonus
    elif row["close"] > row["ma20"] and row["close"] < row["ma60"]:
        df.at[last_idx, "position_type"] = "底部起漲位"
        df.at[last_idx, "score"] = 70 + score_bonus
    elif row["star_signal"]:
        df.at[last_idx, "position_type"] = "起漲發動位"
        df.at[last_idx, "score"] = 80 + score_bonus

    df["pattern"] = "一般盤整"
    ma_diff = (max(row["ma5"], row["ma10"], row["ma20"]) - min(row["ma5"], row["ma10"], row["ma20"])) / row["close"]
    if ma_diff < 0.015: df.at[last_idx, "pattern"] = "💎 鑽石眼"
    elif row["ma5"] > row["ma10"] > row["ma20"]: df.at[last_idx, "pattern"] = "📐 黃金三角眼"
    elif row["low"] < row["ma20"] and row["close"] > row["ma20"]: df.at[last_idx, "pattern"] = "🕳️ 鑽石坑"

    return df

# =====================
# 📊 圖表繪製模組
# =====================
def plot_advanced_chart(df, title=""):
    df_plot = df.tail(100).copy()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])

    fig.add_trace(go.Candlestick(
        x=df_plot["date"], open=df_plot["open"], high=df_plot["high"], 
        low=df_plot["low"], close=df_plot["close"], name="K線",
        increasing_line_color='#eb4d4b', increasing_fillcolor='#eb4d4b', 
        decreasing_line_color='#2ecc71', decreasing_fillcolor='#2ecc71'
    ), row=1, col=1)

    ma_colors = {5: '#2980b9', 10: '#f1c40f', 20: '#e67e22', 60: '#9b59b6', 200: '#34495e'}
    for ma, color in ma_colors.items():
        fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot[f"ma{ma}"], name=f"{ma}MA", line=dict(color=color, width=1.5)), row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["upward_key"], name="上漲關鍵位", line=dict(color='rgba(235,77,75,0.5)', dash='dash')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot["date"], y=df_plot["downward_key"], name="下跌關鍵位", line=dict(color='rgba(46,204,113,0.5)', dash='dash')), row=1, col=1)

    stars = df_plot[df_plot["star_signal"]]
    fig.add_trace(go.Scatter(x=stars["date"], y=stars["low"] * 0.98, mode="markers", marker=dict(symbol="star", size=14, color="#FFD700"), name="發動點"), row=1, col=1)

    colors = ['#eb4d4b' if val >= 0 else '#2ecc71' for val in df_plot["hist"]]
    fig.add_trace(go.Bar(x=df_plot["date"], y=df_plot["hist"], name="MACD", marker_color=colors), row=2, col=1)

    fig.update_layout(title=title, height=700, template="plotly_white", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=50, b=10))
    fig.update_xaxes(showgrid=True, gridcolor='#f0f0f0')
    fig.update_yaxes(showgrid=True, gridcolor='#f0f0f0')
    return fig

# =====================
# 🚀 主應用程式
# =====================
st.title("🏹 股票狙擊手")

with st.sidebar:
    st.header("🛡️ 資訊中心設定")
    if not FM_TOKEN:
        st.error("⚠️ 未在 Secrets 中找到 FinMind Token")
    else:
        st.success("✅ Token 已從 Secrets 載入")
    
    st.divider()
    
    search_codes = st.text_area("🎯 狙擊個股清單 (代碼間隔)", value="", help="重新整理後將清除輸入內容")
    inventory_codes = st.text_area("📦 庫存股清單 (代碼間隔)", value="6257 2303 8028 2811 8374 3019 6188 6727 6643 2382 00679B")
    
    analyze_btn = st.button("🚀 執行全局掃描", use_container_width=True)
    st.info("系統掃描：週線多頭、均線發散、MACD動能、成交量與進場提醒。")

if analyze_btn:
    if not FM_TOKEN:
        st.error("請先在 Secrets 中設定 FINMIND_TOKEN。")
    else:
        scan_results = []

        # --- 1. 大盤戰情區 ---
        st.subheader(" 🌐 台股加權指數 (TAIEX)")
        m_df = get_stock_data("TAIEX", FM_TOKEN)
        if m_df is not None:
            m_df = analyze_strategy(m_df)
            m_last = m_df.iloc[-1]
            
            score = m_last["score"]
            if score >= 80: cmd, cmd_class, risk_tip = "🚀 強力買進", "buy-signal", "🔥 市場動能極強。"
            elif score >= 60: cmd, cmd_class, risk_tip = "📈 分批買進", "buy-signal", "⚖️ 穩定上漲中。"
            elif score >= 40: cmd, cmd_class, risk_tip = "🤏 少量買進", "buy-signal", "⚠️ 處於震盪區。"
            elif score >= 20: cmd, cmd_class, risk_tip = "📉 分批賣出", "sell-signal", "🛑 趨勢轉弱。"
            else: cmd, cmd_class, risk_tip = "💀 強力賣出", "sell-signal", "🚨 極高風險。"

            col1, col2 = st.columns([1, 2])
            with col1:
                st.metric("加權指數", f"{m_last['close']:.2f}", f"{m_last['close']-m_df.iloc[-2]['close']:.2f}")
                st.write(f"**大盤風險提示：** {risk_tip}")
            with col2:
                st.markdown(f"""<div class='status-card {cmd_class}'>指揮官指令：{cmd}</div>""", unsafe_allow_html=True)
            with st.expander("查看大盤詳細走勢"):
                st.plotly_chart(plot_advanced_chart(m_df, "大盤 TAIEX 指數走勢"), use_container_width=True)
        
        st.divider()

        # --- 2. 個股狙擊掃描 ---
        raw_codes = (search_codes + " " + inventory_codes).strip()
        combined_codes = [c for c in re.split(r'[\s\n,]+', raw_codes) if c]
        
        stock_info = get_stock_info()
        
        for sid in combined_codes:
            with st.spinner(f"分析中 {sid}..."):
                df = get_stock_data(sid, FM_TOKEN)
                if df is None or len(df) < 200: continue
                    
                df = analyze_strategy(df)
                last = df.iloc[-1]
                
                s_row = stock_info[stock_info["stock_id"] == sid]
                s_name = s_row["stock_name"].values[0] if not s_row.empty else "未知"
                industry = s_row["industry_category"].values[0] if not s_row.empty else "N/A"
                
                scan_results.append({
                    "代碼": sid, "名稱": s_name, "收盤價": last['close'],
                    "分數": last['score'], "型態": last['pattern'],
                    "位階": last['position_type'], "戰情提醒": last['warning']
                })

                border = "#ff4b4b" if last["score"] >= 75 else "#28a745" if last["score"] <= 30 else "#adb5bd"
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
                        <div>🎯 <b>關鍵位建議:</b> <br>{last['upward_key']:.2f} 突破 / {last['downward_key']:.2f} 跌破</div>
                        <div>🚩 <b>即時戰情:</b> <br><span style="color:#d9480f; font-weight:bold;">{last['warning']}</span></div>
                        <div>📊 <b>量能狀態:</b> <br>{last['vol_ratio']:.2f} 倍均量</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                with st.expander(f"查看 {sid} {s_name} 戰情圖表"):
                    st.plotly_chart(plot_advanced_chart(df, f"{sid} {s_name} 狙擊分析"), use_container_width=True)

        # --- 3. 產生排行榜清單 ---
        if scan_results:
            st.divider()
            st.subheader("🏆 綜合評分排行榜 (含庫存與狙擊)")
            results_df = pd.DataFrame(scan_results).sort_values(by="分數", ascending=False).reset_index(drop=True)
            st.dataframe(results_df.style.format({"收盤價": "{:.2f}"}), use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
st.sidebar.caption("股票狙擊手 2026/04/15 實戰精簡版")