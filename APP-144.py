# =========================================================
# 🎯 股票狙擊手 Pro Max V2
# 即時選股監控系統
# Version: Pro Max V2
# Author : ChatGPT AI
# =========================================================

import streamlit as st
import pandas as pd
import numpy as np
import requests
import twstock
import yfinance as yf
import plotly.graph_objects as go

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from plotly.subplots import make_subplots

# =========================================================
# ⚙️ 基本設定
# =========================================================

st.set_page_config(
    page_title="股票狙擊手 Pro Max V2",
    layout="wide",
    page_icon="🎯"
)

# =========================================================
# 🎨 CSS 美化
# =========================================================

st.markdown("""
<style>

.main {
    background-color: #0e1117;
    color: white;
}

div[data-testid="stMetric"] {
    background-color: #1e1e1e;
    padding: 15px;
    border-radius: 10px;
    border: 1px solid #333;
}

.red-card {
    background: linear-gradient(135deg,#ff1744,#ff5252);
    padding: 15px;
    border-radius: 15px;
    animation: pulse 2s infinite;
    color: white;
    margin-bottom: 10px;
}

@keyframes pulse {
    0% {box-shadow:0 0 0 0 rgba(255,82,82,.7);}
    70% {box-shadow:0 0 0 20px rgba(255,82,82,0);}
    100% {box-shadow:0 0 0 0 rgba(255,82,82,0);}
}

.log-box {
    background-color: black;
    color: #00ff66;
    padding: 15px;
    border-radius: 10px;
    font-family: monospace;
    height: 300px;
    overflow-y: scroll;
    border: 1px solid #00ff66;
}

.buy {
    color: #ff5252;
    font-weight: bold;
}

.sell {
    color: #00e676;
    font-weight: bold;
}

</style>
""", unsafe_allow_html=True)

# =========================================================
# 🔐 Sidebar
# =========================================================

st.sidebar.title("⚙️ 系統控制台")

finmind_token = st.sidebar.text_input(
    "FinMind Token",
    type="password",
    value=st.secrets.get("FINMIND_TOKEN", "")
)

discord_webhook = st.sidebar.text_input(
    "Discord Webhook",
    type="password",
    value=st.secrets.get("DISCORD_WEBHOOK", "")
)

auto_refresh = st.sidebar.checkbox("🔄 自動監控", value=False)

discord_enable = st.sidebar.checkbox("📢 Discord 通知", value=True)

manual_scan = st.sidebar.button("🚀 開始掃描")

stock_input = st.sidebar.text_input("🔍 個股快查", "2330")

sync_button = st.sidebar.button("☁️ 同步雲端清單")

# =========================================================
# ☁️ Google Sheets 同步
# =========================================================

GOOGLE_SHEET_CSV = st.secrets.get("GOOGLE_SHEET_CSV", "")

def load_watchlist():

    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV)
        return df["stock_id"].astype(str).tolist()

    except:
        return [
            "2330","2317","2454","2303","3017",
            "2603","2382","3661","3443","3037",
            "1519","8046","3227","3260","4979"
        ]

# =========================================================
# 📊 FinMind 資料
# =========================================================

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

def get_stock_data(stock_id):

    end_date = datetime.today()
    start_date = end_date - timedelta(days=700)

    params = {
        "dataset": "TaiwanStockPrice",
        "data_id": stock_id,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "token": finmind_token
    }

    try:

        res = requests.get(BASE_URL, params=params, timeout=15)
        data = res.json()["data"]

        df = pd.DataFrame(data)

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date")

        return df

    except Exception as e:

        st.error(f"{stock_id} 下載失敗 {e}")
        return pd.DataFrame()

# =========================================================
# ⚡ 即時報價
# =========================================================

def get_realtime(stock_id):

    try:

        rt = twstock.realtime.get(stock_id)

        if rt["success"]:

            latest_price = float(rt["realtime"]["latest_trade_price"] or 0)

            volume = int(float(rt["realtime"]["accumulate_trade_volume"] or 0) * 1000)

            return latest_price, volume

    except:
        pass

    return None, None

# =========================================================
# 📈 技術指標
# =========================================================

