import io
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ==========================================
# 0. 頁面設定與版型
# ==========================================
st.set_page_config(
    page_title="Tide 潮汐｜台股板塊輪動・法人資金流向",
    page_icon="🌊",
    layout="wide",
)

st.markdown(
    """
    <style>
    .main { background-color: #0F1413; color: #EFF3F1; }
    .stMetric { background-color: #1B2220; padding: 10px; border-radius: 10px; border: 1px solid #293230; }
    </style>
""",
    unsafe_allow_html=True,
)


# ==========================================
# 1. 動態從證交所抓取上市(2)與上櫃(4)清單模組
# ==========================================
@st.cache_data(ttl=86400)  # 快取 24 小時，避免頻繁請求
def fetch_twse_tpex_stocks():
    """透過證交所官方 ISIN 網頁動態抓取上市 (strMode=2) 與上櫃 (strMode=4) 之股票代號、名稱與產業別"""
    all_stocks = []

    urls = {
        "上市 (TWSE)": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
        "上櫃 (TPEX)": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
    }

    for market_type, url in urls.items():
        try:
            # 模擬瀏覽器 Header 避免被擋
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = "cp950"  # 證交所舊網頁編碼通常為 CP950/Big5

            # 解析 HTML 表格
            dfs = pd.read_html(io.StringIO(res.text))
            df = dfs[0]

            # 清洗欄位
            df.columns = df.iloc[0]
            df = df.iloc[1:].copy()

            target_col = None
            for col in df.columns:
                if col and ("代號" in str(col) and "名稱" in str(col)):
                    target_col = col
                    break

            if not target_col:
                continue

            for _, row in df.iterrows():
                val = str(row[target_col]).strip()
                industry = str(row.get("產業別", "其他")).strip()

                if " " in val:
                    parts = val.split(" ", 1)
                elif " " in val:
                    parts = val.split(" ", 1)
                else:
                    continue

                if len(parts) == 2:
                    code, name = parts[0].strip(), parts[1].strip()
                    # 篩選一般股票代號（通常為 4 碼數字）
                    if len(code) == 4 and code.isdigit():
                        all_stocks.append(
                            {
                                "股票代號": code,
                                "股票名稱": name,
                                "市場別": market_type,
                                "產業類別": (
                                    industry
                                    if industry and industry != "nan"
                                    else "其他"
                                ),
                            }
                        )
        except Exception as e:
            print(f"抓取 {market_type} 失敗: {e}")

    df_result = pd.DataFrame(all_stocks)
    # 若抓取失敗或網路異常，提供基本備用清單
    if df_result.empty:
        fallback_data = [
            ("2330", "台積電", "上市 (TWSE)", "半導體業"),
            ("2317", "鴻海", "上市 (TWSE)", "電腦及週邊設備業"),
            ("2454", "聯發科", "上市 (TWSE)", "半導體業"),
            ("2308", "台達電", "上市 (TWSE)", "電子零組件業"),
            ("2881", "富邦金", "上市 (TWSE)", "金融保險業"),
            ("2603", "長榮", "上市 (TWSE)", "航運業"),
            ("3231", "緯創", "上市 (TWSE)", "電腦及週邊設備業"),
            ("6472", "保瑞", "上櫃 (TPEX)", "生技醫療業"),
            ("3481", "群創", "上市 (TWSE)", "光電業"),
        ]
        df_result = pd.DataFrame(
            fallback_data, columns=["股票代號", "股票名稱", "市場別", "產業類別"]
        )

    return df_result.drop_duplicates(subset=["股票代號"])


