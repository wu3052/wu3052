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
# 1. 資料擷取模組 (TWSE / TPEX / Moneydj 模擬與API串接)
# ==========================================
@st.cache_data(ttl=3600)
def fetch_market_data():
    """從證交所/櫃買中心或免費來源取得上市上櫃股票、三大法人買賣超與類別資料

    註：實務上可串接 TWSE OpenAPI、FinMind API 或 yfinance。
    此處為確保程式完整開箱即用，建立高擬真結構化示範數據。
    """
    np.random.seed(42)
    sectors = [
        "半導體",
        "電腦及週邊",
        "電子零組件",
        "光電業",
        "通信網路",
        "金融保險",
        "航運業",
        "生技醫療",
        "化學工業",
        "水泥工業",
    ]
    sub_sectors = {
        "半導體": ["IC設計", "IC製造", "IC封測"],
        "電腦及週邊": ["代工", "伺服器", "週邊配件"],
        "電子零組件": ["PCB", "被動元件", "連接器"],
        "光電業": ["面板", "LED", "光學鏡頭"],
        "通信網路": ["網通設備", "電信服務"],
        "金融保險": ["銀行", "金控", "產險"],
        "航運業": ["貨櫃航運", "散裝航運", "航空"],
        "生技醫療": ["新藥研發", "醫療器材"],
        "化學工業": ["特用化學", "塑膠化學"],
        "水泥工業": ["水泥製造"],
    }

    stocks = []
    code_start = 2300
    for sec, subs in sub_sectors.items():
        for sub in subs:
            for i in range(3):  # 每個細產業3檔示範股
                code = str(code_start)
                name = f"{sec[0]}{sub[0]}股{i+1}"
                close = np.random.uniform(20, 1000)
                chg_1d = np.random.uniform(-5, 5)
                chg_5d = np.random.uniform(-12, 12)
                foreign_buy_pct = np.random.uniform(-1.5, 2.0)
                trust_buy_pct = np.random.uniform(-0.8, 1.2)
                flow_5d = np.random.uniform(-500, 800)  # 百萬
                flow_accel = np.random.uniform(-100, 100)
                volume_ratio = np.random.uniform(0.5, 3.5)  # 相對20日爆量比

                stocks.append(
                    {
                        "股票代號": code,
                        "股票名稱": name,
                        "產業類別": sec,
                        "細產業": sub,
                        "收盤價": round(close, 2),
                        "當日漲跌幅(%)": round(chg_1d, 2),
                        "五日漲跌幅(%)": round(chg_5d, 2),
                        "外資買賣超占比(%)": round(foreign_buy_pct, 2),
                        "投信買賣超占比(%)": round(trust_buy_pct, 2),
                        "五日資金流向(百萬)": round(flow_5d, 2),
                        "資金加速動能": round(flow_accel, 2),
                        "爆量異常比": round(volume_ratio, 2),
                        "外資連買天數": int(np.random.choice([0, 1, 3, 5, 7], p=[0.4, 0.2, 0.2, 0.1, 0.1])),
                        "投信連買天數": int(np.random.choice([0, 1, 2, 4], p=[0.5, 0.3, 0.15, 0.05])),
                    }
                )
                code_start += 1

    df = pd.DataFrame(stocks)
    return df


df_stocks = fetch_market_data()

# 模擬大盤指數與漲跌幅
market_chg_1d = 1.2  # 假設今天大盤漲 1.2% (可用於測試逆勢賣超)
# market_chg_1d = -1.5 # 若要測試大盤跌超過1%可切換此行

st.sidebar.title("🌊 Tide 潮汐資金導覽")
app_mode = st.sidebar.radio(
    "選擇功能模組",
    ["板塊泡泡輪動圖", "每日多方籌碼精選 (買)", "每日空方籌碼警戒 (賣)"],
)

st.title("Tide 潮汐｜台股板塊輪動・法人資金流向")
st.markdown(
    f"資料更新日期：2026-09-08 | 大盤當日漲跌幅: `{market_chg_1d:+.2f}%`"
)

