import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
import plotly.graph_objects as go
import re

st.set_page_config(layout="wide", page_title="海海狙擊手 10.5 Pro", page_icon="🏹")

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================
# 🔹 輔助函數：計算連買天數
# =====================
def get_continuous_buy_days(df, investor_name):
    """
    計算特定法人的連續買超天數
    """
    if df.empty:
        return 0
    
    # 篩選該法人資料並按日期由新到舊排序
    investor_df = df[df["name"] == investor_name].sort_values("date", ascending=False)
    
    if investor_df.empty:
        return 0
    
    streak = 0
    for _, row in investor_df.iterrows():
        net_buy = row["buy"] - row["sell"]
        if net_buy > 0:
            streak += 1
        else:
            # 一旦遇到沒買超(賣超或平盤)就中斷天數計算
            break
    return streak

# =====================
# 🔹 股票名稱
# =====================
@st.cache_data(ttl=86400)
def get_stock_info():
    try:
        data = requests.get(BASE_URL, params={"dataset":"TaiwanStockInfo"}).json()["data"]
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

# =====================
# 🔹 API 數據抓取
# =====================
@st.cache_data(ttl=3600)
def get_price(sid, token):
    params = {
        "dataset":"TaiwanStockPrice",
        "data_id":sid,
        "start_date":(datetime.now()-timedelta(days=250)).strftime("%Y-%m-%d"),
        "token":token
    }
    try:
        data = requests.get(BASE_URL, params=params).json()["data"]
        df = pd.DataFrame(data)
        if df.empty: return None
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"max":"high","min":"low","trading_volume":"volume"})
        return df.sort_values("date")
    except:
        return None

@st.cache_data(ttl=3600)
def get_investor(sid, token):
    params = {
        "dataset":"TaiwanStockInstitutionalInvestorsBuySell",
        "data_id":sid,
        "start_date":(datetime.now()-timedelta(days=60)).strftime("%Y-%m-%d"),
        "token":token
    }
    try:
        data = requests.get(BASE_URL, params=params).json()["data"]
        return pd.DataFrame(data)
    except:
        return pd.DataFrame()

# =====================
# 🔹 策略邏輯
# =====================
def apply_strategy(df):
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma200"] = df["close"].rolling(200).mean()

    df["key_line"] = np.nan

    for i in range(1, len(df)):
        if df["ma5"].iloc[i-1] > df["ma10"].iloc[i-1] and df["ma5"].iloc[i] < df["ma10"].iloc[i]:
            df.loc[df.index[i], "key_line"] = df["high"].iloc[i]

    df["key_line"] = df["key_line"].ffill()

    df["signal"] = 0
    df["buy_price"] = np.nan
    df["stop"] = np.nan
    df["pattern"] = "震盪"

    for i in range(60, len(df)):
        row = df.iloc[i]
        ma_vals = [row["ma5"], row["ma10"], row["ma20"], row["ma60"]]
        gap = (max(ma_vals)-min(ma_vals))/row["close"]

        if gap < 0.02:
            df.loc[df.index[i],"pattern"] = "💎鑽石眼"
        elif row["close"] > row["ma60"]:
            df.loc[df.index[i],"pattern"] = "▼鑽石坑"
        elif row["close"] > row["ma20"]:
            df.loc[df.index[i],"pattern"] = "●黃金眼"

        if not pd.isna(row["key_line"]) and row["close"] > row["key_line"]:
            df.loc[df.index[i],"signal"] = 1
            df.loc[df.index[i],"buy_price"] = row["key_line"] * 1.005
            df.loc[df.index[i],"stop"] = row["ma20"]

    return df

# =====================
# 📊 圖表繪製
# =====================
def plot_chart(df, title):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="K線"
    ))

    for ma in [5, 10, 20, 60, 200]:
        fig.add_trace(go.Scatter(x=df["date"], y=df[f"ma{ma}"], name=f"MA{ma}", line=dict(width=1)))

    fig.add_trace(go.Scatter(
        x=df["date"], y=df["key_line"], name="關鍵密碼", line=dict(dash="dash", color="rgba(255, 0, 0, 0.5)")
    ))

    sig = df[df["signal"]==1]
    fig.add_trace(go.Scatter(
        x=sig["date"], y=sig["low"]*0.98,
        mode="markers", marker=dict(size=12, symbol="triangle-up", color="red"),
        name="買點訊號"
    ))

    fig.update_layout(height=500, title=title, xaxis_rangeslider_visible=False)
    return fig

# =====================
# 🚀 UI 與主程式
# =====================
st.title("🏹 海海狙擊手 10.5 強化版")

with st.sidebar:
    token = st.text_input("FinMind Token", type="password")
    symbols_input = st.text_area("股票代號（空格或換行隔開）", "2330 2317 2454")
    analyze_btn = st.button("🚀 開始分析")

# 解析股票代號
symbols = re.split(r'[\s\n]+', symbols_input.strip())
symbols = [s for s in symbols if s]
stock_info = get_stock_info()

if analyze_btn:
    if not token:
        st.error("請輸入 FinMind Token！")
    else:
        results = []

        for sid in symbols:
            df = get_price(sid, token)
            if df is None or len(df) < 100:
                continue

            df = apply_strategy(df)
            last_row = df.iloc[-1]

            # 股票名稱
            name_row = stock_info.loc[stock_info["stock_id"] == sid, "stock_name"]
            name = name_row.values[0] if not name_row.empty else "未知"

            # 籌碼計算：連買天數
            inv_data = get_investor(sid, token)
            foreign_streak = get_continuous_buy_days(inv_data, "Foreign_Investor")
            trust_streak = get_continuous_buy_days(inv_data, "Investment_Trust")

            action = "🔥可出手" if last_row["signal"] == 1 else "觀察"

            results.append({
                "股票代號": sid,
                "股票名稱": name,
                "收盤價": round(last_row["close"], 2),
                "型態": last_row["pattern"],
                "外資連買": f"{foreign_streak} 天",
                "投信連買": f"{trust_streak} 天",
                "建議行動": action,
                "買入參考": round(last_row["buy_price"], 2) if not np.isnan(last_row["buy_price"]) else "-",
                "停損參考": round(last_row["stop"], 2) if not np.isnan(last_row["stop"]) else "-"
            })

            st.subheader(f"📈 {sid} {name} | 當前建議：{action}")
            # 顯示即時籌碼狀況
            col1, col2 = st.columns(2)
            col1.metric("外資連續買超", f"{foreign_streak} 天")
            col2.metric("投信連續買超", f"{trust_streak} 天")
            
            st.plotly_chart(plot_chart(df.tail(120), f"{sid} {name}"), use_container_width=True)

        if results:
            st.divider()
            st.subheader("📊 多空狙擊總表")
            st.dataframe(pd.DataFrame(results), use_container_width=True)