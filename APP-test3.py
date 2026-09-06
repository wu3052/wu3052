import datetime
import time
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# -----------------------------------------------------------------------------
# 頁面基本設定
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="AI 股票狙擊手 Pro Max & 資金流向監測系統",
    page_icon="📈",
    layout="wide",
)

# -----------------------------------------------------------------------------
# 模擬資料初始化與生成函式 (確保完整可執行)
# -----------------------------------------------------------------------------


@st.cache_data
def load_market_overview():
    return {
        "taiex_change": 1.51,
        "update_date": "2026-09-04",
        "up_sectors_count": 33,
        "sideway_sectors_count": 16,
        "pullback_sectors_count": 17,
        "down_sectors_count": 44,
        "market_sentiment": {"bullish": 81, "bearish": 19},
    }


@st.cache_data
def load_sector_bubble_data():
    data = [
        {
            "sector": "AI PC 筆電與平板",
            "daily_flow": 248.0,
            "speed_20d": 15.2,
            "cum_20d": 381.5,
            "change_5d": 3.0,
            "status": "漲潮",
            "leader": "主力 緯創",
        },
        {
            "sector": "銀行金融",
            "daily_flow": 47.9,
            "speed_20d": 16.1,
            "cum_20d": 305.8,
            "change_5d": 7.6,
            "status": "漲潮",
            "leader": "主力 兆豐金",
        },
        {
            "sector": "智慧型手機",
            "daily_flow": 145.2,
            "speed_20d": 8.0,
            "cum_20d": 262.9,
            "change_5d": 5.6,
            "status": "漲潮",
            "leader": "主力 鴻海",
        },
        {
            "sector": "EMS 電子代工",
            "daily_flow": 230.6,
            "speed_20d": 10.3,
            "cum_20d": 254.7,
            "change_5d": 1.5,
            "status": "順勢",
            "leader": "主力 廣達",
        },
        {
            "sector": "AI 伺服器組裝",
            "daily_flow": 230.0,
            "speed_20d": 11.1,
            "cum_20d": 220.8,
            "change_5d": 6.7,
            "status": "漲潮",
            "leader": "主力 緯創",
        },
        {
            "sector": "液冷散熱",
            "daily_flow": 40.4,
            "speed_20d": 6.0,
            "cum_20d": 190.2,
            "change_5d": 7.4,
            "status": "順勢",
            "leader": "主力 雙鴻",
        },
        {
            "sector": "氣冷與核心組件",
            "daily_flow": 35.0,
            "speed_20d": 5.5,
            "cum_20d": 174.9,
            "change_5d": 5.0,
            "status": "順勢",
            "leader": "主力 奇鋐",
        },
        {
            "sector": "傳統傳產鋼鐵",
            "daily_flow": -85.0,
            "speed_20d": -4.2,
            "cum_20d": -120.0,
            "change_5d": -2.1,
            "status": "逆潮",
            "leader": "主力 中鋼",
        },
        {
            "sector": "塑膠化工",
            "daily_flow": -110.0,
            "speed_20d": -6.5,
            "cum_20d": -180.0,
            "change_5d": -3.5,
            "status": "退潮",
            "leader": "主力 台塑",
        },
    ]
    return pd.DataFrame(data)


@st.cache_data
def load_abnormal_stocks():
    return {
        "explosion": [
            {
                "stock": "2327 國巨",
                "flow": "+105億",
                "reason": "單日爆買成交量放大3倍",
            },
            {"stock": "2317 鴻海", "flow": "+74億", "reason": "法人強力敲進"},
            {"stock": "3231 緯創", "flow": "+55億", "reason": "突破均線糾結"},
            {"stock": "2330 台積電", "flow": "+47億", "reason": "穩定資金流入"},
        ],
        "foreign_投信_co_buy": [
            {
                "stock": "2603 長榮海",
                "foreign_pct": "+0.8%",
                "投信_pct": "+0.6%",
                "status": "同買",
            },
            {
                "stock": "2454 聯發科",
                "foreign_pct": "+1.2%",
                "投信_pct": "+0.5%",
                "status": "同買",
            },
        ],
        "continuous_buy": [
            {
                "stock": "2382 廣達",
                "days": 4,
                "note": "外資投信連買4天",
            },
            {"stock": "3017 奇鋐", "days": 3, "note": "外資投信連買3天"},
        ],
    }


@st.cache_data
def load_stock_20d_flow(stock_name):
    np.random.seed(42)
    dates = pd.date_range(end=datetime.date.today(), periods=20, freq="B")
    flows = np.random.uniform(-15, 25, size=20).cumsum()
    df = pd.DataFrame(
        {
            "日期": dates.strftime("%Y-%m-%d"),
            "法人買賣超金額(億)": np.random.uniform(-10, 20, size=20).round(2),
            "近20日資金累積(億)": flows.round(2),
            "主力動向": np.choice(
                ["買超", "賣超", "中立"], size=20, p=[0.5, 0.3, 0.2]
            ),
        }
    )
    return df


# -----------------------------------------------------------------------------
# 側邊欄控制與導覽
# -----------------------------------------------------------------------------
st.sidebar.title("🚀 股票狙擊手 Pro Max")
st.sidebar.markdown("---")
menu = st.sidebar.selectbox(
    "功能導覽",
    [
        "📊 板塊資金流向與監測",
        "🎯 AI 智慧選股與狙擊",
        "📈 個股 20 日資金流向查詢",
        "⚙️ 系統設定與通知",
    ],
)

market_info = load_market_overview()
st.sidebar.markdown(
    f"**大盤指數**: `{market_info['taiex_change']}%` 🟢 | **更新日期**: `{market_info['update_date']}`"
)

# -----------------------------------------------------------------------------
# 主要頁面邏輯
# -----------------------------------------------------------------------------

if menu == "📊 板塊資金流向與監測":
    st.markdown("### 📊 板塊資金流向與即時監測儀表板")

    # 上方市場狀態摘要指標
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(
            "漲潮板塊 (資金資金流入)",
            f"{market_info['up_sectors_count']} 個",
            "+5 較昨日",
        )
    with col2:
        st.metric(
            "順勢板塊 (資金流入放緩)",
            f"{market_info['sideway_sectors_count']} 個",
            "-2 較昨日",
        )
    with col3:
        st.metric(
            "緩盤板塊 (資金流出但抗跌)",
            f"{market_info['pullback_sectors_count']} 個",
            "+1 較昨日",
        )
    with col4:
        st.metric(
            "退潮板塊 (資金流出)",
            f"{market_info['down_sectors_count']} 個",
            "-3 較昨日",
        )

    st.markdown("---")

    # 1. 板塊泡泡圖區塊
    st.markdown(
        "#### 🔵 板塊泡泡圖 (X軸: 當日資金流向 | Y軸: 近20日資金加速度 | 泡泡大小: 20日累積規模)"
    )
    df_bubble = load_sector_bubble_data()

    fig = px.scatter(
        df_bubble,
        x="daily_flow",
        y="speed_20d",
        size=df_bubble["cum_20d"].abs(),
        color="status",
        hover_name="sector",
        text="sector",
        size_max=50,
        labels={
            "daily_flow": "當日資金流出/流入 (億)",
            "speed_20d": "近20日資金進速",
        },
        color_discrete_map={
            "漲潮": "#2ca02c",
            "順勢": "#1f77b4",
            "逆潮": "#ff7f0e",
            "退潮": "#d62728",
        },
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        height=500,
        xaxis=dict(zeroline=True, zerolinecolor="gray", zerolinewidth=2),
        yaxis=dict(zeroline=True, zerolinecolor="gray", zerolinewidth=2),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # 2. 買 / 賣 篩選與監測清單
    st.markdown("#### 📋 板塊與個股資金排行監測")
    trade_action = st.radio(
        "選擇方向", ["🟢 買方資金監測 (Buy)", "🔴 賣方資金監測 (Sell)"], horizontal=True
    )

    # 次級標籤頁
    sub_tab1, sub_tab2, sub_tab3, sub_tab4, sub_tab5 = st.tabs(
        [
            "法人動向 (近五日)",
            "買多漲少 / 賣多跌少",
            "逆勢買超 / 逆勢賣超",
            "個股異常 (爆買)",
            "外資投信 (同買/連買)",
        ]
    )

    if "買方" in trade_action:
        with sub_tab1:
            st.markdown(
                "##### 🏆 近五日法人買最多的板塊 (依累計金額排序，含當日與五日數據)"
            )
            display_df = df_bubble.sort_values(by="cum_20d", ascending=False)[
                [
                    "sector",
                    "change_5d",
                    "cum_20d",
                    "daily_flow",
                    "status",
                    "leader",
                ]
            ]
            display_df.columns = [
                "板塊名稱",
                "5日漲跌幅 (%)",
                "5日淨買超(億)",
                "當日淨買超(億)",
                "狀態",
                "主力動向",
            ]
            st.dataframe(display_df, use_container_width=True)

        with sub_tab2:
            st.markdown(
                "##### ⚖️ 買多漲少排行 (五日資金流入高，但漲幅相對低之潛力落後補漲板塊)"
            )
            # 模擬計算買多漲少：資金高但漲幅相對偏低
            filtered_bz = df_bubble.sort_values(
                by=["cum_20d", "change_5d"], ascending=[False, True]
            )
            st.dataframe(filtered_bz, use_container_width=True)

        with sub_tab3:
            st.markdown(
                "##### 🛡️ 逆勢買超監測 (當大盤跌幅超過1%時，法人逆勢敲進的板塊)"
            )
            if market_info["taiex_change"] < -1.0:
                st.info(
                    "目前大盤跌幅超過 1%，以下為逆勢資金流入板塊："
                )
                st.dataframe(
                    df_bubble[df_bubble["daily_flow"] > 0],
                    use_container_width=True,
                )
            else:
                st.success(
                    "目前大盤未跌逾 1%（目前大盤變動: "
                    f"{market_info['taiex_change']}%），系統持續待命中。"
                )
                st.dataframe(
                    df_bubble[df_bubble["daily_flow"] > 50],
                    use_container_width=True,
                )

        with sub_tab4:
            st.markdown(
                "##### ⚡ 個股異常 - 爆買 (今日相對20日突然放量大買之個股)"
            )
            abnormal = load_abnormal_stocks()
            st.table(pd.DataFrame(abnormal["explosion"]))

        with sub_tab5:
            st.markdown(
                "##### 🤝 外資投信同買與連買個股 (外資投信同買>0.5% 或 連買3天以上)"
            )
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**外資投信同買 (>0.5%)**")
                st.table(pd.DataFrame(abnormal["foreign_投信_co_buy"]))
            with col_b:
                st.markdown("**外資投信連買 (>= 3天)**")
                st.table(pd.DataFrame(abnormal["continuous_buy"]))

    else:
        # 賣方監測
        with sub_tab1:
            st.markdown("##### 📉 近五日法人賣最多的板塊")
            sell_df = df_bubble.sort_values(by="cum_20d", ascending=True)[
                [
                    "sector",
                    "change_5d",
                    "cum_20d",
                    "daily_flow",
                    "status",
                    "leader",
                ]
            ]
            st.dataframe(sell_df, use_container_width=True)

        with sub_tab2:
            st.markdown(
                "##### ⚖️ 賣多跌少排行 (資金流出但跌幅相對輕微之防守板塊)"
            )
            st.dataframe(df_bubble.sort_values(by="cum_20d"), use_container_width=True)

        with sub_tab3:
            st.markdown(
                "##### 🌪️ 逆勢賣超監測 (大盤上漲或平盤時，遭法人逆勢倒貨板塊)"
            )
            st.dataframe(
                df_bubble[df_bubble["daily_flow"] < 0], use_container_width=True
            )

        with sub_tab4:
            st.markdown("##### ⚡ 個股異常 - 爆賣 (今日遭突襲重手賣超個股)")
            st.info("目前無重大異常爆賣個股。")

        with sub_tab5:
            st.markdown("##### 🏃 外資投信同賣與連賣個股")
            st.info("無連續賣超滿3天以上之重點標的。")

elif menu == "🎯 AI 智慧選股與狙擊":
    st.markdown("### 🎯 AI 股票狙擊手 Pro Max - 智慧選股策略")
    st.markdown(
        "在此執行籌碼集中度、均線糾結後帶量突破、以及營收加速之量化選股邏輯。"
    )

    col1, col2 = st.columns(2)
    with col1:
        selected_strategy = st.selectbox(
            "選擇選股策略",
            [
                "籌碼集中度爆發策略",
                "均線糾結後帶量突破 (5MA)",
                "營收加速 + 漲停基因篩選",
            ],
        )
    with col2:
        min_volume = st.slider(
            "最低成交量篩選 (張)", 500, 10000, 2000, step=500
        )

    if st.button("🚀 開始執行智慧選股"):
        with st.spinner("正在連線 FinMind 及運算技術指標中..."):
            time.sleep(1)
        st.success(f"選股完成！策略: 【{selected_strategy}】")

        # 模擬選股結果表格
        result_data = pd.DataFrame(
            {
                "股票代號": ["2330 台積電", "2317 鴻海", "3231 緯創", "2382 廣達"],
                "收盤價": [980.0, 215.0, 128.5, 295.0],
                "當日漲幅(%)": [2.4, 3.1, 4.5, 1.8],
                "籌碼集中度": ["+12.5%", "+8.2%", "+15.1%", "+6.4%"],
                "技術訊號": [
                    "5MA 支撐帶量",
                    "頭肩底突破",
                    "VCP 收斂突破",
                    "法人連買",
                ],
            }
        )
        st.dataframe(result_data, use_container_width=True)

elif menu == "📈 個股 20 日資金流向查詢":
    st.markdown("### 📈 個股近 20 日資金流向追蹤查詢")

    stock_input = st.text_input(
        "請輸入股票代號或名稱 (例如: 2330 台積電, 2317 鴻海)", "2330 台積電"
    )

    if st.button("🔍 查詢個股資金流"):
        st.markdown(f"#### 【{stock_input}】 近 20 個交易日資金流向明細")
        df_flow_20d = load_stock_20d_flow(stock_input)

        # 繪製近20日資金趨勢圖
        fig_stock = px.bar(
            df_flow_20d,
            x="日期",
            y="法人買賣超金額(億)",
            color="法人買賣超金額(億)",
            color_continuous_scale="RdBu",
            title=f"{stock_input} 近20日法人買賣超金額紀錄",
        )
        st.plotly_chart(fig_stock, use_container_width=True)

        # 顯示詳細表格
        st.dataframe(df_flow_20d, use_container_width=True)

elif menu == "⚙️ 系統設定與通知":
    st.markdown("### ⚙️ 系統設定與 LINE 訊息自動通知")
    line_token = st.text_input(
        "LINE Notify權杖 (Token)", value="************************", type="password"
    )
    notify_time = st.time_input(
        "每日自動推播時間", datetime.time(8, 30)
    )

    if st.button("💾 儲存設定"):
        st.success("設定已成功儲存！LINE 自動推播排程已更新。")