def add_indicators(df):

    ma_list = [5,10,20,55,60,144,200]

    for ma in ma_list:
        df[f"MA{ma}"] = df["close"].rolling(ma).mean()

    # MACD
    ema12 = df["close"].ewm(span=12).mean()
    ema26 = df["close"].ewm(span=26).mean()

    df["MACD"] = ema12 - ema26
    df["Signal"] = df["MACD"].ewm(span=9).mean()
    df["Hist"] = df["MACD"] - df["Signal"]

    # ATR
    high_low = df["max"] - df["min"]
    high_close = np.abs(df["max"] - df["close"].shift())
    low_close = np.abs(df["min"] - df["close"].shift())

    ranges = pd.concat([high_low, high_close, low_close], axis=1)

    true_range = np.max(ranges, axis=1)

    df["ATR"] = true_range.rolling(14).mean()

    return df

# =========================================================
# 💎 VCP 壓縮
# =========================================================

def detect_vcp(df):

    recent = df.tail(20)

    hl_range = (recent["max"].max() - recent["min"].min()) / recent["close"].mean()

    ma_distance = abs(
        recent["MA5"].iloc[-1] -
        recent["MA10"].iloc[-1]
    ) / recent["close"].iloc[-1]

    return hl_range < 0.12 and ma_distance < 0.03

# =========================================================
# 🚀 噴發第一根
# =========================================================

def detect_breakout(df):

    if len(df) < 30:
        return False

    last = df.iloc[-1]

    cond1 = last["close"] > last["MA20"]
    cond2 = last["Trading_Volume"] > df["Trading_Volume"].rolling(20).mean().iloc[-1] * 1.8

    recent_high = df["close"].rolling(20).max().shift(1).iloc[-1]

    cond3 = last["close"] > recent_high

    return cond1 and cond2 and cond3

# =========================================================
# ⭐ 黃金眼
# =========================================================

def detect_golden_eye(df):

    if len(df) < 30:
        return False

    last = df.iloc[-1]

    cond1 = last["MA5"] > last["MA10"] > last["MA20"]

    cond2 = last["close"] > last["MA5"]

    cond3 = last["Hist"] > 0

    return cond1 and cond2 and cond3

# =========================================================
# 📊 評分系統
# =========================================================

def calculate_score(df):

    score = 50

    last = df.iloc[-1]

    # 站上均線
    if last["close"] > last["MA5"]:
        score += 12

    if last["close"] > last["MA10"]:
        score += 10

    if last["close"] > last["MA20"]:
        score += 10

    # 多頭排列
    if last["MA5"] > last["MA10"] > last["MA20"]:
        score += 15

    # MACD
    if last["Hist"] > 0:
        score += 8

    # VCP
    if detect_vcp(df):
        score += 5

    # 噴發
    if detect_breakout(df):
        score += 20

    # 跌破均線
    if last["close"] < last["MA5"]:
        score -= 20

    if last["close"] < last["MA10"]:
        score -= 20

    return max(0, min(score, 100))

# =========================================================
# 🧠 市場風險控管
# =========================================================

def market_score():

    try:

        twii = yf.download("^TWII", period="6mo", progress=False)

        twii["MA20"] = twii["Close"].rolling(20).mean()

        last = twii.iloc[-1]

        score = 50

        if last["Close"] > last["MA20"]:
            score += 20
        else:
            score -= 20

        return score

    except:
        return 50

# =========================================================
# 📢 Discord 通知
# =========================================================

def send_discord(msg):

    if not discord_enable:
        return

    if discord_webhook == "":
        return

    try:

        requests.post(
            discord_webhook,
            json={"content": msg},
            timeout=10
        )

    except:
        pass

# =========================================================
# 📈 Plotly K線圖
# =========================================================

def plot_chart(df, stock_id):

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7,0.3]
    )

    # K線
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["max"],
            low=df["min"],
            close=df["close"],
            name="K"
        ),
        row=1,
        col=1
    )

    # MA
    ma_colors = {
        5:"yellow",
        10:"orange",
        20:"cyan",
        55:"green",
        60:"white"
    }

    for ma,color in ma_colors.items():

        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df[f"MA{ma}"],
                mode="lines",
                name=f"MA{ma}",
                line=dict(color=color,width=2)
            ),
            row=1,
            col=1
        )

    # MACD
    fig.add_trace(
        go.Bar(
            x=df["date"],
            y=df["Hist"],
            name="MACD Hist"
        ),
        row=2,
        col=1
    )

    # 標記
    if detect_breakout(df):

        fig.add_annotation(
            x=df["date"].iloc[-1],
            y=df["close"].iloc[-1],
            text="🚀",
            showarrow=True,
            row=1,
            col=1
        )

    if detect_golden_eye(df):

        fig.add_annotation(
            x=df["date"].iloc[-1],
            y=df["close"].iloc[-1]*0.98,
            text="⭐",
            showarrow=True,
            row=1,
            col=1
        )

    fig.update_layout(
        height=700,
        template="plotly_dark",
        title=f"{stock_id} 技術分析"
    )

    return fig

