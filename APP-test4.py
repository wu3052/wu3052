import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

st.set_page_config(
    page_title="Tide 資金動態與板塊輪動",
    page_icon="🌊",
    layout="wide"
)

# 模擬台股板塊與法人資金流向資料
@st.cache_data
def load_market_data():
    data = {
        "sector": ["半導體", "AI伺服器", "金融保險", "航運類", "生技醫療", "汽車零組件", "綠能環保", "光電面板"],
        "code_count": [45, 20, 38, 16, 25, 30, 15, 18],
        "perf_1d": [2.4, 3.8, -0.5, -1.2, 1.1, 0.4, 1.9, -0.8],
        "perf_5d": [5.2, 12.4, 1.2, -4.5, 3.0, 2.1, 6.8, -2.1],
        "net_flow": [52.4, 88.1, -12.3, -34.5, 14.2, 6.5, 22.1, -8.4], # 億元
        "leader": ["台積電", "廣達", "富邦金", "長榮", "保瑞", "東陽", "中興電", "群創"]
    }
    return pd.DataFrame(data)

df = load_market_data()

st.title("🌊 Tide ｜ 台股板塊輪動與法人資金流向")
st.markdown("追蹤三大法人資金流向，掌握資金湧入的強勢板塊與潛力標的。")

# 頂部指標卡片
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("大盤成交值", "3,852 億", "+420億")
with col2:
    st.metric("外資買賣超", "+124.5 億", "偏多")
with col3:
    st.metric("投信買賣超", "+45.2 億", "連買")
with col4:
    st.metric("主流強勢板塊", "AI伺服器", "資金集中")

st.markdown("---")

# 版塊輪動氣泡圖 / 散佈圖
st.subheader("📊 板塊資金流向與漲跌分佈")

fig = px.scatter(
    df,
    x="perf_5d",
    y="net_flow",
    size="code_count",
    color="perf_1d",
    hover_name="sector",
    text="sector",
    color_continuous_scale="Tealgrn",
    labels={
        "perf_5d": "5日漲跌幅 (%)",
        "net_flow": "法人資金淨流入 (億元)",
        "perf_1d": "1日漲跌幅 (%)",
        "code_count": "成分股數量"
    },
    title="板塊動能氣泡圖 (X軸: 5日漲跌, Y軸: 資金淨流入, 大小: 成份股家數)"
)

fig.update_traces(textposition='top center')
fig.update_layout(
    height=550,
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#CED7D4")
)

st.plotly_chart(fig, use_container_width=True)

# 下方詳細清單與個股檢視
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("📋 板塊強弱排行榜")
    ranked_df = df.sort_values(by="net_flow", ascending=False).reset_index(drop=True)
    st.dataframe(ranked_df[["sector", "perf_1d", "perf_5d", "net_flow", "leader"]], use_container_width=True)

with col_right:
    st.subheader("🔍 板塊成分股明細")
    selected_sector = st.selectbox("選擇板塊檢視", df["sector"].tolist())
    
    # 模擬該板塊的個股資料
    stock_mock = {
        "半導體": [("2330", "台積電", "1080", "+2.8%", "+18.2億"), ("2454", "聯發科", "1250", "+1.5%", "+8.4億"), ("3035", "智原", "340", "-0.9%", "-1.2億")],
        "AI伺服器": [("2382", "廣達", "295", "+4.5%", "+24.1億"), ("2357", "華碩", "520", "+3.2%", "+12.5億"), ("3231", "緯創", "115", "+5.1%", "+15.8億")],
        "金融保險": [("2881", "富邦金", "88.5", "-0.4%", "-3.2億"), ("2882", "國泰金", "58.2", "-0.6%", "-4.5億")],
    }
    
    stocks = stock_mock.get(selected_sector, [("----", "範例個股", "0.0", "0.0%", "0億")])
    stock_df = pd.DataFrame(stocks, columns=["代號", "名稱", "收盤價", "漲跌幅", "法人買賣超"])
    st.dataframe(stock_df, use_container_width=True)
