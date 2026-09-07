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
# 1. 動態抓取證交所/櫃買中心 ISIN 清單與模擬資料整合
# ==========================================
@st.cache_data(ttl=86400)
def fetch_twse_isin_mapping():
    """從證交所公開資訊網 (ISIN) 抓取上市上櫃代號、名稱與產業別

    若連線或解析失敗，則自動切換至內建完整台股權值與代表性股票對照清單。
    """
    url = "http://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
    try:
        res = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
            },
            timeout=8,
        )
        res.encoding = "big5"
        dfs = pd.read_html(res.text)
        df_raw = dfs[0]

        # 清理標題行
        df_raw.columns = df_raw.iloc[0]
        df_raw = df_raw.iloc[1:].copy()

        # 尋找含有「有價證券代號及名稱」與「產業別」的欄位
        col_code_name = next(
            (c for c in df_raw.columns if "代號及名稱" in str(c)), None
        )
        col_market = next((c for c in df_raw.columns if "市場別" in str(c)), None)
        col_industry = next(
            (c for c in df_raw.columns if "產業別" in str(c)), None
        )

        if col_code_name:
            # 過濾掉 NaN 與非股票列（股票代號通常為 4 碼數字或含字母）
            df_valid = df_raw.dropna(subset=[col_code_name]).copy()
            # 切割代號與名稱 (支援全形或半形空白)
            split_df = df_valid[col_code_name].str.extract(
                r"([A-Za-z0-9]+)[ \s]+(.+)"
            )
            df_valid["股票代號"] = split_df[0]
            df_valid["股票名稱"] = split_df[1]

            # 篩選 4 碼台股代號
            df_valid = df_valid.dropna(subset=["股票代號"])
            df_valid = df_valid[df_valid["股票代號"].str.len() == 4]

            if col_industry:
                df_valid["產業類別"] = df_valid[col_industry].fillna(
                    "其他產業"
                )
            else:
                df_valid["產業類別"] = "台股總覽"

            if col_market:
                df_valid["市場別"] = df_valid[col_market]
            else:
                df_valid["市場別"] = "上市"

            mapping_df = df_valid[["股票代號", "股票名稱", "產業類別", "市場別"]].drop_duplicates(
                subset=["股票代號"]
            )
            if len(mapping_df) > 100:
                return mapping_df
    except Exception:
        pass

    # 備用：內建完整台股各產業代表與權值股對照清單
    fallback_data = [
        # 半導體
        ("2330", "台積電", "半導體", "上市"),
        ("2454", "聯發科", "半導體", "上市"),
        ("2303", "聯電", "半導體", "上市"),
        ("3034", "聯詠", "半導體", "上市"),
        ("3711", "日月光投控", "半導體", "上市"),
        ("5347", "世界", "半導體", "上櫃"),
        ("6488", "環球晶", "半導體", "上櫃"),
        ("3243", "穩懋", "半導體", "上櫃"),
        ("8299", "群聯", "半導體", "上櫃"),
        # 電腦及週邊
        ("2317", "鴻海", "電腦及週邊", "上市"),
        ("2382", "廣達", "電腦及週邊", "上市"),
        ("3231", "緯創", "電腦及週邊", "上市"),
        ("2357", "華碩", "電腦及週邊", "上市"),
        ("2376", "技嘉", "電腦及週邊", "上市"),
        ("6669", "緯穎", "電腦及週邊", "上市"),
        ("2356", "英業達", "電腦及週邊", "上市"),
        ("3234", "光環", "電腦及週邊", "上櫃"),
        # 電子零組件
        ("2308", "台達電", "電子零組件", "上市"),
        ("3037", "欣興", "電子零組件", "上市"),
        ("2313", "華通", "電子零組件", "上市"),
        ("2327", "國巨", "電子零組件", "上市"),
        ("4938", "和碩", "電子零組件", "上市"),
        ("3044", "健鼎", "電子零組件", "上市"),
        ("8046", "南電", "電子零組件", "上市"),
        # 光電業
        ("3008", "大立光", "光電業", "上市"),
        ("2409", "友達", "光電業", "上市"),
        ("3481", "群創", "光電業", "上市"),
        ("3019", "亞光", "光電業", "上市"),
        ("3631", "晟楠", "光電業", "上櫃"),
        # 通信網路
        ("2412", "中華電", "通信網路", "上市"),
        ("3045", "台灣大哥大", "通信網路", "上市"),
        ("4904", "遠傳", "通信網路", "上市"),
        ("2345", "智邦", "通信網路", "上市"),
        ("5388", "中磊", "通信網路", "上櫃"),
        # 金融保險
        ("2881", "富邦金", "金融保險", "上市"),
        ("2882", "國泰金", "金融保險", "上市"),
        ("2891", "中信金", "金融保險", "上市"),
        ("2884", "玉山金", "金融保險", "上市"),
        ("2886", "兆豐金", "金融保險", "上市"),
        ("5880", "合庫金", "金融保險", "上市"),
        ("2885", "元大金", "金融保險", "上市"),
        # 航運業
        ("2603", "長榮", "航運業", "上市"),
        ("2609", "陽明", "航運業", "上市"),
        ("2615", "萬海", "航運業", "上市"),
        ("2618", "長榮航", "航運業", "上市"),
        ("2610", "華航", "航運業", "上市"),
        # 生技醫療
        ("1795", "美時", "生技醫療", "上市"),
        ("6472", "保瑞", "生技醫療", "上櫃"),
        ("4743", "合一", "生技醫療", "上市"),
        ("4123", "晟德", "生技醫療", "上市"),
        ("1760", "寶齡富錦", "生技醫療", "上市"),
        # 化學工業 / 塑膠
        ("1301", "台塑", "化學工業", "上市"),
        ("1303", "南亞", "化學工業", "上市"),
        ("6505", "台塑化", "化學工業", "上市"),
        ("4739", "康普", "化學工業", "上市"),
        ("1305", "華夏", "化學工業", "上市"),
        # 水泥工業 / 傳統產業
        ("1101", "台泥", "水泥工業", "上市"),
        ("1102", "亞泥", "水泥工業", "上市"),
        ("9904", "寶成", "其他", "上市"),
        ("9910", "豐泰", "其他", "上市"),
    ]
    return pd.DataFrame(
        fallback_data, columns=["股票代號", "股票名稱", "產業類別", "市場別"]
    )


