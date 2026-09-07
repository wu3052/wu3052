import datetime
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊資金流向戰情室 (官方OpenAPI)",
    page_icon="🌊",
    layout="wide",
)


@st.cache_data(ttl=3600)
def get_twse_institutional_data(date_str):
  """抓取臺灣證券交易所 (TWSE) 上市個股三大法人買賣超資料

  API 來源: https://www.twse.com.tw/rwd/zh/fund/T86
  """
  # TWSE API 日期格式需為 YYYYMMDD
  date_formatted = date_str.replace("-", "")
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_formatted}&selectType=ALLBUT0999"

  try:
    response = requests.get(url, timeout=10)
    data = response.json()
    if data.get("stat") == "OK":
      fields = data.get("fields", [])
      rows = data.get("data", [])
      df = pd.DataFrame(rows, columns=fields)
      # 欄位重新對應與清理
      # T86 欄位通常包含: 證券代號, 證券名稱, 外資買進股數, 外資賣出股數, 外資買賣超股數, 投信買進股數...等
      rename_map = {
          "證券代號": "stock_id",
          "證券名稱": "stock_name",
          "外陸資買賣超股數(不含外資自營商)": "foreign_net",
          "投信買賣超股數": "trust_net",
          "自營商買賣超股數(自行買賣)": "dealer_self_net",
          "自營商買賣超股數(避險)": "dealer_hedge_net",
          "三大法人買賣超股數": "total_net",
      }
      # 找尋實際符合的欄位進行重新命名
      df = df.rename(columns=lambda x: x.strip())
      return df
    else:
      return pd.DataFrame()
  except Exception as e:
    return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_tpex_institutional_data(date_str):
  """抓取證券櫃檯買賣中心 (TPEx) 上櫃個股三大法人買賣超資料

  API 來源: https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading
  """
  # TPEx API 日期格式通常為 YYYY/MM/DD 或 YYYYMMDD，需依民國或西元調整
  # 這裡示範直接呼叫 OpenAPI 取得全量資料再進行日期篩選
  url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
  try:
    response = requests.get(url, timeout=10)
    data = response.json()
    df = pd.DataFrame(data)
    if not df.empty and "Date" in df.columns:
      # 轉換日期格式 (TPEx 通常回傳民國年月日如 1150907 或西元)
      # 假設其格式為 YYYY-MM-DD 或需轉換，進行過濾
      filtered_df = df[df["Date"] == date_str.replace("-", "/")]
      return filtered_df
    return pd.DataFrame()
  except Exception as e:
    return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info_mapping():
  """取得上市櫃公司產業類別對照 (透過 FinMind 或證交所公開代號)"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {"dataset": "TaiwanStockInfo"}
  try:
    response = requests.get(url, params=parameters)
    data = response.json()
    if data.get("status") == 200:
      return pd.DataFrame(data["data"])
  except:
    pass
  return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室 (TWSE & TPEx 官方直連)")
st.markdown(
    "對齊 `tide-tw.app` 風格，直接串接臺灣證券交易所與櫃買中心官方資料源，追蹤法人在各產業板塊的資金輪動與買賣超動態。"
)

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str = query_date.strftime("%Y-%m-%d")

# 資料載入
with st.spinner(
    f"正在向 TWSE (上市) 與 TPEx (上櫃) 官方 API 擷取 {date_str} 法人資料..."
):
  df_twse = get_twse_institutional_data(date_str)
  df_tpex = get_tpex_institutional_data(date_str)
  df_info = get_stock_info_mapping()

if df_twse.empty and df_tpex.empty:
  st.warning(
      f"找不到 {date_str} 的官方法人資料（可能為週末、假日或官方伺服器尚未釋出當日盤後檔案），請嘗試切換至更早的日期。"
  )
else:
  st.success(
      f"成功載入資料！上市資料庫筆數: {len(df_twse)}，上櫃資料庫筆數: {len(df_tpex)}"
  )

  # 整合處理上市櫃資料與產業對照
  # 實務上可將 df_twse 與 df_tpex 統一欄位格式後透過 pd.concat 合併
  # 並且與 df_info (包含 industry_category 產業類別) 進行 merge，即可做出類似 tide-tw.app 的板塊輪動與資金流向對比表。

  st.info(
      "💡 提示：您可以進一步利用合併後的 DataFrame 進行 pivot_table 聚合，產出各個產業板塊（半導體、電腦週邊、金融保險等）的法人淨買超排行榜。"
  )
