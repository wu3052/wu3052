import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# 頁面基本配置
st.set_page_config(
    page_title="Tide 潮汐｜台股板塊輪動・法人資金流向",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 自訂佈局與暗色主題樣式
st.markdown("""
<style>
    .main { background-color: #0F1413; color: #EFF3F1; }
    .stSidebar { background-color: #151B19; }
    h1, h2, h3 { color: #EFF3F1; }
    .metric-card { background-color: #1B2220; border: 1px solid #293230; padding: 15px; border-radius: 12px; }
</style>
""", unsafe_allow_html=True)

# 頂部標題與核心定位
st.title("🌊 Tide 潮汐 · 台股板塊輪動與法人資金流向")
st.markdown("每天追蹤三大法人資金流向，精準掌握資金正在湧向哪些關鍵板塊與標的。")

# 模擬台股板塊與法人資金流向核心資料庫
@st.cache_data
def load_tide_sector_data():
    sectors = [
        {"sector": "半導體", "category": "電子", "flow": 48.5, "change": 2.3, "weight": 35.2, "status": "資金流入・強勢", "stocks": [("2330", "台積電", "+2.5%", "+120億"), ("2454", "聯發科", "+1.8%", "+35億"), ("3711", "日月光投控", "+3.1%", "+15億")]},
        {"sector": "人工智慧與伺服器", "category": "電子", "flow": 62.1, "change": 4.1, "weight": 18.5, "status": "強勢主導", "stocks": [("2317", "鴻海", "+4.5%", "+55億"), ("2382", "廣達", "+3.8%", "+42億"), ("3231", "緯創", "+5.2%", "+28億")]},
        {"sector": "金融保險", "category": "金融", "flow": -12.4, "change": -0.4, "weight": 12.1, "status": "資金流出・回檔", "stocks": [("2881", "富邦金", "-0.5%", "-8億"), ("2882", "國泰金", "-0.3%", "-5億"), ("2891", "中信金", "+0.2%", "+3億")]},
        {"sector": "航運", "category": "傳產", "flow": 15.3, "change": 1.5, "weight": 8.4, "status": "短線聚焦點火", "stocks": [("2603", "長榮", "+2.1%", "+18億"), ("2609", "陽明", "+1.2%", "+6億"), ("2615", "萬海", "+0.8%", "+2億")]},
        {"sector": "生技醫療", "category": "生技", "flow": -5.2, "change": -1.1, "weight": 4.3, "status": "整理觀望", "stocks": [("4743", "合一", "-1.5%", "-1.2億"), ("1795", "美時", "-0.8%", "-0.5億")]},
        {"sector": "重電與綠能", "category": "傳產", "flow": 28.0, "change": 3.2, "weight": 7.8, "status": "法人加碼", "stocks": [("1519", "華城", "+6.5%", "+15億"), ("1503", "士電", "+4.2%", "+8億"), ("1513", "中興電", "+2.9%", "+6億")]},
        {"sector": "光電及面板", "category": "電子", "flow": -8.1, "change": -0.7, "weight": 6.5, "status": "弱勢震盪", "stocks": [("2409", "友達", "-0.9%", "-3億"), ("3481", "群創", "-0.6%", "-2億")]},
        {"sector": "汽車零組件", "category": "傳產", "flow": 6.5, "change": 0.9, "weight": 7.2, "status": "溫和走揚", "stocks": [("2201", "裕隆", "+1.1%", "+1億"), ("1522", "堤維西", "+0.5%", "+0.5億")]},
    ]
    return pd.DataFrame(sectors)

df_sectors = load_tide_sector_data()

# 側邊欄互動控制項
st.sidebar.header("🔍 資金篩選與設定")
selected_category = st.sidebar.selectbox("選擇產業分類", ["全部", "電子", "金融", "傳產", "生技"])
min_flow = st.sidebar.slider("最小法人資金流向門檻 (億)", -50.0, 50.0, -20.0, 1.0)

# 資料篩選邏輯
if selected_category != "全部":
    filtered_df = df_sectors[(df_sectors["category"] == selected_category) & (df_sectors["flow"] >= min_flow)]
else:
    filtered_df = df_sectors[df_sectors["flow"] >= min_flow]

# 頂部關鍵指標展示
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric(label="追蹤板塊總數", value=f"{len(df_sectors)} 個", delta="即時同步")
with col2:
    st.metric(label="資金淨流入最高", value="人工智慧與伺服器", delta="+62.1 億")
with col3:
    st.metric(label="大盤主力動向", value="電子權值股主導", delta="強勢輪動")
with col4:
    st.metric(label="更新時間", value=datetime.now().strftime("%Y-%m-%d %H:%M"), delta="盤後結算")

st.markdown("---")

# 核心視覺：板塊輪動與資金流向氣泡圖
st.subheader("📊 台股板塊資金流向與強弱分佈圖")
st.markdown("以 **X軸 (漲跌幅%)**、**Y軸 (法人資金流向億元)** 以及 **氣泡大小 (成交值比重%)** 完整呈現資金熱度與輪動軌跡。")

fig = px.scatter(
    filtered_df,
    x="change",
    y="flow",
    size="weight",
    color="sector",
    hover_name="sector",
    text="sector",
    size_max=60,
    labels={"change": "板塊平均漲跌幅 (%)", "flow": "三大法人資金流向 (億元)", "weight": "成交比重 (%)"},
    template="plotly_dark"
)

fig.update_traces(textposition='top center')
fig.update_layout(
    height=550,
    paper_bgcolor='#151B19',
    plot_bgcolor='#0F1413',
    xaxis=dict(showgrid=True, gridcolor='#293230'),
    yaxis=dict(showgrid=True, gridcolor='#293230'),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)

st.plotly_chart(fig, use_container_width=True)

# 板塊詳細明細與成分股穿梭
st.subheader("📋 板塊詳細數據與強勢成分股")

selected_sector = st.selectbox("選擇欲檢視細節的板塊", df_sectors["sector"].tolist())
sector_info = df_sectors[df_sectors["sector"] == selected_sector].iloc[0]

col_info1, col_info2, col_info3 = st.columns(3)
with col_info1:
    st.markdown(f"**產業分類：** {sector_info['category']}")
    st.markdown(f"**板塊狀態：** `{sector_info['status']}`")
with col_info2:
    st.markdown(f"**法人資金流向：** `{sector_info['flow']} 億`")
with col_info3:
    st.markdown(f"**漲跌幅：** `{sector_info['change']}%`")

st.markdown("#### 🎯 代表性成分股資金表現")
stock_df = pd.DataFrame(sector_info["stocks"], columns=["股票代號", "股票名稱", "漲跌幅", "法人買賣超"])
st.dataframe(stock_df, use_container_width=True, hide_index=True)

# 個人自選股追蹤清單
st.markdown("---")
st.subheader("⭐ 個人自選板塊監控清單")
user_watchlist = st.multiselect("新增至追蹤清單的板塊", df_sectors["sector"].tolist(), default=["半導體", "人工智慧與伺服器"])

if user_watchlist:
    watchlist_df = df_sectors[df_sectors["sector"].isin(user_watchlist)]
    st.table(watchlist_df[["sector", "category", "flow", "change", "status"]])
else:
    st.info("請從上方選單挑選您想關注的板塊清單。")
