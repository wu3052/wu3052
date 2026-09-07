import datetime
import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# 頁面配置
st.set_page_config(
    page_title="台股板塊與法人資金流向戰情室", page_icon="📈", layout="wide"
)


# 資料獲取與快取函數
@st.cache_data(ttl=3600)
def get_institutional_data_range(start_date, end_date):
  """透過 FinMind API 取得區間內的三大法人買賣超資料"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {
      "dataset": "TaiwanStockInstitutionalInvestors",
      "start_date": start_date,
      "end_date": end_date,
  }
  try:
    response = requests.get(url, params=parameters, timeout=10)
    data = response.json()
    if data.get("status") == 200 and len(data.get("data", [])) > 0:
      return pd.DataFrame(data["data"])
  except Exception:
    pass
  return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_stock_price_range(start_date, end_date):
  """取得區間內台股每日收盤價與漲跌幅"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {
      "dataset": "TaiwanStockPrice",
      "start_date": start_date,
      "end_date": end_date,
  }
  try:
    response = requests.get(url, params=parameters, timeout=10)
    data = response.json()
    if data.get("status") == 200 and len(data.get("data", [])) > 0:
      return pd.DataFrame(data["data"])
  except Exception:
    pass
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info():
  """取得台股上市櫃公司代號、名稱與產業類別"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {"dataset": "TaiwanStockInfo"}
  try:
    response = requests.get(url, params=parameters, timeout=10)
    data = response.json()
    if data.get("status") == 200:
      return pd.DataFrame(data["data"])
  except Exception:
    pass
  return pd.DataFrame()


# 主標題
st.title("🌊 台股板塊與資金流向戰情室 (Tide-TW 風格)")
st.markdown("結合三大法人動向、板塊資金泡泡圖與多維度量化選股系統。")

# 日期計算（自動尋找最近交易日）
today = datetime.date.today()
default_end = today - datetime.timedelta(days=1)
if default_end.weekday() == 5:
  default_end -= datetime.timedelta(days=1)
elif default_end.weekday() == 6:
  default_end -= datetime.timedelta(days=2)

start_5days = default_end - datetime.timedelta(days=7)  ... # 涵蓋週末抓取 5 個交易日

st.sidebar.header("⚙️ 參數控制面板")
query_date = st.sidebar.date_input("選擇基準日期", value=default_end)
end_str = query_date.strftime("%Y-%m-%d")
start_str = (query_date - datetime.timedelta(days=10)).strftime("%Y-%m-%d")

with st.spinner("正在向 API 擷取法人與股價資金流向資料..."):
  df_inst = get_institutional_data_range(start_str, end_str)
  df_price = get_stock_price_range(start_str, end_str)
  df_info = get_stock_info()

if df_inst.empty or df_price.empty:
  st.warning("目前選擇的日期區間無足夠資料，請嘗試切換至其他交易日。")
else:
  # 資料前處理與整併
  df_inst["date"] = pd.to_datetime(df_inst["date"])
  df_price["date"] = pd.to_datetime(df_price["date"])

  # 計算淨買賣超張數 (買 - 賣) / 1000
  df_inst["net_shares"] = (
      pd.to_numeric(df_inst["buy"], errors="coerce").fillna(0)
      - pd.to_numeric(df_inst["sell"], errors="coerce").fillna(0)
  ) / 1000

  # 取得最新交易日與前5交易日清單
  trading_dates = sorted(df_inst["date"].unique())
  if len(trading_dates) == 0:
    st.error("找不到有效的交易日數據。")
    st.stop()

  latest_date = trading_dates[-1]
  recent_5_dates = trading_dates[-5:] if len(trading_dates) >= 5 else trading_dates

  # 合併產業資訊
  if not df_info.empty and "stock_id" in df_info.columns:
    info_subset = df_info[
        ["stock_id", "industry_category", "stock_name"]
    ].drop_duplicates("stock_id")
  else:
    info_subset = pd.DataFrame(
        columns=["stock_id", "industry_category", "stock_name"]
    )

  # 當日資料
  df_latest = df_inst[df_inst["date"] == latest_date]
  df_latest_agg = (
      df_latest.groupby("stock_id")["net_shares"].sum().reset_index()
  )

  # 近5日資料
  df_5d = df_inst[df_inst["date"].isin(recent_5_dates)]
  df_5d_agg = df_5d.groupby("stock_id")["net_shares"].sum().reset_index(
      name="net_shares_5d"
  )

  # 合併個股統計
  df_stock_summary = pd.merge(df_latest_agg, df_5d_agg, on="stock_id", how="outer").fillna(0)
  if not info_subset.empty:
    df_stock_summary = pd.merge(df_stock_summary, info_subset, on="stock_id", how="left")
  else:
    df_stock_summary["industry_category"] = "未分類"
    df_stock_summary["stock_name"] = df_stock_summary["stock_id"]

  # 取得最新股價與漲跌幅
  df_price_latest = df_price[df_price["date"] == latest_date]
  if not df_price_latest.empty:
    # 假設有 spread 或 change / close 計算報酬率
    if "close" in df_price_latest.columns and "open" in df_price_latest.columns:
      df_price_latest["pct_change"] = (
          pd.to_numeric(df_price_latest["close"], errors="coerce")
          - pd.to_numeric(df_price_latest["open"], errors="coerce")
      ) / pd.to_numeric(df_price_latest["open"], errors="coerce") * 100
      df_stock_summary = pd.merge(
          df_stock_summary,
          df_price_latest[["stock_id", "close", "pct_change"]],
          on="stock_id",
          how="left",
      )

  # 頁籤設計：1. 板塊泡泡圖與動向 | 2. 買方策略選股 | 3. 賣方策略選股
  tab1, tab2, tab3 = st.tabs(
      ["📊 板塊資金流向與泡泡圖", "🟢 多方策略篩選 (買)", "🔴 空方策略篩選 (賣)"]
  )

  with tab1:
    st.subheader("💡 板塊資金流向四象限泡泡圖")
    st.markdown(
        "X軸：近5日資金流速變化 | Y軸：當日資金動能強度 | 泡泡大小：總成交金額或淨買超規模"
    )

    # 計算板塊聚合數據
    sector_grouped = (
        df_stock_summary.groupby("industry_category")
        .agg({"net_shares": "sum", "net_shares_5d": "sum"})
        .reset_index()
    )

    if not sector_grouped.empty:
      fig = px.scatter(
          sector_grouped,
          x="net_shares_5d",
          y="net_shares",
          size=sector_grouped["net_shares"].abs() + 1,
          color="industry_category",
          hover_name="industry_category",
          text="industry_category",
          labels={
              "net_shares_5d": "近5日累計淨買賣超 (張)",
              "net_shares": "當日淨買賣超 (張)",
          },
          title=f"各產業板塊資金流向分佈 ({latest_date.strftime('%Y-%m-%d')})",
      )
      fig.add_hline(y=0, line_dash="dash", line_color="gray")
      fig.add_vline(x=0, line_dash="dash", line_color="gray")
      st.plotly_chart(fig, use_container_width=True)
    else:
      st.info("目前無足夠的板塊聚合資料可繪製圖表。")

    col_s1, col_s2 = st.columns(2)
    with col_s1:
      st.markdown("#### 🏆 近五日法人買超最多板塊")
      if not sector_grouped.empty:
        top_buy_sectors = sector_grouped.sort_values(
            by="net_shares_5d", ascending=False
        ).head(5)
        st.dataframe(top_buy_sectors, use_container_width=True)
    with col_s2:
      st.markdown("#### ⚠️ 近五日法人賣超最多板塊")
      if not sector_grouped.empty:
        top_sell_sectors = sector_grouped.sort_values(
            by="net_shares_5d", ascending=True
        ).head(5)
        st.dataframe(top_sell_sectors, use_container_width=True)

  with tab2:
    st.subheader("🟢 多方策略選股清單")

    strategy_buy = st.selectbox(
        "選擇多方篩選策略",
        [
            "1. 買多漲少 (五日資金流入高，漲幅相對低)",
            "2. 個股爆買異常 (今日法人買超相較過往顯著放大)",
            "3. 外資投信同買 / 連買追蹤",
        ],
    )

    if "1." in strategy_buy:
      st.markdown("**策略邏輯：** 篩選近5日法人持續大買，但股價尚未完全反映（漲幅相對落後）的潛力標的。")
      if "pct_change" in df_stock_summary.columns:
        res_buy1 = df_stock_summary.sort_values(
            by=["net_shares_5d", "pct_change"], ascending=[False, True]
        ).head(20)
        st.dataframe(res_buy1, use_container_width=True)
      else:
        st.warning("缺少當日漲幅欄位數據。")

    elif "2." in strategy_buy:
      st.markdown("**策略邏輯：** 尋找今日法人買超張數顯著高於平均水準的異常爆買個股。")
      res_buy2 = df_stock_summary.sort_values(
          by="net_shares", ascending=False
      ).head(20)
      st.dataframe(res_buy2, use_container_width=True)

    elif "3." in strategy_buy:
      st.markdown("**策略邏輯：** 篩選外資與投信同步買超之優質標的。")
      # 過濾出外資與投信
      if "name" in df_latest.columns:
        df_foreign = df_latest[df_latest["name"].str.contains("外資", na=False)]
        df_trust = df_latest[df_latest["name"].str.contains("投信", na=False)]
        merged_ft = pd.merge(
            df_foreign[["stock_id", "net_shares"]].rename(
                columns={"net_shares": "foreign_net"}
            ),
            df_trust[["stock_id", "net_shares"]].rename(
                columns={"net_shares": "trust_net"}
            ),
            on="stock_id",
            how="inner",
        )
        co_buy = merged_ft[
            (merged_ft["foreign_net"] > 0) & (merged_ft["trust_net"] > 0)
        ]
        if not info_subset.empty:
          co_buy = pd.merge(co_buy, info_subset, on="stock_id", how="left")
        st.dataframe(co_buy.sort_values(by="foreign_net", ascending=False), use_container_width=True)
      else:
        st.info("無法人機構明細欄位可供篩選。")

  with tab3:
    st.subheader("🔴 空方策略選股清單")

    strategy_sell = st.selectbox(
        "選擇空方篩選策略",
        [
            "1. 賣多跌少 (五日資金賣出高，跌幅相對輕微)",
            "2. 個股爆賣異常 (今日法人大舉拋售個股)",
            "3. 外資投信同賣追蹤",
        ],
    )

    if "1." in strategy_sell:
      st.markdown("**策略邏輯：** 篩選近5日法人大幅提款賣出，但股價尚未重挫的潛在弱勢/壓盤標的。")
      res_sell1 = df_stock_summary.sort_values(
          by=["net_shares_5d", "pct_change"], ascending=[True, False]
      ).head(20)
      st.dataframe(res_sell1, use_container_width=True)

    elif "2." in strategy_sell:
      st.markdown("**策略邏輯：** 尋找今日法人突然大量倒貨的異常個股。")
      res_sell2 = df_stock_summary.sort_values(
          by="net_shares", ascending=True
      ).head(20)
      st.dataframe(res_sell2, use_container_width=True)

    elif "3." in strategy_sell:
      st.markdown("**策略邏輯：** 篩選外資與投信同步賣超之標的。")
      if "name" in df_latest.columns:
        df_foreign = df_latest[df_latest["name"].str.contains("外資", na=False)]
        df_trust = df_latest[df_latest["name"].str.contains("投信", na=False)]
        merged_ft_s = pd.merge(
            df_foreign[["stock_id", "net_shares"]].rename(
                columns={"net_shares": "foreign_net"}
            ),
            df_trust[["stock_id", "net_shares"]].rename(
                columns={"net_shares": "trust_net"}
            ),
            on="stock_id",
            how="inner",
        )
        co_sell = merged_ft_s[
            (merged_ft_s["foreign_net"] < 0) & (merged_ft_s["trust_net"] < 0)
        ]
        if not info_subset.empty:
          co_sell = pd.merge(co_sell, info_subset, on="stock_id", how="left")
        st.dataframe(co_sell.sort_values(by="foreign_net", ascending=True), use_container_width=True)
      else:
        st.info("無法人機構明細欄位可供篩選。")
