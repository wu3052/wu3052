import datetime
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊與資金流向戰情室 (官方 API 版)", page_icon="🌊", layout="wide"
)


@st.cache_data(ttl=3600)
def fetch_twse_t86(date_str):
  """抓取臺灣證券交易所 (TWSE) 上市三大法人買賣超資料 (T86 端點)"""
  # date_str 格式為 YYYYMMDD
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
  try:
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
      jdata = res.json()
      if jdata.get("stat") == "OK" and "data" in jdata:
        df = pd.DataFrame(jdata["data"], columns=jdata["fields"])
        return df
  except Exception as e:
    st.error(f"連線 TWSE API 發生錯誤: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=3600)
def fetch_tpex_data():
  """抓取證券櫃檯買賣中心 (TPEx) 上櫃三大法人買賣明細 OpenAPI"""
  url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
  try:
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
      data = res.json()
      if isinstance(data, list) and len(data) > 0:
        return pd.DataFrame(data)
  except Exception as e:
    st.error(f"連線 TPEx API 發生錯誤: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def fetch_stock_info():
  """取得上市櫃公司代號與產業類別對照 (透過證交所 OpenAPI)"""
  url = (
      "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"  # 上市公司基本資料
  )
  try:
    res = requests.get(url, timeout=10)
    if res.status_code == 200:
      return pd.DataFrame(res.json())
  except Exception:
    pass
  return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室 (TWSE & TPEx 官方 API)")
st.markdown(
    "直接對接證交所 T86 報表與櫃買中心 OpenAPI，追蹤全市場聰明錢流向。"
)

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日 (上市適用)", value=default_date)
twse_date_str = query_date.strftime("%Y%m%d")
display_date_str = query_date.strftime("%Y-%m-%d")

# 資料載入
with st.spinner("正在向證交所與櫃買中心官方 API 擷取最新籌碼資料..."):
  df_twse_raw = fetch_twse_t86(twse_date_str)
  df_tpex_raw = fetch_tpex_data()
  df_info = fetch_stock_info()

if df_twse_raw.empty and df_tpex_raw.empty:
  st.warning(
      f"找不到 {display_date_str} 的法人資料（可能為非交易日、週末或官方尚未更新盤後報表）。"
  )
else:
  processed_dfs = []

  # 1. 處理上市資料 (TWSE T86)
  if not df_twse_raw.empty:
    # 欄位對照清理 (移除逗號並轉為數字)
    # T86 欄位通常包含：證券代號, 證券名稱, 外陸資買賣超股數(合計), 投信買賣超股數, 自營商買賣超股數, 三大法人買賣超股數合計等
    cols = df_twse_raw.columns
    # 重新對應標準欄位名稱
    df_twse = pd.DataFrame()
    df_twse["stock_id"] = df_twse_raw[cols[0]]
    df_twse["stock_name"] = df_twse_raw[cols[1]]
    df_twse["market"] = "上市"

    # 清理數值函數
    def clean_num(val):
      if pd.isna(val):
        return 0.0
      return float(
          str(val).replace(",", "").replace("+", "").strip() or 0
      ) / 1000  # 轉為張數

    # 取得外資、投信、自營商、合計淨買賣超欄位 (依 T86 標準欄位索引)
    # 索引 8: 外資及陸資買賣超股數, 11: 投信買賣超股數, 14: 自營商買賣超股數合計, 15: 三大法人買賣超股數合計
    if len(cols) >= 16:
      df_twse["foreign_net"] = df_twse_raw[cols[8]].apply(clean_num)
      df_twse["trust_net"] = df_twse_raw[cols[11]].apply(clean_num)
      df_twse["dealer_net"] = df_twse_raw[cols[14]].apply(clean_num)
      df_twse["total_net"] = df_twse_raw[cols[15]].apply(clean_num)
      processed_dfs.append(df_twse)

  # 2. 處理上櫃資料 (TPEx OpenAPI)
  if not df_tpex_raw.empty:
    # TPEx 欄位通常包含：Date, StockCode, StockName, ForeignInvestorNetChange, InvestmentTrustNetChange, DealerNetChange, TotalNetChange 等
    # 檢查欄位名稱
    if "StockCode" in df_tpex_raw.columns:
      df_tpex = pd.DataFrame()
      df_tpex["stock_id"] = df_tpex_raw["StockCode"]
      df_tpex["stock_name"] = df_tpex_raw.get("StockName", df_tpex["stock_id"])
      df_tpex["market"] = "上櫃"

      def clean_tpex_num(val):
        if pd.isna(val):
          return 0.0
        return float(
            str(val).replace(",", "").replace("+", "").strip() or 0
        ) / 1000

      # 根據實際欄位名稱動態抓取
      f_col = next(
          (c for c in df_tpex_raw.columns if "Foreign" in c or "外資" in c), None
      )
      t_col = next(
          (
              c
              for c in df_tpex_raw.columns
              if "InvestmentTrust" in c or "投信" in c
          ),
          None,
      )
      d_col = next(
          (c for c in df_tpex_raw.columns if "Dealer" in c or "自營商" in c),
          None,
      )
      tot_col = next(
          (c for c in df_tpex_raw.columns if "Total" in c or "合計" in c), None
      )

      df_tpex["foreign_net"] = (
          df_tpex_raw[f_col].apply(clean_tpex_num) if f_col else 0.0
      )
      df_tpex["trust_net"] = (
          df_tpex_raw[t_col].apply(clean_tpex_num) if t_col else 0.0
      )
      df_tpex["dealer_net"] = (
          df_tpex_raw[d_col].apply(clean_tpex_num) if d_col else 0.0
      )
      df_tpex["total_net"] = (
          df_tpex_raw[tot_col].apply(clean_tpex_num) if tot_col else 0.0
      )
      processed_dfs.append(df_tpex)

  if processed_dfs:
    df_all = pd.concat(processed_dfs, ignore_index=True)

    # 結合產業別
    if not df_info.empty and "公司代號" in df_info.columns:
      df_info = df_info.rename(
          columns={"公司代號": "stock_id", "產業別": "industry_category"}
      )
      df_merged = pd.merge(
          df_all,
          df_info[["stock_id", "industry_category"]],
          on="stock_id",
          how="left",
      )
    else:
      df_merged = df_all

    df_merged["industry_category"] = df_merged["industry_category"].fillna(
        "其他/未分類"
    )

    # 版面配置：區塊一、板塊資金流向總覽
    st.header("📊 板塊資金流向總覽")

    sector_pivot = (
        df_merged.groupby("industry_category")[
            ["foreign_net", "trust_net", "dealer_net", "total_net"]
        ]
        .sum()
        .sort_values(by="total_net", ascending=False)
    )

    st.dataframe(
        sector_pivot.rename(
            columns={
                "foreign_net": "外資淨買賣超(張)",
                "trust_net": "投信淨買賣超(張)",
                "dealer_net": "自營商淨買賣超(張)",
                "total_net": "三大法人合計(張)",
            }
        )
        .style.format("{:,.2f} 張")
        .background_gradient(cmap="coolwarm", subset=["三大法人合計(張)"]),
        use_container_width=True,
    )

    # 版面配置：區塊二、個股資金流向排行榜
    st.header("🔍 個股資金流向排行榜")

    col1, col2, col3 = st.columns(3)
    with col1:
      market_filter = st.selectbox("市場別", ["全部", "上市", "上櫃"])
    with col2:
      investor_col = st.selectbox(
          "觀察法人",
          [
              "三大法人合計",
              "外資淨買賣超",
              "投信淨買賣超",
              "自營商淨買賣超",
          ],
      )
    with col3:
      sort_dir = st.radio(
          "排序", ["買超最多 (多->少)", "賣超最多 (少->多)"], horizontal=True
      )

    filtered_df = df_merged.copy()
    if market_filter != "全部":
      filtered_df = filtered_df[filtered_df["market"] == market_filter]

    col_map = {
        "三大法人合計": "total_net",
        "外資淨買賣超": "foreign_net",
        "投信淨買賣超": "trust_net",
        "自營商淨買賣超": "dealer_net",
    }
    target_col = col_map[investor_col]
    is_ascending = True if "賣超" in sort_dir else False

    filtered_df = filtered_df.sort_values(by=target_col, ascending=is_ascending)

    st.dataframe(
        filtered_df[
            [
                "stock_id",
                "stock_name",
                "market",
                "industry_category",
                "foreign_net",
                "trust_net",
                "dealer_net",
                "total_net",
            ]
        ]
        .rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "market": "市場",
                "industry_category": "產業類別",
                "foreign_net": "外資(張)",
                "trust_net": "投信(張)",
                "dealer_net": "自營商(張)",
                "total_net": "三大法人合計(張)",
            }
        )
        .style.format(
            {
                "外資(張)": "{:,.2f}",
                "投信(張)": "{:,.2f}",
                "自營商(張)": "{:,.2f}",
                "三大法人合計(張)": "{:,.2f}",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning("無法解析官方 API 回傳的法人結構資料，請確認 API 格式或稍後再試。")
