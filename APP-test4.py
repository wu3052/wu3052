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
def get_twse_institutional_data(date_str):
  """抓取 TWSE 上市三大法人買賣超日報 (T86)"""
  # 將日期格式轉為 TWSE 需要的 YYYYMMDD
  date_code = date_str.replace("-", "")
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_code}&selectType=ALLBUT0999"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    if data.get("stat") == "OK":
      fields = data["fields"]  # 欄位名稱
      rows = data["data"]  # 內容
      df = pd.DataFrame(rows, columns=fields)
      return df
  except Exception as e:
    print(f"TWSE API 擷取錯誤: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_tpex_institutional_data(date_str):
  """抓取 TPEx 上櫃三大法人買賣明細資訊 (OpenAPI)"""
  # TPEx 日期格式為民國年份 YYYYMMDD (例如 1150907)
  dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
  roc_year = dt.year - 1911
  date_code = f"{roc_year:03d}{dt.month:02d}{dt.day:02d}"

  url = f"https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?d={date_code}"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    if isinstance(data, list) and len(data) > 0:
      return pd.DataFrame(data)
  except Exception as e:
    print(f"TPEx API 擷取錯誤: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info_mapping():
  """取得上市櫃股票名稱與產業對照表（透過 FinMind 輔助對照產業，若無token可自行載入靜態對照）"""
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


@st.cache_data(ttl=3600)
def load_market_data_with_fallback(end_date_str, max_days=5):
  """自動回溯查詢最近一個有交易資料的日期"""
  current_date = datetime.datetime.strptime(end_date_str, "%Y-%m-%d").date()

  for _ in range(max_days):
    while current_date.weekday() >= 5:  # 略過週末
      current_date -= datetime.timedelta(days=1)

    check_date_str = current_date.strftime("%Y-%m-%d")

    # 同步嘗試抓取上市與上櫃
    df_twse = get_twse_institutional_data(check_date_str)
    df_tpex = get_tpex_institutional_data(check_date_str)

    if not df_twse.empty or not df_tpex.empty:
      return df_twse, df_tpex, check_date_str

    current_date -= datetime.timedelta(days=1)

  return pd.DataFrame(), pd.DataFrame(), None


st.title("🌊 台股板塊與資金流向戰情室（證交所/櫃買中心官方直連）")
st.markdown(
    "直接對接 TWSE 證交所與 TPEx 櫃買中心公開資料，追蹤三大法人資金板塊流向。"
)

# 側邊欄日期選擇
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇基準日期", value=default_date)
date_str = query_date.strftime("%Y-%m-%d")

with st.spinner("正在向 證交所 與 櫃買中心 官方 API 同步抓取資金流向資料..."):
  df_twse, df_tpex, actual_date = load_market_data_with_fallback(date_str)
  df_info = get_stock_info_mapping()

if df_twse.empty and df_tpex.empty:
  st.warning(
      "找不到近期可用的官方法人資料，可能為連續長假或 API 尚未釋出，請嘗試選擇更早的日期。"
  )
else:
  if actual_date != date_str:
    st.info(
        f"ℹ️ 您選擇的日期 `{date_str}` 尚無完整資料，已自動切換至最近有資料的交易日：`{actual_date}`"
    )

  # 1. 處理上市資料 (TWSE T86)
  processed_twse = []
  if not df_twse.empty:
    # TWSE T86 欄位通常為: 證券代號, 證券名稱, 外陸資買賣超張數, 投信買賣超張數, 自營商買賣超張數(自行買賣), 自營商買賣超張數(避險), 三大法人買賣超張數...
    # 欄位名稱對應清理
    cols = [
        "stock_id",
        "stock_name",
        "foreign_net",
        "trust_net",
        "dealer_self_net",
        "dealer_hedge_net",
        "total_net",
    ]
    # 取出需要的欄位 (T86 欄位索引固定)
    try:
      temp_df = df_twse.iloc[:, [0, 1, 4, 10, 14, 17, 18]].copy()
      temp_df.columns = [
          "stock_id",
          "stock_name",
          "外資",
          "投信",
          "自營商(自行)",
          "自營商(避險)",
          "合計",
      ]
      temp_df["市場"] = "上市"
      processed_twse.append(temp_df)
    except Exception as e:
      st.error(f"解析上市資料格式發生錯誤: {e}")

  df_twse_clean = (
      pd.concat(processed_twse, ignore_index=True)
      if processed_twse
      else pd.DataFrame()
  )

  # 2. 處理上櫃資料 (TPEx OpenAPI)
  processed_tpex = []
  if not df_tpex.empty:
    # TPEx 欄位：SecuritiesCompanyCode (代號), SecuritiesCompanyName (名稱), 外資買賣超, 投信買賣超, 自營商買賣超 ...
    try:
      # 欄位對應可能會根據 OpenAPI 版本微調，進行防呆檢查
      col_map = {
          "SecuritiesCompanyCode": "stock_id",
          "SecuritiesCompanyName": "stock_name",
          "ForeignInvestorsNetBuySellShares": "外資",
          "SITCTradeNetBuySellShares": "投信",
          "DealersNetBuySellShares": "自營商",
      }
      # 兼容處理
      tpex_df = df_tpex.rename(columns=col_map)
      if "stock_id" in tpex_df.columns:
        tpex_df["自營商(自行)"] = tpex_df.get("DealersSelfNetBuySellShares", 0)
        tpex_df["自營商(避險)"] = tpex_df.get(
            "DealersHedgeNetBuySellShares", 0
        )
        tpex_df["合計"] = (
            pd.to_numeric(
                tpex_df["外資"].astype(str).str.replace(",", ""), errors="coerce"
            )
            .fillna(0)
            + pd.to_numeric(
                tpex_df["投信"].astype(str).str.replace(",", ""), errors="coerce"
            )
            .fillna(0)
            + pd.to_numeric(
                tpex_df["自營商"].astype(str).str.replace(",", ""), errors="coerce"
            )
            .fillna(0)
        )
        tpex_df["市場"] = "上櫃"
        processed_tpex.append(
            tpex_df[
                [
                    "stock_id",
                    "stock_name",
                    "外資",
                    "投信",
                    "自營商(自行)",
                    "自營商(避險)",
                    "合計",
                    "市場",
                ]
            ]
        )
    except Exception as e:
      st.error(f"解析上櫃資料格式發生錯誤: {e}")

  df_tpex_clean = (
      pd.concat(processed_tpex, ignore_index=True)
      if processed_tpex
      else pd.DataFrame()
  )

  # 合併上市櫃
  df_all = pd.concat([df_twse_clean, df_tpex_clean], ignore_index=True)

  if not df_all.empty:
    # 數值清洗（移除逗號並轉為數字，單位轉換為張）
    for col in ["外資", "投信", "自營商(自行)", "自營商(避險)", "合計"]:
      if col in df_all.columns:
        df_all[col] = (
            pd.to_numeric(
                df_all[col].astype(str).str.replace(",", "").str.strip(),
                errors="coerce",
            )
            .fillna(0)
            / 1000
        )  # 官方單位通常為股，除以 1000 轉為張

    # 對接產業類別
    if not df_info.empty and "stock_id" in df_info.columns:
      df_all = pd.merge(
          df_all, df_info[["stock_id", "industry_category"]], on="stock_id", how="left"
      )
    else:
      df_all["industry_category"] = "未分類"
    df_all["industry_category"] = df_all["industry_category"].fillna("未分類")

    # 區塊一：板塊資金流向總覽
    st.header("📊 各產業板塊資金流向總覽 (單位：張)")
    sector_pivot = pd.pivot_table(
        df_all,
        values="合計",
        index="industry_category",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    sector_pivot = sector_pivot.sort_values(by="合計", ascending=False)

    st.dataframe(
        sector_pivot.rename(
            columns={
                "industry_category": "產業板塊",
                "合計": "三大法人淨買賣超合計(張)",
            }
        )
        .style.format({"三大法人淨買賣超合計(張)": "{:,.2f}"})
        .background_gradient(cmap="coolwarm", subset=["三大法人淨買賣超合計(張)"]),
        use_container_width=True,
    )

    # 區塊二：個股資金流向排行榜
    st.header("🔍 個股資金流向排行榜")
    col1, col2 = st.columns(2)
    with col1:
      target_investor = st.selectbox(
          "選擇法人/合計", ["合計", "外資", "投信", "自營商(自行)"]
      )
    with col2:
      sort_dir = st.radio(
          "排序方向", ["買超最多 (由多到少)", "賣超最多 (由少到多)"], horizontal=True
      )

    is_asc = True if "賣超" in sort_dir else False
    df_ranked = df_all.sort_values(by=target_investor, ascending=is_asc)

    st.dataframe(
        df_ranked[
            [
                "stock_id",
                "stock_name",
                "市場",
                "industry_category",
                "外資",
                "投信",
                "合計",
            ]
        ]
        .rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "industry_category": "產業",
                "合計": "三大法人合計(張)",
            }
        )
        .style.format(
            {
                "外資": "{:,.2f}",
                "投信": "{:,.2f}",
                "三大法人合計(張)": "{:,.2f}",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning("整理後無資料，請確認 API 連線狀態。")
