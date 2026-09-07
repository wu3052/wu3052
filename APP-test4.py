import datetime
from io import StringIO
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# 頁面設定
st.set_page_config(
    page_title="台股三大法人資金流向板塊",
    page_icon="🌊",
    layout="wide",
)

st.title("🌊 台股三大法人資金流向與板塊追蹤")
st.markdown("追蹤外資、投信、自營商每日在各產業板塊與個股的資金流向脈動。")


# 取得台股股票基本資料與產業對應 (可快取)
@st.cache_data(ttl=86400)
def get_stock_info():
  url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
  response = requests.get(url)
  data = response.json()
  if data.get("status") == 200:
    df = pd.DataFrame(data["data"])
    return df[["stock_id", "stock_name", "industry_category"]]
  return pd.DataFrame(columns=["stock_id", "stock_name", "industry_category"])


# 取得三大法人買賣超資料
@st.cache_data(ttl=3600)
def get_institutional_investors(date_str):
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {
      "dataset": "TaiwanStockInstitutionalInvestors",
      "start_date": date_str,
      "end_date": date_str,
  }
  response = requests.get(url, params=parameters)
  data = response.json()
  if data.get("status") == 200 and len(data.get("data", [])) > 0:
    df = pd.DataFrame(data["data"])
    return df
  return pd.DataFrame()


# 計算智慧預設日期（考量每日盤後資料通常於下午 18:00 左右才會更新發布，以及週末假日）
def get_smart_default_date():
  now = datetime.datetime.now()
  d = now.date()
  # 如果今天是週末，或今天是平日但時間小於下午 6 點 (18:00)，則預設往前推一天（或推至最近的交易日）
  if d.weekday() >= 5 or (d.weekday() < 5 and now.hour < 18):
    if d.weekday() == 6:  # 星期日 -> 星期五
      d = d - datetime.timedelta(days=2)
    elif d.weekday() == 5:  # 星期六 -> 星期五
      d = d - datetime.timedelta(days=1)
    else:  # 平日但未滿 18:00 -> 昨天
      d = d - datetime.timedelta(days=1)
      if d.weekday() == 5:  # 昨天是週六 -> 星期五
        d = d - datetime.timedelta(days=1)
      elif d.weekday() == 6:  # 昨天是週日 -> 星期五
        d = d - datetime.timedelta(days=2)
  return d


# 側邊欄設定
st.sidebar.header("設定面板")
default_date = get_smart_default_date()

selected_date = st.sidebar.date_input(
    "選擇交易日期", value=default_date, max_value=datetime.date.today()
)
date_str = selected_date.strftime("%Y-%m-%d")

st.sidebar.info(
    "💡 提示：臺灣證券交易所與櫃買中心的三大法人買賣超數據通常會在**每日下午 18:00 左右**結算並對外公布。若您在下午 6 點前查詢當日資料會查無結果，系統已自動為您帶入最近一個完整的交易日。"
)

# 載入資料
with st.spinner("正在載入法人資金流向資料..."):
  df_info = get_stock_info()
  df_inst = get_institutional_investors(date_str)

if df_inst.empty:
  st.warning(
      f"查無 {date_str} 的法人買賣超資料（可能是該日為假日、尚未過下午 18:00 更新時間，或 API 尚未釋出），請嘗試切換至前一個交易日。"
  )
else:
  # 資料處理：整理三大法人買賣超張數與金額
  df_inst["buy"] = pd.to_numeric(df_inst["buy"], errors="coerce").fillna(0)
  df_inst["sell"] = pd.to_numeric(df_inst["sell"], errors="coerce").fillna(0)
  df_inst["net"] = df_inst["buy"] - df_inst["sell"]

  # 依 stock_id 聚合三大法人合計買賣超
  df_agg = (
      df_inst.groupby("stock_id")
      .agg({"buy": "sum", "sell": "sum", "net": "sum"})
      .reset_index()
  )

  # 合併產業別與名稱
  df_merged = pd.merge(df_agg, df_info, on="stock_id", how="left")
  df_merged["industry_category"] = (
      df_merged["industry_category"].fillna("其他").astype(str)
  )
  df_merged["stock_name"] = df_merged["stock_name"].fillna(
      df_merged["stock_id"]
  )

  # 頂部總覽指標
  total_net = df_merged["net"].sum()
  top_buy_stock = df_merged.loc[df_merged["net"].idxmax()]
  top_sell_stock = df_merged.loc[df_merged["net"].idxmin()]

  col1, col2, col3 = st.columns(3)
  col1.metric(
      f"({date_str}) 全體法人淨買賣超(張)",
      f"{total_net:,.0f}",
      delta="買超" if total_net > 0 else "賣超",
  )
  col2.metric(
      "單日買超冠軍",
      f"{top_buy_stock['stock_name']} ({top_buy_stock['stock_id']})",
      f"+{top_buy_stock['net']:,.0f} 張",
  )
  col3.metric(
      "單日賣超冠軍",
      f"{top_sell_stock['stock_name']} ({top_sell_stock['stock_id']})",
      f"{top_sell_stock['net']:,.0f} 張",
  )

  st.markdown("---")

  # 區塊一：板塊資金流向 (Industry Flow)
  st.subheader("📊 產業板塊資金流向")
  df_sector = (
      df_merged.groupby("industry_category")["net"].sum().reset_index()
  )
  df_sector = df_sector.sort_values(by="net", ascending=False)

  fig_sector = px.bar(
      df_sector,
      x="industry_category",
      y="net",
      title=f"{date_str} 各產業板塊三大法人淨買賣超張數",
      labels={
          "industry_category": "產業板塊",
          "net": "淨買賣超張數 (張)",
      },
      color="net",
      color_continuous_scale="RdYlGn",
  )
  st.plotly_chart(fig_sector, use_container_width=True)

  # 區塊二：個股資金流向排行榜
  st.subheader("🔍 個股資金流向明細")

  tab1, tab2 = st.tabs(["🔥 法人買超前 20 名", "💧 法人賣超前 20 名"])

  with tab1:
    top_buys = df_merged.sort_values(by="net", ascending=False).head(20)
    st.dataframe(
        top_buys[[
            "stock_id",
            "stock_name",
            "industry_category",
            "buy",
            "sell",
            "net",
        ]].rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "industry_category": "產業",
                "buy": "買進張數",
                "sell": "賣出張數",
                "net": "淨買超張數",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

  with tab2:
    top_sells = df_merged.sort_values(by="net", ascending=True).head(20)
    st.dataframe(
        top_sells[[
            "stock_id",
            "stock_name",
            "industry_category",
            "buy",
            "sell",
            "net",
        ]].rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "industry_category": "產業",
                "buy": "買進張數",
                "sell": "賣出張數",
                "net": "淨買超張數",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )
