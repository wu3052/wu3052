import datetime
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="台股板塊與資金流向戰情室", page_icon="🌊", layout="wide"
)


@st.cache_data(ttl=3600)
def get_twse_institutional_data(date_str):
  """直接從證交所 OpenAPI 抓取三大法人買賣超日報表

  date_str 格式需為 YYYYMMDD (例如 20260907)
  """
  # 證交所三大法人買賣超日報 API (以民國年月日或西元年月日視 API 版本而定，此處使用通用公開資料集網址)
  # 註：證交所 OpenAPI JSON 網址範例
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?date={date_str}&response=json"

  try:
    response = requests.get(url, timeout=10)
    data = response.json()
    if data.get("stat") == "OK":
      fields = data.get("fields", [])
      rows = data.get("data", [])
      df = pd.DataFrame(rows, columns=fields)
      return df
  except Exception as e:
    st.error(f"連線證交所 API 發生錯誤: {e}")

  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_info_twse():
  """取得證交所上市股票代號與產業類別"""
  url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
  try:
    response = requests.get(url, timeout=10)
    data = response.json()
    df = pd.DataFrame(data)
    return df
  except:
    return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室（證交所直連版）")
st.markdown("直接串接臺灣證券交易所官方資料，追蹤三大法人資金流向。")

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
# 證交所 API 通常需要 YYYYMMDD 格式
date_str_api = query_date.strftime("%Y%m%d")
date_str_display = query_date.strftime("%Y-%m-%d")

with st.spinner(f"正在向證交所擷取 {date_str_display} 法人資料..."):
  df_inst = get_twse_institutional_data(date_str_api)
  df_info = get_stock_info_twse()

if df_inst.empty:
  st.warning(
      f"找不到 {date_str_display} 的證交所法人資料。可能原因：\n1."
      " 該日為假日或休市日。\n2. 證交所當日資料尚未收盤結算或釋出。\n建議選擇更早的交易日。"
  )
else:
  # 證交所 T86 回傳欄位整理（通常欄位包含：證券代號, 證券名稱, 外陸資買賣超股數(不含自營商)...等）
  # 依實際欄位進行重新命名與整理
  st.success(f"成功載入 {date_str_display} 證交所法人資料！")

  # 顯示原始資料供檢驗欄位結構
  with st.expander("查看原始資料欄位結構"):
    st.dataframe(df_inst.head())

  st.dataframe(df_inst, use_container_width=True)
