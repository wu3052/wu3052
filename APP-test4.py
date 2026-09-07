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
  """抓取 TWSE 上市三大法人買賣超日報 (格式: YYYYMMDD)"""
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    if data.get("stat") == "OK":
      fields = data["fields"]
      rows = data["data"]
      df = pd.DataFrame(rows, columns=fields)
      # 清理欄位名稱與數字格式
      # 欄位通常包含: 證券代號, 證券名稱, 外陸資買賣超張數(不含自營), 投信買賣超張數, 自營商買賣超張數(自行買賣/避險)等
      return df
  except Exception as e:
    print(f"TWSE API Error: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_tpex_institutional_data(date_str):
  """抓取 TPEx 上櫃三大法人買賣超資料 (格式: YYYY/MM/DD 或 YYYY-MM-DD 依民國/西元轉換)"""
  # TPEx 日期格式通常為民國或西元，openapi 接收格式多為西元 YYYY-MM-DD
  url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    df = pd.DataFrame(data)
    # 篩選指定日期 (TPEx api通常回傳全部或近期資料，需用 Date 過濾，格式如 2026-09-07)
    if not df.empty and "Date" in df.columns:
      # 轉換日期格式比對
      df = df[df["Date"] == date_str]
      return df
  except Exception as e:
    print(f"TPEx API Error: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info_meta():
  """取得上市櫃代號與產業對照（此處透過 FinMind 輔助基本資訊對照，若要完全原生可對接證交所Mops或證券基本檔）"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {"dataset": "TaiwanStockInfo"}
  res = requests.get(url, params=parameters)
  data = res.json()
  if data.get("status") == 200:
    return pd.DataFrame(data["data"])
  return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室 (TWSE & TPEx 官方直連)")
st.markdown("追蹤上市櫃三大法人（外資、投信、自營商）在各產業板塊與個股的資金流向。")

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str_dash = query_date.strftime("%Y-%m-%d")  # 2026-09-07
date_str_compact = query_date.strftime("%Y%m%d")  # 20260907

with st.spinner("正在向證交所與櫃買中心官方 API 擷取法人資金流向資料..."):
  # 1. 抓取上市資料 (TWSE T86)
  df_twse = get_twse_institutional_data(date_str_compact)
  # 2. 抓取上櫃資料 (TPEx OpenAPI)
  df_tpex = get_tpex_institutional_data(date_str_dash)
  # 3. 取得上市櫃產業與名稱對照
  df_info = get_stock_info_meta()

if df_twse.empty and df_tpex.empty:
  st.warning(
      f"找不到 {date_str_dash} 的上市櫃法人資料（可能是假日、非交易日或當日資料尚未結算發布）。"
  )
else:
  processed_list = []

  # 處理上市資料結構 (TWSE)
  if not df_twse.empty:
    # 欄位對應清理 (T86 回傳欄位名稱含有空白或特定名稱)
    # 通常為 ['證券代號', '證券名稱', '外陸資買賣超張數(不含自營商)', '投信買賣超張數', '自營商買賣超張數(自行買賣)', '自營商買賣超張數(避險)', '三大法人買賣超張數']
    try:
      twse_formatted = pd.DataFrame()
      twse_formatted["stock_id"] = df_twse.iloc[:, 0].astype(str).str.strip()
      twse_formatted["stock_name"] = df_twse.iloc[:, 1].astype(str).str.strip()

      # 清理千分位逗號並轉數值
      def clean_num(val):
        if pd.isna(val):
          return 0.0
        return (
            float(str(val).replace(",", "").replace("+", ""))
            if str(val).strip() != ""
            else 0.0
        )

      # 取得外資、投信、自營商淨買賣超 (單位: 張)
      twse_formatted["Foreign_Net"] = df_twse.iloc[:, 2].apply(clean_num)
      twse_formatted["SITC_Net"] = df_twse.iloc[:, 3].apply(clean_num)
      # 自營商通常分自行買賣與避險，加總起來
      dealer_1 = (
          df_twse.iloc[:, 4].apply(clean_num)
          if df_twse.shape[1] > 4
          else 0.0
      )
      dealer_2 = (
          df_twse.iloc[:, 5].apply(clean_num)
          if df_twse.shape[1] > 5
          else 0.0
      )
      twse_formatted["Dealer_Net"] = dealer_1 + dealer_2
      twse_formatted["Total_Net"] = (
          twse_formatted["Foreign_Net"]
          + twse_formatted["SITC_Net"]
          + twse_formatted["Dealer_Net"]
      )
      twse_formatted["market"] = "上市"
      processed_list.append(twse_formatted)
    except Exception as e:
      st.error(format(e))

  # 處理上櫃資料結構 (TPEx OpenAPI)
  if not df_tpex.empty:
    try:
      tpex_formatted = pd.DataFrame()
      tpex_formatted["stock_id"] = (
          df_tpex["SecuritiesCompanyCode"].astype(str).str.strip()
      )
      tpex_formatted["stock_name"] = df_tpex["SecuritiesName"].astype(str).str.strip()

      def clean_tpex_num(val):
        if pd.isna(val):
          return 0.0
        return float(str(val).replace(",", ""))

      # TPEx 欄位：ForeignInvestorNetChange, InvestmentTrustNetChange, DealerNetChange 等
      tpex_formatted["Foreign_Net"] = (
          df_tpex["ForeignInvestorNetChange"].apply(clean_tpex_num)
          if "ForeignInvestorNetChange" in df_tpex.columns
          else 0.0
      )
      tpex_formatted["SITC_Net"] = (
          df_tpex["InvestmentTrustNetChange"].apply(clean_tpex_num)
          if "InvestmentTrustNetChange" in df_tpex.columns
          else 0.0
      )
      tpex_formatted["Dealer_Net"] = (
          df_tpex["DealerNetChange"].apply(clean_tpex_num)
          if "DealerNetChange" in df_tpex.columns
          else 0.0
      )
      tpex_formatted["Total_Net"] = (
          tpex_formatted["Foreign_Net"]
          + tpex_formatted["SITC_Net"]
          + tpex_formatted["Dealer_Net"]
      )
      tpex_formatted["market"] = "上櫃"
      processed_list.append(tpex_formatted)
    except Exception as e:
      st.error(format(e))

  if len(processed_list) > 0:
    df_all = pd.concat(processed_list, ignore_index=True)

    # 結合產業類別
    if not df_info.empty and "stock_id" in df_info.columns:
      df_final = pd.merge(
          df_all,
          df_info[["stock_id", "industry_category"]],
          on="stock_id",
          how="left",
      )
      df_final["industry_category"] = df_final["industry_category"].fillna(
          "其他/未分類"
      )
    else:
      df_final = df_all
      df_final["industry_category"] = "其他/未分類"

    # 區塊一：板塊資金流向總覽
    st.header("📊 板塊資金流向總覽 (三大法人合計)")
    sector_summary = (
        df_final.groupby("industry_category")[
            ["Foreign_Net", "SITC_Net", "Dealer_Net", "Total_Net"]
        ]
        .sum()
        .sort_values(by="Total_Net", ascending=False)
    )

    st.dataframe(
        sector_summary.rename(
            columns={
                "Foreign_Net": "外資淨買賣超(張)",
                "SITC_Net": "投信淨買賣超(張)",
                "Dealer_Net": "自營商淨買賣超(張)",
                "Total_Net": "法人合計淨買賣超(張)",
            }
        ).style.format("{:,.2f} 張").background_gradient(
            cmap="coolwarm", subset=["法人合計淨買賣超(張)"]
        ),
        use_container_width=True,
    )

    # 區塊二：個股資金流向排行榜
    st.header("🔍 個股資金流向排行榜")
    c1, c2, c3 = st.columns(3)
    with c1:
      sel_market = st.selectbox("市場別", ["全部", "上市", "上櫃"])
    with c2:
      sel_role = st.selectbox(
          "法人別",
          ["Total_Net", "Foreign_Net", "SITC_Net", "Dealer_Net"],
          format_func=lambda x: {
              "Total_Net": "三大法人合計",
              "Foreign_Net": "外資",
              "SITC_Net": "投信",
              "Dealer_Net": "自營商",
          }[x],
      )
    with c3:
      sel_sort = st.radio(
          "排序", ["買超最多 (多->少)", "賣超最多 (少->多)"], horizontal=True
      )

    df_filtered = df_final.copy()
    if sel_market != "全部":
      df_filtered = df_filtered[df_filtered["market"] == sel_market]

    is_asc = True if "賣超" in sel_sort else False
    df_filtered = df_filtered.sort_values(by=sel_role, ascending=is_asc)

    st.dataframe(
        df_filtered[
            [
                "stock_id",
                "stock_name",
                "market",
                "industry_category",
                "Foreign_Net",
                "SITC_Net",
                "Dealer_Net",
                "Total_Net",
            ]
        ]
        .rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "market": "市場",
                "industry_category": "產業類別",
                "Foreign_Net": "外資(張)",
                "SITC_Net": "投信(張)",
                "Dealer_Net": "自營商(張)",
                "Total_Net": "合計買賣超(張)",
            }
        )
        .style.format(
            {
                "外資(張)": "{:,.2f}",
                "投信(張)": "{:,.2f}",
                "自營商(張)": "{:,.2f}",
                "合計買賣超(張)": "{:,.2f}",
            }
        ),
        use_container_width=True,
    )
  else:
    st.warning("無法解析當日法人資料格式，請稍後再試。")