@st.cache_data(ttl=3600)
def fetch_market_data():
    """結合官方上市櫃清單與資金流向模擬數值"""
    df_base = fetch_twse_tpex_stocks()
    np.random.seed(42)

    stocks = []
    for _, row in df_base.iterrows():
        close = np.random.uniform(15, 1000)
        chg_1d = np.random.uniform(-5, 5)
        chg_5d = np.random.uniform(-12, 12)
        foreign_buy_pct = np.random.uniform(-1.5, 2.0)
        trust_buy_pct = np.random.uniform(-0.8, 1.2)
        flow_5d = np.random.uniform(-500, 800)  # 百萬
        flow_accel = np.random.uniform(-100, 100)
        volume_ratio = np.random.uniform(0.5, 3.5)

        stocks.append(
            {
                "股票代號": row["股票代號"],
                "股票名稱": row["股票名稱"],
                "市場別": row["市場別"],
                "產業類別": row["產業類別"],
                "細產業": row["產業類別"],
                "收盤價": round(close, 2),
                "當日漲跌幅(%)": round(chg_1d, 2),
                "五日漲跌幅(%)": round(chg_5d, 2),
                "外資買賣超占比(%)": round(foreign_buy_pct, 2),
                "投信買賣超占比(%)": round(trust_buy_pct, 2),
                "五日資金流向(百萬)": round(flow_5d, 2),
                "資金加速動能": round(flow_accel, 2),
                "爆量異常比": round(volume_ratio, 2),
                "外資連買天數": int(
                    np.random.choice([0, 1, 3, 5, 7], p=[0.4, 0.2, 0.2, 0.1, 0.1])
                ),
                "投信連買天數": int(
                    np.random.choice([0, 1, 2, 4], p=[0.5, 0.3, 0.15, 0.05])
                ),
            }
        )

    return pd.DataFrame(stocks)


df_stocks = fetch_market_data()
market_chg_1d = 1.2  # 模擬大盤當日漲跌幅

st.sidebar.title("🌊 Tide 潮汐資金導覽")
app_mode = st.sidebar.radio(
    "選擇功能模組",
    ["板塊泡泡輪動圖", "每日多方籌碼精選 (買)", "每日空方籌碼警戒 (賣)"],
)

st.title("Tide 潮汐｜台股板塊輪動・法人資金流向")
st.markdown(
    f"資料來源：證交所官方上市櫃清單 (strMode=2 & 4) | 股票總檔數：`{len(df_stocks)}` 檔 | 大盤漲跌幅: `{market_chg_1d:+.2f}%`"
)

# ==========================================
# 1. 板塊泡泡圖模組
# ==========================================
if app_mode == "板塊泡泡輪動圖":
    st.subheader("📊 板塊資金流向泡泡圖 (依產業聚合)")

    df_sub = (
        df_stocks.groupby("產業類別")
        .agg(
            {
                "五日資金流向(百萬)": "sum",
                "資金加速動能": "mean",
                "收盤價": "count",
                "當日漲跌幅(%)": "mean",
            }
        )
        .reset_index()
    )
    df_sub.rename(columns={"收盤價": "股票檔數"}, inplace=True)

    fig = px.scatter(
        df_sub,
        x="五日資金流向(百萬)",
        y="資金加速動能",
        size="股票檔數",
        color="產業類別",
        hover_name="產業類別",
        text="產業類別",
        size_max=40,
        template="plotly_dark",
        title="上市櫃產業資金流向與加速動能分佈",
    )

    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_traces(textposition="top center")
    fig.update_layout(height=600)
    st.plotly_chart(fig, use_container_width=True)


