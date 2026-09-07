import datetime
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊與資金流向戰情室 (官方OpenAPI)",
    page_icon="🌊",
    layout="wide",
)


@st.cache_data(ttl=3600)
def fetch_twse_t86(date_str):
  """抓取臺灣證券交易所 (TWSE) 上市三大法人買賣超日報 (T86)"""
  # 日期格式: YYYYMMDD
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  try:
    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    if data.get("stat") == "OK" and "data" in data:
      df = pd.DataFrame(data["data"])
      # 欄位對應 (根據 TWSE T86 官方格式)
      # 0:代號, 1:名稱, 4:外資淨買超, 7:投信淨買超, 14:三大法人淨買超總計 (視版本可能微調，這裡進行安全對應)
      cols = [
          "stock_id",
          "stock_name",
          "foreign_buy_val",
          "foreign_sell_val",
          "foreign_net",
          "sitc_buy_val",
          "sitc_sell_val",
          "sitc_net",
          "dealer_self_buy",
          "dealer_self_sell",
          "dealer_self_net",
          "dealer_hedge_buy",
          "dealer_hedge_sell",
          "dealer_hedge_net",
          "total_net",
      ]
      if df.shape[1] >= len(cols):
        df = df.iloc[:, : len(cols)]
        df.columns = cols
        df["market"] = "上市"
        return df
  except Exception as e:
    print(f"TWSE API Error: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_tpex_data():
  """抓取證券櫃檯買賣中心 (TPEx) 上櫃三大法人買賣超 OpenAPI"""
  url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }
  try:
    res = requests.get(url, headers=headers, timeout=10)
    data = res.json()
    if isinstance(data, list) and len(data) > 0:
      df = pd.DataFrame(data)
      # 欄位對應轉換 (TPEx OpenAPI 欄位名稱)
      # 通常包含: Date, StockCode, StockName, ForeignInvestorNetBuySell, InvestmentTrustNetBuySell, DealerNetBuySell...
      return df
  except Exception as e:
    print(f"TPEx API Error: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_industry_mapping():
  """取得上市櫃股票產業類別對照 (透過 FinMind 或證交所公開清單)"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {"dataset": "TaiwanStockInfo"}
  try:
    res = requests.get(url, params=parameters, timeout=10)
    data = res.json()
    if data.get("status") == 200:
      return pd.DataFrame(data["data"])
  except:
    pass
  return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室 (官方API直連版)")
st.markdown("對接臺灣證券交易所與櫃買中心官方資料來源，追蹤法人資金脈動。")

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str_t86 = query_date.strftime("%Y%m%d")
date_str_hyphen = query_date.strftime("%Y-%m-%d")

with st.spinner("正在向證交所與櫃買中心官方擷取資料..."):
  df_twse = fetch_twse_t86(date_str_t86)
  df_tpex = fetch_tpex_data()
  df_info = get_stock_industry_mapping()

# 處理上市資料
combined_list = []
if not df_twse.empty:
  # 清理數值格式 (去除逗號)
  for col in [
      "foreign_net",
      "sitc_net",
      "dealer_self_net",
      "dealer_hedge_net",
      "total_net",
  ]:
    if col in df_twse.columns:
      df_twse[col] = (
          df_twse[col].astype(str).str.replace(",", "").astype(float)
      )
  combined_list.append(
      df_twse[
          [
              "stock_id",
              "stock_name",
              "foreign_net",
              "sitc_net",
              "total_net",
              "market",
          ]
      ]
  )

# 處理上櫃資料
if not df_tpex.empty:
  # 根據 TPEx 欄位名稱動態對應
  # 欄位可能為 StockCode, StockName, ForeignInvestorNetBuySell 等
  code_col = (
      "StockCode"
      if "StockCode" in df_tpex.columns
      else ("SecuritiesCompanyCode" if "SecuritiesCompanyCode" in df_tpex.columns else None)
  )
  name_col = (
      "StockName"
      if "StockName" in df_tpex.columns
      else ("SecuritiesCompanyName" if "SecuritiesCompanyName" in df_tpex.columns else None)
  )

  if code_col:
    tpex_processed = pd.DataFrame()
    tpex_processed["stock_id"] = df_tpex[code_col]
    tpex_processed["stock_name"] = (
        df_tpex[name_col] if name_col else df_tpex[code_col]
    )

    # 抓取外資、投信、自營商欄位並轉換數值
    for target_col, api_cols in [
        (
            "foreign_net",
            [
                "ForeignInvestorNetBuySell",
                "foreignInvestorsNetBuySell",
                "外資買賣超",
            ],
        ),
        (
            "sitc_net",
            [
                "InvestmentTrustNetBuySell",
                "sitcNetBuySell",
                "投信買賣超",
            ],
        ),
        (
            "total_net",
            ["TotalNetBuySell", "totalNetBuySell", "三大法人買賣超合計"],
        ),
    ]:
      found = False
      for ac in api_cols:
        if ac in df_tpex.columns:
          tpex_processed[target_col] = (
              df_tpex[ac].astype(str).str.replace(",", "").astype(float)
          )
          found = True
          break
      if not found:
        tpex_processed[target_col] = 0.0

    tpex_processed["market"] = "上櫃"
    combined_list.append(tpex_processed)

if len(combined_list) == 0:
  st.warning(
      f"無法取得 {date_str_hyphen} 的官方法人資料（可能是週末、非交易日或API尚未發布），請嘗試選擇其他日期。"
  )
else:
  df_all = pd.concat(combined_list, ignore_index=True)

  # 整併產業類別
  if not df_info.empty and "stock_id" in df_info.columns:
    df_all = pd.merge(
        df_all,
        df_info[["stock_id", "industry_category"]],
        on="stock_id",
        how="left",
    )
  else:
    df_all["industry_category"] = "未分類"

  df_all["industry_category"] = df_all["industry_category"].fillna("未分類")

  # 轉換單位為「張」（官方原始資料通常為股數，需除以 1000）
  for col in ["foreign_net", "sitc_net", "total_net"]:
    if col in df_all.columns:
      df_all[col] = df_all[col] / 1000.0

  # 重新命名欄位以便呈現
  df_all = df_all.rename(
      columns={
          "foreign_net": "外資淨買超(張)",
          "sitc_net": "投信淨買超(張)",
          "total_net": "三大法人淨買超(張)",
      }
  )

  # 區塊一：板塊資金流向總覽
  st.header("📊 板塊資金流向總覽")
  sector_pivot = pd.pivot_table(
      df_all,
      values="三大法人淨買超(張)",
      index="industry_category",
      columns="market",
      aggfunc="sum",
      fill_value=0,
  )

  if "上市" not in sector_pivot.columns:
    sector_pivot["上市"] = 0
  if "上櫃" not in sector_pivot.columns:
    sector_pivot["上櫃"] = 0

  sector_pivot["市場合計"] = sector_pivot["上市"] + sector_pivot["上櫃"]
  sector_pivot = sector_pivot.sort_values(by="市場合計", ascending=False)

  st.dataframe(
      sector_pivot.style.format("{:,.2f} 張").background_gradient(
          cmap="coolwarm", subset=["市場合計"]
      ),
      use_container_width=True,
  )

  # 區塊二：個股資金流向排行
  st.header("🔍 個股資金流向排行榜")
  col1, col2, col3 = st.columns(3)

  with col1:
    market_filter = st.selectbox("選擇市場", ["全部", "上市", "上櫃"])
  with col2:
    metric_choice = st.selectbox(
        "排序指標", ["三大法人淨買超(張)", "外資淨買超(張)", "投信淨買超(張)"]
    )
  with col3:
    sort_dir = st.radio(
        "排序方向", ["買超最多 (由多到少)", "賣超最多 (由少到多)"], horizontal=True
    )

  filtered_df = df_all.copy()
  if market_filter != "all" and market_filter != "全部":
    filtered_df = filtered_df[filtered_df["market"] == market_filter]

  is_asc = True if "賣超" in sort_dir else False
  if metric_choice in filtered_df.columns:
    filtered_df = filtered_df.sort_values(by=metric_choice, ascending=is_asc)

  display_cols = [
      "stock_id",
      "stock_name",
      "market",
      "industry_category",
      "外資淨買超(張)",
      "投信淨買超(張)",
      "三大法人淨買超(張)",
  ]
  available_cols = [c for c in display_cols if c in filtered_df.columns]

  st.dataframe(
      filtered_df[available_cols]
      .rename(
          columns={
              "stock_id": "股票代號",
              "stock_name": "股票名稱",
              "market": "市場別",
              "industry_category": "產業類別",
          }
      )
      .style.format(
          {
              "外資淨買超(張)": "{:,.2f}",
              "投信淨買超(張)": "{:,.2f}",
              "三大法人淨買超(張)": "{:,.2f}",
          }
      ),
      use_container_width=True,
  )
