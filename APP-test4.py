import datetime
import io
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊與資金流向戰情室", page_icon="🌊", layout="wide"
)


@st.cache_data(ttl=3600)
def get_twse_institutional_data(date_str):
  """直接從證交所官網抓取指定日期的三大法人買賣超日報 (T86)

  date_str 格式: YYYYMMDD
  """
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}"
  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }

  try:
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()

    if data.get("stat") == "OK" and "data" in data:
      columns = data["fields"]
      df = pd.DataFrame(data["data"], columns=columns)
      return df
    else:
      return pd.DataFrame()
  except Exception as e:
    st.error(f"連線證交所 API 失敗: {e}")
    return pd.DataFrame()


st.title("🌊 台股板塊與資金流向戰情室 (TWSE 官方資料)")
st.markdown(
    "直接串接臺灣證券交易所官方資料，追蹤三大法人在個股與板塊的資金流向。"
)

# 側邊欄控制項
st.sidebar.header("參數設定")

# 預設抓取前一個交易日
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str_api = query_date.strftime("%Y%m%d")
date_str_dash = query_date.strftime("%Y-%m-%d")

# 新增刪除 ETF 選項
exclude_etf = st.sidebar.checkbox(
    "排除 ETF (過濾代號開頭為 00 的基金)", value=True
)

# 資料載入
with st.spinner(f"正在向證交所擷取 {date_str_dash} 三大法人買賣超資料..."):
  df_raw = get_twse_institutional_data(date_str_api)

if df_raw.empty:
  st.warning(
      f"找不到 {date_str_dash} 的法人資料（可能為假日、非交易日或當日盤後資料尚未更新），請選擇其他日期。"
  )
else:
  # 欄位重新命名與格式整理（證交所 T86 回傳的欄位名稱處理）
  # 欄位通常為：['證券代號', '證券名稱', '外陸資買進股數(不含外資自營商)', '外陸資賣出股數(不含外資自營商)', '外陸資買賣超股數(不含外資自營商)', ...]
  try:
    df = pd.DataFrame()
    df["stock_id"] = df_raw.iloc[:, 0].astype(str).str.strip()
    df["stock_name"] = df_raw.iloc[:, 1].str.strip()

    # 轉換成張數 (原始資料為股數，除以 1000)
    # 欄位索引對應: 外資買賣超(4), 投信買賣超(10), 自營商買賣超合計(15), 三大法人買賣超合計(18)
    # 為了保險，透過欄位名稱尋找
    col_map = {col: i for i, col in enumerate(df_raw.columns)}

    def clean_num(val):
      if isinstance(val, str):
        return pd.to_numeric(val.replace(",", ""), errors="coerce")
      return pd.to_numeric(val, errors="coerce")

    # 尋找對應欄位名稱
    foreign_col = [c for c in df_raw.columns if "外陸資" in c and "買賣超" in c]
    trust_col = [c for c in df_raw.columns if "投信" in c and "買賣超" in c]
    dealer_col = [c for c in df_raw.columns if "自營商" in c and "買賣超" in c]
    total_col = [
        c for c in df_raw.columns if "三大法人" in c and "買賣超" in c
    ]

    df["外資"] = (
        clean_num(df_raw[foreign_col[0]]) / 1000 if foreign_col else 0
    )
    df["投信"] = clean_num(df_raw[trust_col[0]]) / 1000 if trust_col else 0

    # 自營商通常包含 自行買賣 與 避險，取合計欄位或加總
    if dealer_col:
      # 取出最後一個包含「買賣超」的自營商欄位通常是合計
      df["自營商"] = clean_num(df_raw[dealer_col[-1]]) / 1000
    else:
      df["自營商"] = 0

    df["三大法人合計"] = (
        clean_num(df_raw[total_col[0]]) / 1000
        if total_col
        else df["外資"] + df["投信"] + df["自營商"]
    )

  except Exception as e:
    st.error(f"解析證交所資料格式時發生錯誤: {e}")
    st.stop()

  # 簡易產業分類對照（示範用：可根據台股代號區間或外掛對照表）
  # 實務上可串接證交所產業類別 API，此處以代號區間做簡易示範分群
  def get_industry(stock_id):
    if stock_id.startswith("00"):
      return "ETF"
    elif stock_id in ["2330", "2317", "2454", "2308", "2382"]:
      return "半導體/電子權值"
    elif stock_id.startswith("2") or stock_id.startswith("3"):
      return "一般電子/傳產"
    elif stock_id.startswith("28"):
      return "金融保險"
    else:
      return "其他產業"


  df["industry_category"] = df["stock_id"].apply(get_industry)

  # 執行 ETF 篩選
  if exclude_etf:
    df = df[~df["stock_id"].str.startswith("00")]

  # 版面配置：區塊一、個股資金流向排行榜
  st.header(f"🔍 個股資金流向排行榜 ({date_str_dash})")

  col1, col2 = st.columns(2)
  with col1:
    selected_investor = st.selectbox(
        "選擇法人機構", ["三大法人合計", "外資", "投信", "自營商"]
    )
  with col2:
    sort_order = st.radio(
        "排序方式", ["買超最多 (由多到少)", "賣超最多 (由少到多)"], horizontal=True
    )

  is_ascending = True if "賣超" in sort_order else False
  df_sorted = df.sort_values(by=selected_investor, ascending=is_ascending)

  st.dataframe(
      df_sorted[
          [
              "stock_id",
              "stock_name",
              "industry_category",
              "外資",
              "投信",
              "自營商",
              "三大法人合計",
          ]
      ]
      .rename(columns={"stock_id": "股票代號", "stock_name": "股票名稱"})
      .style.format(
          {
              "外資": "{:,.2f} 張",
              "投信": "{:,.2f} 張",
              "自營商": "{:,.2f} 張",
              "三大法人合計": "{:,.2f} 張",
          }
      ),
      use_container_width=True,
  )

  # 版面配置：區塊二、板塊資金流向總覽
  st.header("📊 板塊資金流向總覽")
  sector_summary = (
      df.groupby("industry_category")[["外資", "投信", "自營商", "三大法人合計"]]
      .sum()
      .sort_values(by="三大法人合計", ascending=False)
  )

  st.dataframe(
      sector_summary.style.format("{:,.2f} 張").background_gradient(
          cmap="coolwarm", subset=["三大法人合計"]
      ),
      use_container_width=True,
  )