# =========================================================
# 🎯 主分析
# =========================================================

def analyze_stock(stock_id):

    try:

        df = get_stock_data(stock_id)

        if len(df) < 100:
            return None

        # 即時資料
        rt_price, rt_volume = get_realtime(stock_id)

        if rt_price:
            df.loc[df.index[-1], "close"] = rt_price

        if rt_volume:
            df.loc[df.index[-1], "Trading_Volume"] = rt_volume

        df = add_indicators(df)

        score = calculate_score(df)

        breakout = detect_breakout(df)

        golden = detect_golden_eye(df)

        atr = df["ATR"].iloc[-1]

        risk = min(max((1 / atr) * 10, 3), 20)

        return {
            "stock_id": stock_id,
            "score": score,
            "breakout": breakout,
            "golden": golden,
            "risk": round(risk,1),
            "df": df
        }

    except Exception as e:

        return None

# =========================================================
# 📋 市場總覽
# =========================================================

market = market_score()

col1,col2,col3 = st.columns(3)

with col1:
    st.metric("📊 大盤評分", market)

with col2:

    if market >= 60:
        st.metric("市場位階","多頭")
    elif market <= 40:
        st.metric("市場位階","空頭")
    else:
        st.metric("市場位階","盤整")

with col3:

    if market < 40:
        st.error("⚠️ 避險暫緩買入")
    else:
        st.success("✅ 可正常監控")

# =========================================================
# 🚀 開始掃描
# =========================================================

if manual_scan or auto_refresh:

    watchlist = load_watchlist()

    results = []

    logs = []

    progress = st.progress(0)

    with ThreadPoolExecutor(max_workers=10) as executor:

        futures = []

        for s in watchlist:
            futures.append(executor.submit(analyze_stock, s))

        for idx, future in enumerate(futures):

            r = future.result()

            if r:

                results.append(r)

                if r["score"] >= 80:

                    log = f"""
[{datetime.now().strftime('%H:%M:%S')}]
{r['stock_id']}
BUY SIGNAL
Score: {r['score']}
"""

                    logs.append(log)

                    send_discord(log)

            progress.progress((idx+1)/len(futures))

    # =====================================================
    # 🎯 狙擊卡片
    # =====================================================

    st.header("🎯 狙擊名單")

    for r in sorted(results, key=lambda x:x["score"], reverse=True):

        if r["score"] >= 80:

            st.markdown(f"""
            <div class='red-card'>
            <h2>🚀 {r['stock_id']}</h2>
            <h3>Score: {r['score']}</h3>
            <h4>建議持倉: {r['risk']}%</h4>
            </div>
            """, unsafe_allow_html=True)

            with st.expander(f"📈 {r['stock_id']} 詳細圖表"):

                fig = plot_chart(r["df"], r["stock_id"])

                st.plotly_chart(fig, use_container_width=True)

    # =====================================================
    # 📜 戰情日誌
    # =====================================================

    st.header("📜 戰情日誌")

    log_text = "\n".join(logs)

    st.markdown(
        f"<div class='log-box'>{log_text}</div>",
        unsafe_allow_html=True
    )

# =========================================================
# 🔍 個股快查
# =========================================================

if stock_input:

    st.header(f"🔍 個股快查 {stock_input}")

    r = analyze_stock(stock_input)

    if r:

        col1,col2,col3,col4 = st.columns(4)

        with col1:
            st.metric("評分", r["score"])

        with col2:
            st.metric("突破", "YES" if r["breakout"] else "NO")

        with col3:
            st.metric("黃金眼", "YES" if r["golden"] else "NO")

        with col4:
            st.metric("建議倉位", f"{r['risk']}%")

        fig = plot_chart(r["df"], stock_input)

        st.plotly_chart(fig, use_container_width=True)

# =========================================================
# 🔄 Auto Refresh
# =========================================================

if auto_refresh:

    import time

    time.sleep(30)

    st.rerun()
