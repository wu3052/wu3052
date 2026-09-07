import datetime
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊與資金流向追蹤系統", page_icon="🌊", layout="wide"
)


# 快取資料以提升效能
@st.cache_data(ttl=3600)
def get_institutional_data(date_str):
    """透過 FinMind API 取得三大法人買賣超資料

    (亦可自行替換為證交所/櫃買中心 OpenAPI)
    """
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {
        "dataset": "TaiwanStockInstitutionalInvestors",
        "start_date": date_str,
        "end_date": date_str,
        # 'token': '你的免費FinMind_Token',
    }
    response = requests.get(url, params=parameters)
    data = response.json()
    if data.get("status") == 200 and len(data.get("data", [])) > 0:
        return pd.DataFrame(data["data"])
    return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info():
    """取得台股上市櫃公司代號與產業類別對照"""
    url = "https://api.finmindtrade.com/api/v4/data"
    parameters = {"dataset": "TaiwanStockInfo"}
    response = requests.get(url, params=parameters)
    data = response.json()
    if data.get("status") == 200:
        return pd.DataFrame(data["data"])
    return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室")
st.markdown("追蹤三大法人（外資、投信、自營商）在各產業板塊與個股的資金流向動態。")

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
# 簡易排除週末
if default_date.weekday() == 5:
    default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
    default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str = query_date.strftime("%Y-%m-%d")

# 資料載入
with st.spinner("正在向 API 擷取三大法人與產業對照資料..."):
    df_inst = get_institutional_data(date_str)
    df_info = get_stock_info()

if df_inst.empty:
    st.warning(
        f"找不到 {date_str} 的法人資料（可能為假日、非交易日或 API 尚未更新），請選擇其他日期。"
    )
else:
    # 資料整併：將法人資料與產業類別進行合併
    if not df_info.empty and "stock_id" in df_info.columns:
        df_merged = pd.merge(
            df_inst,
            df_info[["stock_id", "industry_category", "stock_name"]],
            on="stock_id",
            how="left",
        )
    else:
        df_merged = df_inst
        df_merged["industry_category"] = "未分類"
        df_merged["stock_name"] = df_merged["stock_id"]

    # 計算淨買賣超張數（買進 - 賣出）/ 1000
    if "buy" in df_merged.columns and "sell" in df_merged.columns:
        df_merged["net_shares"] = (
            pd.to_numeric(df_merged["buy"], errors="coerce")
            - pd.to_numeric(df_merged["sell"], errors="coerce")
        ) / 1000

    # 版面配置：區塊一、板塊資金流向總覽
    st.header("📊 板塊資金流向總覽")

    if "industry_category" in df_merged.columns and "name" in df_merged.columns:
        # 樞紐分析：各產業在不同法人買賣超的表現
        sector_pivot = pd.pivot_table(
            df_merged,
            values="net_shares",
            index="industry_category",
            columns="name",
            aggfunc="sum",
            fill_value=0,
        )

        # 計算三大法人合計買賣超欄位以供排序
        sector_pivot["Total_Net"] = sector_pivot.sum(axis=1)
        sector_pivot = sector_pivot.sort_values(
            by="Total_Net", ascending=False
        )

        st.dataframe(
            sector_pivot.style.format("{:,.2f} 張").background_gradient(
                cmap="coolwarm", subset=["Total_Net"]
            ),
            use_container_width=True,
        )

    # 版面配置：區塊二、個股資金流向排行
    st.header("🔍 個股資金流向排行榜")

    col1, col2 = st.columns(2)
    with col1:
        investor_list = (
            df_merged["name"].unique().tolist()
            if "name" in df_merged.columns
            else []
        )
        selected_investor = st.selectbox("選擇法人機構", investor_list)

    with col2:
        sort_order = st.radio(
            "排序方式", ["買超最多 (由多到少)", "賣超最多 (由少到多)"], horizontal=True
        )

    if selected_investor:
        filtered_df = df_merged[df_merged["name"] == selected_investor].copy()
        is_ascending = True if "賣超" in sort_order else False
        filtered_df = filtered_df.sort_values(
            by="net_shares", ascending=is_ascending
        )

        display_cols = [
            "stock_id",
            "stock_name",
            "industry_category",
            "buy",
            "sell",
            "net_shares",
        ]
        available_cols = [c for c in display_cols if c in filtered_df.columns]

        st.dataframe(
            filtered_df[available_cols]
            .rename(
                columns={
                    "stock_id": "股票代號",
                    "stock_name": "股票名稱",
                    "industry_category": "產業",
                    "buy": "買進股數",
                    "sell": "賣出股數",
                    "net_shares": "淨買賣超(張)",
                }
            )
            .style.format(
                {
                    "買進股_數": "{:,.0f}",
                    "賣出股數": "{:,.0f}",
                    "淨買賣超(張)": "{:,.2f}",
                }
            ),
            use_container_width=True,
        )
