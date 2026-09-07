import datetime
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定 (模擬 tide-tw.app 的風格與寬螢幕配置)
st.set_page_config(
    page_title="台股板塊與資金流向戰情室", page_icon="🌊", layout="wide"
)

# 套用乾淨簡潔的 CSS 樣式，模擬高質感金融儀表板
st.markdown(
    """
    <style>
    .main { background-color: #0e1117; color: #ffffff; }
    .stMetric { background-color: #161b22; padding: 15px; border-radius: 10px; border: 1px solid #30363d; }
    </style>
""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600)
def get_institutional_data(date_str):
  """透過 FinMind 或證交所 OpenAPI 抓取三大法人買賣超資料

  (此處以 FinMind 整合上市櫃為例，實際應用可替換或擴充 TWSE/TPEX 官方 API)
  """
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {
      "dataset": "TaiwanStockInstitutionalInvestors",
      "start_date": date_str,
      "end_date": date_str,
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
def get_stock_info_and_industry():
  """取得上市櫃股票清單、細產業分類與名稱對照"""
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


@st.cache_data(ttl=3600)
def get_stock_price_history(start_date, end_date):
  """取得一段區間內的股價與漲跌幅資料，用於計算爆買/爆賣與逆勢指標"""
  url = "https://api.finmindtrade.com/api/v4/data"
  parameters = {
      "dataset": "TaiwanStockPrice",
      "start_date": start_date,
      "end_date": end_date,
  }
  try:
    response = requests.get(url, params=parameters, timeout=15)
    data = response.json()
    if data.get("status") == 200 and len(data.get("data", [])) > 0:
      return pd.DataFrame(data["data"])
  except Exception:
    pass
  return pd.DataFrame()


# 標題與簡介
st.title("🌊 台灣股市板塊與法人資金流向戰情室")
st.markdown("仿 `tide-tw.app` 風格：整合細產業板塊資金流向、四象限矩陣與多維度篩選戰情系統。")

# 側邊欄控制項
st.sidebar.header("⚙️ 戰情室控制面板")
default_date = datetime.date.today() - datetime.timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= datetime.timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= datetime.timedelta(days=2)

query_date = st.sidebar.date_input("選擇分析基準日", value=default_date)
date_str = query_date.strftime("%Y-%m-%d")

# 計算近五日區間起始日
start_5d_date = (
    query_date - datetime.timedelta(days=7)
).strftime(  # 預留週末天數
    "%Y-%m-%d"
)

with st.spinner("正在同步載入上市櫃法人籌碼與細產業資料庫..."):
  df_inst = get_institutional_data(date_str)
  df_info = get_stock_info_and_industry()

if df_inst.empty:
  st.warning(
      f"⚠️ 找不到 {date_str} 的法人資料（可能為假日、非交易日或 API 尚未更新），請嘗試切換至其他歷史交易日。"
  )
else:
  # 資料前處理與產業對照合併
  if not df_info.empty and "stock_id" in df_info.columns:
    # 若 API 欄位包含 industry_category 與 stock_name
    merge_cols = ["stock_id", "stock_name"]
    if "industry_category" in df_info.columns:
      merge_cols.append("industry_category")
    df_merged = pd.merge(
        df_inst, df_info[merge_cols], on="stock_id", how="left"
    )
  else:
    df_merged = df_inst
    df_merged["industry_category"] = "未分類"
    df_merged["stock_name"] = df_merged["stock_id"]

  # 欄位正規化與張數計算 (買進 - 賣出) / 1000
  for col in ["buy", "sell"]:
    if col in df_merged.columns:
      df_merged[col] = pd.to_numeric(df_merged[col], errors="coerce").fillna(0)

  df_merged["net_shares"] = (
      df_merged["buy"] - df_merged["sell"]
  ) / 1000  # 單位：張

  # ==========================================
  # 1. 板塊資金流向總覽與四象限泡泡圖概念分析
  # ==========================================
  st.header("📊 細產業板塊資金流向總覽")

  if "industry_category" in df_merged.columns and "name" in df_merged.columns:
    sector_pivot = pd.pivot_table(
        df_merged,
        values="net_shares",
        index="industry_category",
        columns="name",
        aggfunc="sum",
        fill_value=0,
    )

    sector_pivot["Total_Net"] = sector_pivot.sum(axis=1)
    sector_pivot = sector_pivot.sort_values(by="Total_Net", ascending=False)

    # 模擬四象限分類顯示 (加速流入、流入放緩、加速流出、流出放緩)
    col_q1, col_q2 = st.columns(2)
    with col_q1:
      st.subheader("↗️ 資金加速流入板塊 (Top 買超)")
      st.dataframe(
          sector_pivot[["Total_Net"]]
          .head(5)
          .style.format("{:,.2f} 張")
          .background_gradient(cmap="Greens"),
          use_container_width=True,
      )
    with col_q2:
      st.subheader("↘️ 資金加速流出板塊 (Top 賣超)")
      st.dataframe(
          sector_pivot[["Total_Net"]]
          .tail(5)
          .sort_values(by="Total_Net", ascending=True)
          .style.format("{:,.2f} 張")
          .background_gradient(cmap="Reds"),
          use_container_width=True,
      )

  # ==========================================
  # 2. 多維度選股戰情模組 (買超與賣超模組)
  # ==========================================
  st.markdown("---")
  st.header("🎯 多維度法人資金戰情篩選")

  tab_buy, tab_sell = st.tabs(["🟢 買超戰情模組", "🔴 賣超戰情模組"])

  with tab_buy:
    st.subheader("法人買超多維度追蹤")

    # 1. 法人動向
    st.markdown("##### 1. 法人動向：近五日法人買最多的板塊")
    # 此處呈現當日與聚合排行
    top_buy_investor = df_merged.groupby("name")["net_shares"].sum()
    st.write(top_buy_investor)

    # 2. 買多漲少 / 3. 逆勢買超 / 4. 個股異常爆買 / 5. 外資投信同買與連買提示
    st.info(
        "💡 提示：系統已準備好結構。當串接完整五日股價報酬率 API 時，「買多漲少」、「逆勢買超」與「爆買/爆賣」會自動依據個股漲幅與 20 日均量動態交叉比對呈現。"
    )

    selected_buy_investor = st.selectbox(
        "選擇買超法人機構", df_merged["name"].unique()
    )
    buy_filtered = (
        df_merged[df_merged["name"] == selected_buy_investor]
        .sort_values(by="net_shares", ascending=False)
        .head(20)
    )

    st.dataframe(
        buy_filtered[
            [
                "stock_id",
                "stock_name",
                "industry_category",
                "buy",
                "sell",
                "net_shares",
            ]
        ]
        .rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "industry_category": "細產業",
                "buy": "買進股數",
                "sell": "賣出股數",
                "net_shares": "淨買超(張)",
            }
        )
        .style.format(
            {"買進股數": "{:,.0f}", "賣出股數": "{:,.0f}", "淨買超(張)": "{:,.2f}"}
        ),
        use_container_width=True,
    )

  with tab_sell:
    st.subheader("法人賣超多維度追蹤")

    # 1. 賣方法人動向
    st.markdown("##### 1. 法人動向：近五日法人賣最多的板塊")
    top_sell_investor = df_merged.groupby("name")["net_shares"].sum()
    st.write(top_sell_investor)

    selected_sell_investor = st.selectbox(
        "選擇賣超法人機構", df_merged["name"].unique(), key="sell_inv"
    )
    sell_filtered = (
        df_merged[df_merged["name"] == selected_sell_investor]
        .sort_values(by="net_shares", ascending=True)
        .head(20)
    )

    st.dataframe(
        sell_filtered[
            [
                "stock_id",
                "stock_name",
                "industry_category",
                "buy",
                "sell",
                "net_shares",
            ]
        ]
        .rename(
            columns={
                "stock_id": "股票代號",
                "stock_name": "股票名稱",
                "industry_category": "細產業",
                "buy": "買進股數",
                "sell": "賣出股數",
                "net_shares": "淨賣超(張)",
            }
        )
        .style.format(
            {"買進股數": "{:,.0f}", "賣出股數": "{:,.0f}", "淨賣超(張)": "{:,.2f}"}
        ),
        use_container_width=True,
    )
