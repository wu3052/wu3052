```python
import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import twstock
import requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import time

# =========================================================
# 基本設定
# =========================================================

st.set_page_config(
    page_title="股票狙擊手 Ultimate Pro",
    layout="wide",
    page_icon="🔥"
)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =========================================================
# CSS
# =========================================================

st.markdown("""
<style>
.main {
    background-color: #f5f5f5;
}

.block-container {
    padding-top: 1rem;
}

.stock-card {
    background: white;
    padding: 20px;
    border-radius: 15px;
    margin-bottom: 15px;
    border-left: 10px solid #ff4b4b;
    box-shadow: 0 2px 10px rgba(0,0,0,0.08);
}

.rank-sss {
    background: #ff4b4b;
    color: white;
    padding: 3px 10px;
    border-radius: 20px;
}

.rank-ss {
    background: orange;
    color: white;
    padding: 3px 10px;
    border-radius: 20px;
}

.rank-s {
    background: #2ecc71;
    color: white;
    padding: 3px 10px;
    border-radius: 20px;
}

.rank-a {
    background: #3498db;
    color: white;
    padding: 3px 10px;
    border-radius: 20px;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# 工具函數
# =========================================================

def get_tw_time():
    return datetime.utcnow() + timedelta(hours=8)


def get_yf_symbol(code):

    code = str(code)

    if code.startswith(("3", "5", "6", "8")):
        return f"{code}.TWO"

    return f"{code}.TW"


# =========================================================
# 建立股票池
# =========================================================

@st.cache_data(ttl=3600)
def build_stock_pool():

    pool = []

    for code, info in twstock.codes.items():

        if len(code) != 4:
            continue

        if info.type != "股票":
            continue

        pool.append(code)

    return sorted(pool)


# =========================================================
# 取得歷史資料
# =========================================================

@st.cache_data(ttl=14400)
def get_history_data(code):

    try:

        ticker = get_yf_symbol(code)

        df = yf.download(
            ticker,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=False
        )

        if df.empty:
            return None

        # 修正 MultiIndex 問題
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.columns = [str(c).lower() for c in df.columns]

        df = df.rename(columns={
            "adj close": "adj_close"
        })

        required_cols = [
            "open",
            "high",
            "low",
            "close",
            "volume"
        ]

        for col in required_cols:
            if col not in df.columns:
                return None

        df = df.dropna()

        return df

    except:
        return None


# =========================================================
# 即時資料
# =========================================================

@st.cache_data(ttl=15)
def get_realtime_data(code):

    try:

        data = twstock.realtime.get(code)

        if not data["success"]:
            return None

        real = data["realtime"]

        price = real.get("latest_trade_price")

        if price == "-":
            return None

        return {
            "price": float(price),
            "volume": int(real["accumulate_trade_volume"]) * 1000
        }

    except:
        return None


# =========================================================
# FinMind 籌碼
# =========================================================

@st.cache_data(ttl=43200)
def get_chip_data(code, token):

    try:

        res = requests.get(
            BASE_URL,
            params={
                "dataset": "InstitutionalInvestorsBuySell",
                "data_id": code,
                "start_date": (
                    datetime.now() - timedelta(days=30)
                ).strftime("%Y-%m-%d"),
                "token": token
            },
            timeout=10
        ).json()

        data = res.get("data", [])

        if not data:
            return None

        df = pd.DataFrame(data)

        if df.empty:
            return None

        foreign = df[df["name"] == "Foreign_Investor"]

        foreign_buy = foreign["buy_sell"].tail(3).sum()

        return {
            "foreign_buy": foreign_buy
        }

    except:
        return None


# =========================================================
# 技術分析
# =========================================================

def analyze_stock(df):

    try:

        if df is None:
            return None

        if len(df) < 200:
            return None

        # =====================================================
        # 均線
        # =====================================================

        for ma in [5, 10, 20, 60, 200]:
            df[f"ma{ma}"] = df["close"].rolling(ma).mean()

        # =====================================================
        # 量能
        # =====================================================

        df["vol_ma5"] = df["volume"].rolling(5).mean()

        df["vol_ratio"] = (
            df["volume"] /
            df["vol_ma5"]
        )

        # =====================================================
        # MACD
        # =====================================================

        exp1 = df["close"].ewm(span=12).mean()
        exp2 = df["close"].ewm(span=26).mean()

        df["macd"] = exp1 - exp2
        df["signal"] = df["macd"].ewm(span=9).mean()

        # =====================================================
        # KD
        # =====================================================

        low_9 = df["low"].rolling(9).min()
        high_9 = df["high"].rolling(9).max()

        rsv = (
            (df["close"] - low_9)
            /
            (high_9 - low_9)
        ) * 100

        df["k"] = rsv.ewm(com=2).mean()
        df["d"] = df["k"].ewm(com=2).mean()

        # =====================================================
        # 平台突破
        # =====================================================

        df["box_high"] = df["high"].rolling(20).max()

        df["break_box"] = (
            (df["close"] > df["box_high"].shift(1))
            &
            (df["vol_ratio"] > 1.5)
        )

        # =====================================================
        # VCP
        # =====================================================

        df["range"] = (
            (df["high"] - df["low"])
            /
            df["close"]
        )

        df["vcp"] = (
            df["range"].rolling(5).mean()
            <
            df["range"].rolling(20).mean() * 0.7
        )

        # =====================================================
        # 量縮吸籌
        # =====================================================

        df["vol_contract"] = (
            df["volume"].rolling(5).mean()
            <
            df["volume"].rolling(20).mean() * 0.7
        )

        # =====================================================
        # Relative Strength
        # =====================================================

        df["rs"] = (
            df["close"]
            /
            df["close"].shift(20)
        )

        # =====================================================
        # 洗盤
        # =====================================================

        df["washout"] = (
            (df["low"] < df["low"].shift(1))
            &
            (df["close"] > df["open"])
            &
            (df["volume"] < df["vol_ma5"])
        )

        # =====================================================
        # 危險爆量
        # =====================================================

        df["danger"] = (
            (df["volume"] > df["vol_ma5"] * 2)
            &
            (df["close"] < df["open"])
        )

        # =====================================================
        # 最新資料
        # =====================================================

        row = df.iloc[-1]
        prev = df.iloc[-2]

        score = 0

        signals = []

        # =====================================================
        # 評分
        # =====================================================

        if row["ma5"] > row["ma10"] > row["ma20"]:
            score += 15
            signals.append("多頭排列")

        if row["close"] > row["ma200"]:
            score += 10
            signals.append("站上年線")

        if row["break_box"]:
            score += 25
            signals.append("平台突破")

        if row["vcp"]:
            score += 20
            signals.append("VCP")

        if row["vol_contract"]:
            score += 15
            signals.append("量縮吸籌")

        if row["washout"]:
            score += 15
            signals.append("洗盤")

        if row["rs"] > 1.15:
            score += 20
            signals.append("Relative Strength")

        if row["macd"] > row["signal"]:
            score += 10
            signals.append("MACD翻紅")

        kd_cross = (
            prev["k"] <= prev["d"]
            and
            row["k"] > row["d"]
        )

        if kd_cross:
            score += 10
            signals.append("KD金叉")

        if row["danger"]:
            score -= 30
            signals.append("危險爆量")

        # =====================================================
        # 階段
        # =====================================================

        stage = "觀察"

        if row["vol_contract"] and row["vcp"]:
            stage = "吸籌"

        if row["break_box"]:
            stage = "發動"

        if row["ma5"] > row["ma10"] > row["ma20"]:
            stage = "主升"

        if row["danger"]:
            stage = "出貨"

        # =====================================================
        # 等級
        # =====================================================

        rank = "B"

        if score >= 90:
            rank = "SSS"

        elif score >= 80:
            rank = "SS"

        elif score >= 70:
            rank = "S"

        elif score >= 60:
            rank = "A"

        return {
            "score": score,
            "rank": rank,
            "stage": stage,
            "signals": " | ".join(signals),
            "close": round(float(row["close"]), 2),
            "vol_ratio": round(float(row["vol_ratio"]), 2),
            "break_box": bool(row["break_box"])
        }

    except:
        return None


# =========================================================
# 畫圖
# =========================================================

def plot_chart(df, title):

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3]
    )

    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="K線"
        ),
        row=1,
        col=1
    )

    for ma in [5, 10, 20, 60, 200]:

        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[f"ma{ma}"],
                name=f"{ma}MA"
            ),
            row=1,
            col=1
        )

    fig.add_trace(
        go.Bar(
            x=df.index,
            y=df["volume"],
            name="成交量"
        ),
        row=2,
        col=1
    )

    fig.update_layout(
        title=title,
        height=700,
        xaxis_rangeslider_visible=False
    )

    return fig


# =========================================================
# UI
# =========================================================

st.title("🔥 股票狙擊手 Ultimate Pro")

with st.sidebar:

    st.header("系統設定")

    finmind_token = st.text_input(
        "FinMind Token",
        type="password"
    )

    max_scan = st.slider(
        "掃描股票數量",
        50,
        1000,
        200
    )

    only_strong = st.checkbox(
        "只顯示 S 級以上",
        value=True
    )

    start_scan = st.button("🚀 開始掃描")


# =========================================================
# 主程式
# =========================================================

if start_scan:

    st.info("開始掃描股票...")

    stock_pool = build_stock_pool()

    stock_pool = stock_pool[:max_scan]

    progress = st.progress(0)

    results = []

    for idx, code in enumerate(stock_pool):

        progress.progress(
            (idx + 1) / len(stock_pool)
        )

        try:

            df = get_history_data(code)

            if df is None:
                continue

            result = analyze_stock(df)

            if result is None:
                continue

            # 分數太低跳過
            if result["score"] < 30:
                continue

            # FinMind 籌碼
            if result["score"] >= 75 and finmind_token:

                chip = get_chip_data(
                    code,
                    finmind_token
                )

                if chip:

                    if chip["foreign_buy"] > 0:

                        result["score"] += 10

                        result["signals"] += " | 外資買超"

            stock = twstock.codes.get(code)

            result["code"] = code

            result["name"] = (
                stock.name
                if stock
                else "未知"
            )

            results.append(result)

        except:
            continue

    # =====================================================
    # 排序
    # =====================================================

    results = sorted(
        results,
        key=lambda x: x.get("score", 0),
        reverse=True
    )

    df_result = pd.DataFrame(results)

    # =====================================================
    # 防呆
    # =====================================================

    if df_result.empty:

        st.warning("⚠️ 目前沒有符合條件的股票")

    else:

        # 強勢股過濾
        if only_strong and "score" in df_result.columns:

            df_result = df_result[
                df_result["score"] >= 70
            ]

        st.success(
            f"✅ 掃描完成，共找到 {len(df_result)} 檔"
        )

        show_cols = [
            "code",
            "name",
            "score",
            "rank",
            "stage",
            "close",
            "vol_ratio",
            "signals"
        ]

        valid_cols = [
            c for c in show_cols
            if c in df_result.columns
        ]

        st.dataframe(
            df_result[valid_cols],
            use_container_width=True
        )

        # =================================================
        # 顯示圖表
        # =================================================

        st.divider()

        st.subheader("📈 技術圖表")

        top_10 = df_result.head(10)

        for _, row in top_10.iterrows():

            code = row["code"]

            name = row["name"]

            df = get_history_data(code)

            if df is None:
                continue

            # 重新計算均線
            for ma in [5, 10, 20, 60, 200]:
                df[f"ma{ma}"] = df["close"].rolling(ma).mean()

            with st.expander(
                f"{code} {name} | 評分 {row['score']}"
            ):

                st.plotly_chart(
                    plot_chart(
                        df.tail(120),
                        f"{code} {name}"
                    ),
                    use_container_width=True
                )

else:

    st.info("請點擊左側『開始掃描』")
```