@st.cache_data(ttl=3600)
def fetch_market_data():
    """結合 TWSE/TPEX 清單與量化資金流向模擬資料"""
    df_map = fetch_twse_isin_mapping()
    np.random.seed(42)

    stocks = []
    for _, row in df_map.iterrows():
        code = row["股票代號"]
        name = row["股票名稱"]
        sec = row["產業類別"]
        market = row["市場別"]

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
                "股票代號": code,
                "股票名稱": name,
                "產業類別": sec,
                "市場別": market,
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
market_chg_1d = 1.2  # 假設大盤當日漲跌幅

st.sidebar.title("🌊 Tide 潮汐資金導覽")
app_mode = st.sidebar.radio(
    "選擇功能模組",
    ["板塊泡泡輪動圖", "每日多方籌碼精選 (買)", "每日空方籌碼警戒 (賣)"],
)

st.title("Tide 潮汐｜台股板塊輪動・法人資金流向")
st.markdown(
    f"已串接上市上櫃真實代號與產業別 (共載入 `{len(df_stocks)}` 檔個股) | 大盤當日漲跌幅: `{market_chg_1d:+.2f}%`"
)

# ==========================================
# 1. 板塊泡泡圖模組
# ==========================================
if app_mode == "板塊泡泡輪動圖":
    st.subheader("📊 板塊資金流向泡泡圖 (依產業類別聚合)")
    st.markdown("""
    * **左上**：資金流出但放緩 (流向負、動能正)
    * **左下**：資金加速流出 (流向負、動能負)
    * **右上**：資金加速流入 (流向正、動能正)
    * **右下**：資金流入但放緩 (流向正、動能負)
    """)

    df_sub = (
        df_stocks.groupby("產業類別")
        .agg(
            {
                "五日資金流向(百萬)": "sum",
                "資金加速動能": "mean",
                "股票代號": "count",
                "當日漲跌幅(%)": "mean",
            }
        )
        .reset_index()
    )
    df_sub.rename(columns={"股票代號": "股票檔數"}, inplace=True)

    fig = px.scatter(
        df_sub,
        x="五日資金流向(百萬)",
        y="資金加速動能",
        size="股票檔數",
        color="產業類別",
        hover_name="產業類別",
        text="產業類別",
        size_max=45,
        template="plotly_dark",
        title="產業類別資金流向與加速動能分佈",
    )

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
                    "市場別",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(15),
            use_container_width=True,
        )

    with tab3:
        st.markdown("### 3. 逆勢買超 - 大盤跌幅超過 1% 時法人逆勢買超股票")
        if market_chg_1d < -1.0:
            df_counter_buy = df_stocks[
                (df_stocks["外資買賣超占比(%)"] > 0)
                & (df_stocks["投信買賣超占比(%)"] > 0)
            ].sort_values(by="外資買賣超占比(%)", ascending=False)
            st.dataframe(df_counter_buy, use_container_width=True)
        else:
            st.info(
                f"目前大盤漲跌幅為 `{market_chg_1d:+.2f}%`，未達跌幅大於 -1% 條件。以下顯示防禦型買超參考："
            )
            st.dataframe(
                df_stocks.sort_values(by="外資買賣超占比(%)", ascending=False).head(5),
                use_container_width=True,
            )

    with tab4:
        st.markdown("### 4. 個股異常 - 爆買：今天突然被大買的股票")
        df_spike_buy = df_stocks.sort_values(
            by="爆量異常比", ascending=False
        ).head(15)
        st.dataframe(
            df_spike_buy[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "市場別",
                    "爆量異常比",
                    "當日漲跌幅(%)",
                ]
            ],
            use_container_width=True,
        )

    with tab5:
        st.markdown("### 5. 外資投信 - 同買 / 連買")
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
                    "產業類別",
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                    "外資連買天數",
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
        st.markdown("### 2. 賣多漲少 - 依「五日資金賣出高，跌幅相對低」排序")
        df_sell_less_fall = df_stocks.sort_values(
            by=["五日資金流向(百萬)", "五日漲跌幅(%)"], ascending=[True, False]
        )
        st.dataframe(
            df_sell_less_fall[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "市場別",
                    "五日資金流向(百萬)",
                    "五日漲跌幅(%)",
                ]
            ].head(15),
            use_container_width=True,
        )

    with tab3:
        st.markdown("### 3. 逆勢賣超 - 大盤漲幅超過 1% 時法人逆勢賣超股票")
        if market_chg_1d > 1.0:
            df_counter_sell = df_stocks[
                (df_stocks["外資買賣超占比(%)"] < 0)
                & (df_stocks["投信買賣超占比(%)"] < 0)
            ].sort_values(by="外資買賣超占比(%)", ascending=True)
            st.dataframe(df_counter_sell, use_container_width=True)
        else:
            st.info(
                f"目前大盤漲跌幅為 `{market_chg_1d:+.2f}%`，未達漲幅大於 +1% 條件。以下顯示結帳賣超參考："
            )
            st.dataframe(
                df_stocks.sort_values(by="外資買賣超占比(%)", ascending=True).head(5),
                use_container_width=True,
            )

    with tab4:
        st.markdown("### 4. 個股異常 - 爆賣：今天突然被大賣的股票")
        df_spike_sell = df_stocks.sort_values(
            by="爆量異常比", ascending=True
        ).head(15)
        st.dataframe(
            df_spike_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "市場別",
                    "爆量異常比",
                    "當日漲跌幅(%)",
                ]
            ],
            use_container_width=True,
        )

    with tab5:
        st.markdown("### 5. 外資投信 - 同賣 / 連賣")
        df_co_sell = df_stocks[
            (df_stocks["外資買賣超占比(%)"] < -0.5)
            & (df_stocks["投信買賣超占比(%)"] < -0.5)
        ].head(15)
        st.dataframe(
            df_co_sell[
                [
                    "股票代號",
                    "股票名稱",
                    "產業類別",
                    "外資買賣超占比(%)",
                    "投信買賣超占比(%)",
                ]
            ],
            use_container_width=True,
        )
