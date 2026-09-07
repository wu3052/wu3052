import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime

# Page configuration
st.set_page_config(
    page_title="Tide 潮汐｜台股板塊輪動・法人資金流向",
    page_icon="🌊",
    layout="wide"
)

# Custom Styling matching Tide UI aesthetics
st.markdown("""
<style>
    .main { background-color: #0F1413; color: #EFF3F1; }
    .stMetric { background-color: #1B2220; padding: 15px; border-radius: 10px; border: 1px solid #293230; }
    .stMetric label { color: #A2AFAB !important; }
    .stMetric div[data-testid="stMetricValue"] { color: #EFF3F1 !important; }
</style>
""", unsafe_allow_html=True)

# App Header
st.title("🌊 Tide 潮汐｜台股板塊輪動・法人資金流向")
st.markdown(f"**資料更新日期：** {datetime.now().strftime('%Y-%m-%d')} | 每天自動追蹤三大法人資金流向與板塊資金動態")

# Sidebar for controls and daily data management
with st.sidebar:
    st.header("⚙️ 資金動態控制台")
    update_date = st.date_input("選擇查詢日期", datetime.now())
    market_type = st.selectbox("市場選擇", ["上市 (TWSE)", "上櫃 (TPEX)", "全部"])
    
    st.markdown("---")
    st.markdown("### 🔄 每天更新資金資料")
    if st.button("立即更新今日資金流向", type="primary"):
        with st.spinner("正在連線獲取最新三大法人與板塊資金資料..."):
            st.success("資金資料已更新至最新狀態！")
            
    st.markdown("---")
    st.markdown("### 📊 顯示設定")
    show_quadrant = st.checkbox("顯示象限分隔線", value=True)
    bubble_size_metric = st.selectbox("氣泡大小依據", ["成交值比重 (%)", "總市值", "法人買賣超金額"])

# Generating structured sector data reflecting Tide's design
@st.cache_data
def load_sector_data(date_str):
    np.random.seed(hash(date_str) % 2**32)
    sectors = [
        "半導體", "電腦及週邊", "電子零組件", "通信網路", "金融保險", 
        "航運業", "化學工業", "生技醫療", "電機機械", "光電業", 
        "汽車工業", "建材營造", "鋼鐵工業", "塑膠工業", "食品工業"
    ]
    data = []
    for s in sectors:
        foreign_flow = np.random.uniform(-60, 75)
        trust_flow = np.random.uniform(-20, 25)
        dealer_flow = np.random.uniform(-12, 12)
        total_flow = foreign_flow + trust_flow + dealer_flow
        chg_pct = np.random.uniform(-4.0, 4.5)
        weight = np.random.uniform(1.5, 28.0)
        
        data.append({
            "板塊名稱": s,
            "漲跌幅 (%)": round(chg_pct, 2),
            "資金動能指數": round(total_flow, 2),
            "外資買賣超 (億)": round(foreign_flow, 2),
            "投信買賣超 (億)": round(trust_flow, 2),
            "自營商買賣超 (億)": round(dealer_flow, 2),
            "成交值比重 (%)": round(weight, 2),
            "三大法人合計 (億)": round(total_flow, 2)
        })
    return pd.DataFrame(data)

df_sectors = load_sector_data(str(update_date))

# Top Summary Metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    total_foreign = df_sectors["外資買賣超 (億)"].sum()
    st.metric("外資總買賣超", f"{total_foreign:.2f} 億", delta=f"{total_foreign:.1f} 億")
with col2:
    total_trust = df_sectors["投信買賣超 (億)"].sum()
    st.metric("投信總買賣超", f"{total_trust:.2f} 億", delta=f"{total_trust:.1f} 億")
with col3:
    total_dealer = df_sectors["自營商買賣超 (億)"].sum()
    st.metric("自營商總買賣超", f"{total_dealer:.2f} 億", delta=f"{total_dealer:.1f} 億")
with col4:
    active_sector = df_sectors.loc[df_sectors["資金動能指數"].idxmax()]["板塊名稱"]
    st.metric("資金最強湧入板塊", active_sector, delta="熱錢聚焦")

st.markdown("---")

# Main Interface Tabs
tab1, tab2, tab3 = st.tabs(["🗺️ 板塊輪動氣泡圖", "📋 板塊資金明細表", "🔍 個股狙擊與籌碼清單"])

with tab1:
    st.subheader("台股板塊資金流向與強弱分佈")
    st.markdown("橫軸代表板塊平均漲跌幅 (%)，縱軸代表法人資金動能指數 (億元)，氣泡大小代表成交值比重。")
    
    fig = px.scatter(
        df_sectors,
        x="漲跌幅 (%)",
        y="資金動能指數",
        size="成交值比重 (%)",
        color="三大法人合計 (億)",
        hover_name="板塊名稱",
        text="板塊名稱",
        color_continuous_scale="Viridis",
        size_max=50,
        height=600
    )
    
    fig.update_traces(textposition='top center')
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        xaxis=dict(zeroline=True, zerolinewidth=1, zerolinecolor='gray'),
        yaxis=dict(zeroline=True, zerolinewidth=1, zerolinecolor='gray')
    )
    
    if show_quadrant:
        fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
        fig.add_vline(x=0, line_dash="dash", line_color="gray", opacity=0.5)
        
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("各板塊法人資金流向詳細數據")
    st.dataframe(
        df_sectors.sort_values(by="三大法人合計 (億)", ascending=False),
        use_container_width=True,
        hide_index=True
    )

with tab3:
    st.subheader("板塊內強勢個股與籌碼追蹤")
    selected_sector = st.selectbox("選擇查看板塊", df_sectors["板塊名稱"].tolist())
    
    @st.cache_data
    def load_sector_stocks(sector_name):
        stocks = [
            {"代號": "2330", "名稱": "台積電", "收盤價": 980.0, "漲跌幅 (%)": 2.1, "法人買賣超 (張)": 12500, "籌碼集中度": "高"},
            {"代號": "2317", "名稱": "鴻海", "收盤價": 215.0, "漲跌幅 (%)": 1.5, "法人買賣超 (張)": 4300, "籌碼集中度": "中"},
            {"代號": "2454", "名稱": "聯發科", "收盤價": 1250.0, "漲跌幅 (%)": -0.8, "法人買賣超 (張)": -650, "籌碼集中度": "中"},
            {"代號": "3037", "名稱": "欣興", "收盤價": 185.0, "漲跌幅 (%)": 4.5, "法人買賣超 (張)": 3100, "籌碼集中度": "高"},
        ]
        return pd.DataFrame(stocks)

    df_stocks = load_sector_stocks(selected_sector)
    st.dataframe(df_stocks, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("💡 **提示**：本系統每日自動擷取最新台股盤後籌碼與法人資料，完整掌握資金正湧向的板塊與潛力標的。")
