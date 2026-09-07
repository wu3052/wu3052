import datetime
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="台股板塊與三大法人資金流向", page_icon="📈", layout="wide"
)


@st.cache_data(ttl=3600)
def fetch_twse_institutional_data(date_str: str) -> pd.DataFrame:
  """抓取證交所(TWSE)上市個股三大法人買賣超資料"""
  # 格式化日期為 YYYYMMDD
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=all"

  try:
    response = requests.get(url, timeout=10)
    data = response.json()
    if data.get("stat") == "OK":
      fields = data["fields"]
      rows = data["data"]
      df = pd.DataFrame(rows, columns=fields)
      return df
    else:
      return pd.DataFrame()
  except Exception as e:
    st.error(f"連線證交所 API 失敗: {e}")
    return pd.DataFrame()


def clean_twse_data(df: pd.DataFrame) -> pd.DataFrame:
  """清洗證交所資料格式，將字串轉為數值"""
  if df.empty:
    return df

  # 欄位重新對應與清理 (TWSE 欄位通常包含代號、名稱、外陸資買賣超、投信買賣超、自營商買賣超等)
  # 欄位範例: 0:代號, 1:名稱, 2:外資買賣超股數..., 10:三大法人買賣超股數
  col_mapping = {
      df.columns[0]: "股票代號",
      df.columns[1]: "股票名稱",
      df.columns[4]: "外資買賣超",
      df.columns[10]: "投信買賣超",
      df.columns[15]: "自營商買賣超",
      df.columns[18]: "三大法人買賣超合計",
  }

  # 篩選並重新命名需要的欄位
  available_cols = [c for c in col_mapping.keys() if c in df.columns]
  if len(available_cols) < 4:
    # 萬一證交所欄位調整，回傳原始前幾欄
    return df

  df_clean = df[available_cols].rename(columns=col_mapping)

  # 移除逗號並轉為數字
  for col in df_clean.columns:
    if col not in ["股票代號", "股票名稱"]:
      df_clean[col] = (
          df_clean[col].astype(str).str.replace(",", "").str.replace("—", "0")
      )
      df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce").fillna(0)
      # 轉換單位為「張」(原始資料通常為股，除以 1000)
      df_clean[col] = df_clean[col] / 1000

  return df_clean


@st.cache_data
def load_stock_industry_mapping() -> pd.DataFrame:
  """建立或載入台股上市櫃股票與產業對應表 (此處以簡易對應或內政/公開對應為例)"""
  # 實務上可從 FinMind、TWSE 產業別清單或本地 CSV 讀取完整對應表
  # 這裡以簡單的範例對應說明
  try:
    url = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
    res = requests.get(url, timeout=5)
    data = res.json()
    mapping = []
    for item in data:
      mapping.append({
          "股票代號": item.get("公司代號"),
          "股票名稱": item.get("公司簡稱"),
          "產業類別": item.get("產業別"),
      })
    return pd.DataFrame(mapping)
  except:
    # 備用假資料或回傳空表
    return pd.DataFrame(columns=["股票代號", "股票名稱", "產業類別"])


# --- 主畫面介面 ---
st.title("台股板塊與三大法人資金流向雷達")
st.markdown("追蹤每日上市個股法人動向，並聚合為各產業板塊資金流向。")

# 側邊欄設定
st.sidebar.header("參數設定")
default_date = datetime.date.today()
selected_date = st.sidebar.date_input("選擇交易日", default_date)
date_str = selected_date.strftime("%Y%m%d")

if st.sidebar.button("開始抓取與分析", type="primary"):
  with st.spinner(f"正在取得 {selected_date} 的三大法人資料..."):
    raw_df = fetch_twse_institutional_data(date_str)

    if raw_df.empty:
      st.warning(
          "該日無資料（可能為假日、尚未收盤或 API 回傳格式變動），請嘗試選擇前一個交易日。"
      )
    else:
      df = clean_twse_data(raw_df)
      industry_df = load_stock_industry_mapping()

      if not industry_df.empty:
        df = pd.merge(df, industry_df[["股票代號", "產業類別"]], on="股票代號", how="left")
        df["產業類別"] = df["產業類別"].fillna("其他")
      else:
        df["產業類別"] = "未分類"

      st.session_state["data"] = df
      st.session_state["date"] = selected_date

if "data" in st.session_state:
  df = st.session_state["data"]

  st.subheader(f"📊 板塊資金流向總覽 ({st.session_state['date']})")

  # 依產業加總三大法人買賣超
  sector_summary = (
      df.groupby("產業類別")[
          ["外資買賣超", "投信買賣超", "自營商買賣超", "三大法人買賣超合計"]
      ]
      .sum()
      .reset_index()
  )
  sector_summary = sector_summary.sort_values(
      by="三大法人買賣超合計", ascending=False
  )

  # 格式化顯示
  st.dataframe(
      sector_summary.style.format({
          "外資買賣超": "{:,.0f} 張",
          "投信買賣超": "{:,.0f} 張",
          "自營商買賣超": "{:,.0f} 張",
          "三大法人買賣超合計": "{:,.0f} 張",
      }),
      use_container_width=True,
  )

  st.markdown("---")
  st.subheader("🔍 個股資金流向明細")

  # 篩選功能
  col1, col2 = st.columns(2)
  with col1:
    selected_sector = st.selectbox(
        "選擇產業板塊", ["全部"] + list(sector_summary["產業類別"].unique())
    )
  with col2:
    search_keyword = st.text_input("搜尋股票代號或名稱", "")

  filtered_df = df.copy()
  if selected_sector != "全部":
    filtered_df = filtered_df[filtered_df["產業類別"] == selected_sector]
  if search_keyword:
    filtered_df = filtered_df[
        filtered_df["股票代號"].str.contains(search_keyword)
        | filtered_df["股票名稱"].str.contains(search_keyword)
    ]

  st.dataframe(
      filtered_df.style.format({
          "外資買賣超": "{:,.0f}",
          "投信買賣超": "{:,.0f}",
          "自營商買賣超": "{:,.0f}",
          "三大法人買賣超合計": "{:,.0f}",
      }),
      use_container_width=True,
  )