# ==========================================
# 2. 每日多方籌碼精選 (買)
# ==========================================
elif app_mode == "每日多方籌碼精選 (買)":
    st.header("🟢 每日多方籌碼精選 (買方清單)")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "1. 法人動向 (板塊)",
            "2. 買多漲少",
            "3. 逆勢買超",
            "4. 個股異常 (爆買)",
            "5. 外資投信同買/連買",
        ]
    )

    with tab1:
        st.markdown("### 1. 法人動向 - 近五日法人買最多的產業")
        sector_buy = (
            df_stocks.groupby("產業類別")["五日資金流向(百萬)"]
            .sum()
            .reset_index()
            .sort_values(by="五日資金流向(百萬)", ascending=False)
        )
        st.dataframe(sector_buy, use_container_width=True)

    with tab2:
        st.markdown("### 2. 買多漲少 - 依「五日資金流入高，漲幅相對低」排序")
        df_buy_less_rise = df_stocks.sort_values(
            by=["五日資金流向(百萬)", "五日漲跌幅(%)"], ascending=[False, True]
        )
        st.dataframe(
            df_buy_less_rise[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(15),
            use_container_width=True,
        )

    with tab3:
        st.markdown("### 3. 逆勢買超 - 法人逆勢買超的上市櫃股票")
        df_counter_buy = df_stocks[
            (df_stocks["外資買賣超占比(%)"] > 0)
            & (df_stocks["投信買賣超占比(%)"] > 0)
        ].sort_values(by="外資買賣超占比(%)", ascending=False)
        st.dataframe(df_counter_buy.head(15), use_container_width=True)

    with tab4:
        st.markdown("### 4. 個股異常 - 爆買：今天突然被大買的上市櫃股票")
        df_spike_buy = df_stocks.sort_values(
            by="爆量異常比", ascending=False
        ).head(15)
        st.dataframe(
            df_spike_buy[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "爆量異常比",
                    "當日漲跌幅(%)",
                ]
            ],
            use_container_width=True,
        )

    with tab5:
        st.markdown(
            "### 5. 外資投信 - 同買 (各 > 0.5%) / 連買 (連續 3 天以上)"
        )
        df_co_buy = df_stocks[
            (df_stocks["外資買賣超占比(%)"] > 0.5)
            & (df_stocks["投信買賣超占比(%)"] > 0.5)
            | (df_stocks["外資連買天數"] >= 3)
            | (df_stocks["投信連買天數"] >= 3)
        ]
        st.dataframe(
            df_co_buy[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                    "外資連買天數",
                    "投信連買天數",
                ]
            ].head(15),
            use_container_width=True,
        )


# ==========================================
# 3. 每日空方籌碼警戒 (賣)
# ==========================================
elif app_mode == "每日空方籌碼警戒 (賣)":
    st.header("🔴 每日空方籌碼警戒 (賣方清單)")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "1. 法人動向 (板塊)",
            "2. 賣多漲少",
            "3. 逆勢賣超",
            "4. 個股異常 (爆賣)",
            "5. 外資投信同賣/連賣",
        ]
    )

    with tab1:
        st.markdown("### 1. 法人動向 - 近五日法人賣最多的產業")
        sector_sell = (
            df_stocks.groupby("產業類別")["五日資金流向(百萬)"]
            .sum()
            .reset_index()
            .sort_values(by="五日資金流向(百萬)", ascending=True)
        )
        st.dataframe(sector_sell, use_container_width=True)

    with tab2:
        st.markdown("### 2. 賣多漲少 - 依「五日資金賣出高，跌幅相對低」排序")
        df_sell_less_fall = df_stocks.sort_values(
            by=["五日資金流向(百萬)", "五日漲跌幅(%)"], ascending=[True, False]
        )
        st.dataframe(
            df_sell_less_fall[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(15),
            use_container_width=True,
        )

    with tab3:
        st.markdown("### 3. 逆勢賣超 - 法人逆勢賣超的上市櫃股票")
        df_counter_sell = df_stocks[
            (df_stocks["外資買賣超占比(%)"] < 0)
            & (df_stocks["投信買賣超占比(%)"] < 0)
        ].sort_values(by="外資買賣超占比(%)", ascending=True)
        st.dataframe(df_counter_sell.head(15), use_container_width=True)

    with tab4:
        st.markdown("### 4. 個股異常 - 爆賣：今天突然被大賣的上市櫃股票")
        df_spike_sell = df_stocks.sort_values(
            by="爆量異常比", ascending=True
        ).head(15)
        st.dataframe(
            df_spike_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "爆量異常比",
                    "當日漲跌幅(%)",
                ]
            ],
            use_container_width=True,
        )

    with tab5:
        st.markdown("### 5. 外資投信 - 同賣與連賣警戒")
        df_co_sell = df_stocks[
            (df_stocks["外資買賣超占比(%)"] < -0.5)
            & (df_stocks["投信買賣超占比(%)"] < -0.5)
        ]
        st.dataframe(
            df_co_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "市場別",
                    "產業類別",
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                ]
            ].head(15),
            use_container_width=True,
        )
