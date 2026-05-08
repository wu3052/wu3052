import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import twstock
import requests
from datetime import datetime, timedelta

# =====================================================
# 基本設定
# =====================================================

st.set_page_config(
    page_title="主力潛伏股偵測系統",
    layout="wide",
    page_icon="🧠"
)

BASE_URL = "https://api.finmindtrade.com/api/v4/data"

# =====================================================
# 股票池
# =====================================================

@st.cache_data(ttl=3600)
def stock_pool():

    pool = []

    for code, info in twstock.codes.items():

        if len(code) == 4 and info.type == "股票":
            pool.append(code)

    return pool

# =====================================================
# Yahoo Finance
# =====================================================

def get_symbol(code):

    if code.startswith(("3","5","6","8")):
        return f"{code}.TWO"

    return f"{code}.TW"

@st.cache_data(ttl=14400)
def get_data(code):

    try:

        df = yf.download(
            get_symbol(code),
            period="1y",
            interval="1d",
            progress=False
        )

        if df.empty:
            return None

        df.columns = [c.lower() for c in df.columns]

        return df.dropna()

    except:
        return None

# =====================================================
# 籌碼（FinMind）
# =====================================================

@st.cache_data(ttl=43200)
def get_chip(code, token):

    try:

        res = requests.get(
            BASE_URL,
            params={
                "dataset": "InstitutionalInvestorsBuySell",
                "data_id": code,
                "start_date": (
                    datetime.now() - timedelta(days=20)
                ).strftime("%Y-%m-%d"),
                "token": token
            }
        ).json()

        df = pd.DataFrame(res.get("data", []))

        if df.empty:
            return None

        foreign = df[df["name"] == "Foreign_Investor"]

        return {
            "buy": foreign["buy_sell"].sum()
        }

    except:
        return None

# =====================================================
# 主力潛伏股判斷
# =====================================================

def detect_accumulation(df):

    if df is None or len(df) < 120:
        return None

    # =========================
    # 均線
    # =========================

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma60"] = df["close"].rolling(60).mean()

    # =========================
    # 量能壓縮
    # =========================

    df["vol_ma20"] = df["volume"].rolling(20).mean()

    vol_contract = df["volume"].iloc[-1] < df["vol_ma20"].iloc[-1] * 0.7

    # =========================
    # 波動收斂
    # =========================

    df["range"] = (df["high"] - df["low"]) / df["close"]

    vcp = df["range"].rolling(10).mean().iloc[-1] < \
          df["range"].rolling(30).mean().iloc[-1] * 0.7

    # =========================
    # 價格收斂（區間壓縮）
    # =========================

    high20 = df["high"].rolling(20).max().iloc[-1]
    low20 = df["low"].rolling(20).min().iloc[-1]

    squeeze = (high20 - low20) / low20 < 0.12

    # =========================
    # 均線多頭但不暴漲
    # =========================

    trend = (
        df["ma5"].iloc[-1] > df["ma20"].iloc[-1] >
        df["ma60"].iloc[-1]
    )

    # =========================
    # 不破底
    # =========================

    no_break = df["close"].iloc[-1] > df["ma60"].iloc[-1]

    # =========================
    # 主力潛伏條件
    # =========================

    score = 0

    if vol_contract:
        score += 25

    if vcp:
        score += 25

    if squeeze:
        score += 20

    if trend:
        score += 15

    if no_break:
        score += 15

    # =========================
    # 等級
    # =========================

    if score >= 80:
        level = "🧠 主力強潛伏"

    elif score >= 60:
        level = "👀 潛伏中"

    else:
        level = "觀察"

    return {
        "score": score,
        "level": level,
        "close": df["close"].iloc[-1],
        "vol_contract": vol_contract,
        "vcp": vcp,
        "squeeze": squeeze
    }

# =====================================================
# UI
# =====================================================

st.title("🧠 主力潛伏股偵測系統")

token = st.text_input("FinMind Token", type="password")

max_n = st.slider("掃描數量", 50, 500, 150)

start = st.button("🚀 開始掃描")

# =====================================================
# 主程式
# =====================================================

if start:

    pool = stock_pool()[:max_n]

    results = []

    progress = st.progress(0)

    for i, code in enumerate(pool):

        progress.progress((i+1)/len(pool))

        df = get_data(code)

        result = detect_accumulation(df)

        if result is None:
            continue

        if result["score"] < 60:
            continue

        chip = None

        if token:
            chip = get_chip(code, token)

            if chip and chip["buy"] > 0:
                result["score"] += 10

        result["code"] = code

        results.append(result)

    df = pd.DataFrame(results)

    if df.empty:
        st.warning("沒有找到主力潛伏股")
    else:
        df = df.sort_values("score", ascending=False)

        st.success(f"找到 {len(df)} 檔潛伏股")

        st.dataframe(df)