# ==========================================
# 1. 板塊泡泡圖模組
# ==========================================
if app_mode == "板塊泡泡輪動圖":
    st.subheader("📊 板塊資金流向泡泡圖 (依細產業聚合)")
    st.markdown("""
    * **表格左上**：資金流出但放緩 (流向負、動能正)
    * **表格左下**：資金加速流出 (流向負、動能負)
    * **表格右上**：資金加速流入 (流向正、動能正)
    * **表格右下**：資金流入但放緩 (流向正、動能負)
    """)

    # 依細產業聚合
    df_sub = (
        df_stocks.groupby(["產業類別", "細產業"])
        .agg(
            {
                "五日資金流向(百萬)": "sum",
                "資金加速動能": "mean",
                "收盤價": "count",  # 股票檔數作為泡泡大小
                "當日漲跌幅(%)": "mean",
            }
        )
        .reset_index()
    )
    df_sub.rename(columns={"收盤價": "股票檔數"}, inplace=True)

    # 繪製 Plotly 泡泡圖
    fig = px.scatter(
        df_sub,
        x="五日資金流向(百萬)",
        y="資金加速動能",
        size="股票檔數",
        color="產業類別",
        hover_name="細產業",
        text="細產業",
        size_max=40,
        template="plotly_dark",
        title="細產業資金流向與加速動能分佈",
    )

    # 加上象限分隔線
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.add_vline(x=0, line_dash="dash", line_color="gray")

    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=600,
        xaxis_title="五日資金流向 (百萬NTD) [左：流出 | 右：流入]",
        yaxis_title="資金加速動能 [下：加速 | 上：放緩]",
    )
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
        st.markdown("### 1. 法人動向 - 近五日法人買最多的板塊")
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
                    "產業類別",
                    "細產業",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(10),
            use_container_width=True,
        )

    with tab3:
        st.markdown(
            "### 3. 逆勢買超 - 大盤跌幅超過 1% 時搜尋法人逆勢買超的股票"
        )
        if market_chg_1d < -1.0:
            df_counter_buy = df_stocks[
                (df_stocks["外資買賣超占比(%)"] > 0)
                & (df_stocks["投信買賣超占比(%)"] > 0)
            ].sort_values(by="外資買賣超占比(%)", ascending=False)
            st.dataframe(df_counter_buy, use_container_width=True)
        else:
            st.info(
                f"目前大盤當日漲跌幅為 `{market_chg_1d:+.2f}%`，未符合大盤跌幅超過 -1% 之觸發條件。以下顯示近期的防禦型買超參考："
            )
            df_defensive = df_stocks.sort_values(
                by="外資買賣超占比(%)", ascending=False
            ).head(5)
            st.dataframe(df_defensive, use_container_width=True)

    with tab4:
        st.markdown(
            "### 4. 個股異常 - 爆買：今天（相對 20 日）突然被大買的股票"
        )
        df_spike_buy = df_stocks.sort_values(
            by="爆量異常比", ascending=False
        ).head(10)
        st.dataframe(
            df_spike_buy[
                [
                    "股票代號",
                    "股票名稱",
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
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                    "外資連買天數",
                    "投信連買天數",
                ]
            ],
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
        st.markdown("### 1. 法人動向 - 近五日法人賣最多的板塊")
        sector_sell = (
            df_stocks.groupby("產業類別")["五日資金流向(百萬)"]
            .sum()
            .reset_index()
            .sort_values(by="五日資金流向(百萬)", ascending=True)
        )
        st.dataframe(sector_sell, use_container_width=True)

    with tab2:
        st.markdown(
            "### 2. 賣多漲少 - 依「五日資金賣出高，跌幅相對低」排序"
        )
        df_sell_less_fall = df_stocks.sort_values(
            by=["五日資金流向(百萬)", "五日漲跌幅(%)"], ascending=[True, False]
        )
        st.dataframe(
            df_sell_less_fall[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "細產業",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(10),
            use_container_width=True,
        )

    with tab3:
        st.markdown(
            "### 3. 逆勢賣超 - 大盤漲幅超過 1% 時搜尋法人逆勢賣超的股票"
        )
        if market_chg_1d > 1.0:
            df_counter_sell = df_stocks[
                (df_stocks["外資買賣超占比(%)"] < 0)
                & (df_stocks["投信買賣超占比(%)"] < 0)
            ].sort_values(by="外資買賣超占比(%)", ascending=True)
            st.dataframe(df_counter_sell, use_container_width=True)
        else:
            st.info(
                f"目前大盤當日漲跌幅為 `{market_chg_1d:+.2f}%`，未符合大盤漲幅超過 +1% 之觸發條件。以下顯示近期法人結帳賣超參考："
            )
            df_selling = df_stocks.sort_values(
                by="外資買賣超占比(%)", ascending=True
            ).head(5)
            st.dataframe(df_selling, use_container_width=True)

    with tab4:
        st.markdown(
            "### 4. 個股異常 - 爆賣：今天（相對 20 日）突然被大賣的股票"
        )
        df_spike_sell = df_stocks.sort_values(
            by="爆量異常比", ascending=True
        ).head(10)
        st.dataframe(
            df_spike_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "爆量異常比",
                    "當日漲跌幅(%)",
                ]
            ],
            use_container_width=True,
        )

    with tab5:
        st.markdown(
            "### 5. 外資投信 - 同賣 (各買超 < -0.5%) / 連賣 (連續 3 天以上)"
        )
        df_co_sell = df_stocks[
            (df_stocks["外資買賣超占比(%)"] < -0.5)
            & (df_stocks["投信買賣超占比(%)"] < -0.5)
            | (df_stocks["外資連買天數"] == 0)
            & (df_stocks["投信連買天數"] == 0)
        ].head(10)
        st.dataframe(
            df_co_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                    "外資連買天數",
                    "投信連買天數",
                ]
            ],
            use_container_width=True,
        )
