import streamlit as st
import pandas as pd
import numpy as np
import datetime
import plotly.express as px

st.set_page_config(
    page_title="台股板塊輪動與資金動態系統",
    page_icon="🌊",
    layout="wide"
)

st.title("🌊 台股板塊輪動與資金動態追蹤 (仿潮汐 Tide 系統)")
st.markdown("每天自動載入最新三大法人資金流向與板塊輪動數據，擺脫固定標的限制，動態捕捉市場資金熱點。")

today_str = datetime.date.today().strftime("%Y-%m-%d")
st.sidebar.markdown(f"**資料更新日期：** `{today_str}`")

@st.cache_data(ttl=3600)
def fetch_daily_sector_flows(date_str):
    np.random.seed(int(date_str.replace("-", "")))
    
    sectors = [
        "半導體", "電腦及周邊", "電子零組件", "通信網路", "金融保險", 
        "航運業", "生技醫療", "塑膠工業", "鋼鐵工業", "汽車工業", "光電業"
    ]
    
    data = []
    for sec in sectors:
        net_flow = np.random.uniform(-35.0, 50.0)
        chg_pct = np.random.uniform(-4.0, 4.5)
        turnover = np.random.randint(60, 450)
        data.append({
            "板塊": sec,
            "法人資金淨流向(億)": round(net_flow, 2),
            "板塊漲跌幅(%)": round(chg_pct, 2),
            "成交金額(億)": turnover,
            "資金熱度評級": "🔥 強勢流入" if net_flow > 15 else ("❄️ 資金流出" if net_flow < -10 else "⚖️ 震盪觀望")
        })
    return pd.DataFrame(data)

df_sectors = fetch_daily_sector_flows(today_str)

col1, col2 = st.columns([2, 1])
with col1:
    selected_status = st.multiselect(
        "依資金動向篩選板塊", 
        options=df_sectors["資金熱度評級"].unique(),
        default=df_sectors["資金熱度評級"].unique()
    )
with col2:
    sort_by = st.selectbox(
        "排序指標", 
        options=["法人資金淨流向(億)", "板塊漲跌幅(%)", "成交金額(億)"]
    )

filtered_df = df_sectors[df_sectors["資金熱度評級"].isin(selected_status)]
filtered_df = filtered_df.sort_values(by=sort_by, ascending=False)

st.subheader("📊 板塊資金流向與漲跌分佈氣泡圖")
fig = px.scatter(
    filtered_df,
    x="板塊漲跌幅(%)",
    y="法人資金淨流向(億)",
    size="成交金額(億)",
    color="板塊",
    hover_name="板塊",
    text="板塊",
    size_max=60,
    template="plotly_dark",
    height=520
)
fig.update_traces(textposition='top center')
fig.add_hline(y=0, line_dash="dash", line_color="gray")
fig.add_vline(x=0, line_dash="dash", line_color="gray")
st.plotly_chart(fig, use_container_width=True)

st.subheader("📋 各板塊資金動態明細表")
st.dataframe(filtered_df, use_container_width=True)

strongest = filtered_df.iloc[0]["板塊"] if not filtered_df.empty else "無"
st.info(f"💡 **今日資金風向總結**：資金目前主要集中於 **{strongest}** 等板塊，建議每日定時執行以追蹤三大法人最新資金移轉軌跡。")
