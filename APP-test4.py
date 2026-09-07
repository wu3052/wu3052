from datetime import datetime, timedelta
import pandas as pd
import requests
import streamlit as st

# 頁面基本設定
st.set_page_config(
    page_title="台股板塊與資金流向戰情室 (官方API)", page_icon="🌊", layout="wide"
)


def get_twse_institutional_data(date_str):
  """抓取臺灣證券交易所 (TWSE) 上市個股三大法人買賣超日報 (T86)"""
  # 日期格式化為中華民國年月日或YYYYMMDD，TWSE T86 支援 YYYYMMDD
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={date_str}&selectType=ALLBUT0999"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    if data.get("stat") == "OK":
      fields = data.get("fields", [])
      rows = data.get("data", [])
      df = pd.DataFrame(rows, columns=fields)
      # 清洗欄位
      # 欄位通常包含: 證券代號, 證券名稱, 外陸資買賣超張數(不含外資自營商), 外資自營商買賣超張數, 投信買賣超張數, 自營商買賣超張數(自行買賣), 自營商買賣超張數(避險), 三大法人買賣超張數等
      return df
  except Exception as e:
    print(f"TWSE API Error: {e}")
  return pd.DataFrame()


def get_tpex_institutional_data(date_str):
  """抓取證券櫃檯買賣中心 (TPEx) 上櫃個股三大法人買賣明細"""
  # 將 YYYY-MM-DD 轉為民國年份格式 YYYYMMDD (例如 20260907 -> 1150907)
  dt = datetime.strptime(date_str, "%Y-%m-%d")
  roc_year = dt.year - 1911
  roc_date_str = f"{roc_year}{dt.strftime('%m%d')}"

  url = f"https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading?d={roc_date_str}"
  try:
    res = requests.get(url, timeout=10)
    data = res.json()
    if isinstance(data, list) and len(data) > 0:
      return pd.DataFrame(data)
  except Exception as e:
    print(f"TPEx API Error: {e}")
  return pd.DataFrame()


@st.cache_data(ttl=86400)
def get_stock_industry_map():
  """取得上市櫃公司與產業對照 (透過證交所與櫃買中心公開資料)"""
  mapping = {}
  # 簡易透過 FinMind 或簡易對照，若追求完全官方可由證交所基本檔帶入
  # 這裡使用公開穩定股票清單 API
  try:
    url = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
    res = requests.get(url, timeout=10).json()
    if res.get("status") == 200:
      df = pd.DataFrame(res.get("data"))
      for _, row in df.iterrows():
        mapping[str(row["stock_id"])] = {
            "name": row.get("stock_name", ""),
            "industry": row.get("industry_category", "其他"),
        }
  except:
    pass
  return mapping


st.title("🌊 台股板塊與資金流向戰情室")
st.markdown(
    "直接串接 **臺灣證券交易所 (TWSE)** 與 **證券櫃檯買賣中心 (TPEx)** 官方資料源。"
)

# 側邊欄控制項
st.sidebar.header("參數設定")
default_date = datetime.today() - timedelta(days=1)
if default_date.weekday() == 5:
  default_date -= timedelta(days=1)
elif default_date.weekday() == 6:
  default_date -= timedelta(days=2)

query_date = st.sidebar.date_input("選擇交易日", value=default_date)
date_str = query_date.strftime("%Y-%m-%d")
date_str_no_hyphen = query_date.strftime("%Y%m%d")

# 資料載入
with st.spinner(
    f"正在向 TWSE 及 TPEx 官方抓取 {date_str} 三大法人資金流向..."
):
  df_twse = get_twse_institutional_data(date_str_no_hyphen)
  df_tpex = get_tpex_institutional_data(date_str)
  stock_map = get_stock_industry_map()

if df_twse.empty and df_tpex.empty:
  st.warning(
      f"找不到 {date_str} 的官方法人資料（可能為假日、非交易日或當日收盤結算中尚未發布），請挑選其他交易日。"
  )
else:
  processed_rows = []

  # 1. 處理上市資料 (TWSE T86)
  if not df_twse.empty:
    # 欄位名稱通常對應: ['證券代號', '證券名稱', '外陸資買賣超張數(不含外資自營商)', '投信買賣超張數', '自營商買賣超張數(自行買賣)', ...]
    # 欄位可能含有 commas 需要移除
    for _, row in df_twse.iterrows():
      try:
        s_id = str(row.iloc[0]).strip()
        s_name = str(row.iloc[1]).strip()

        def clean_val(val):
          if pd.isna(val):
            return 0.0
          return float(str(val).replace(",", "").strip())

        # 抓取常見欄位並計算
        # 依 T86 實際回傳欄位索引安全取值
        foreign = clean_val(row.iloc[4])  # 外資總買賣超
        trust = clean_val(row.iloc[10])  # 投信買賣超
        dealer = clean_val(row.iloc[15])  # 自營商總買賣超

        industry = (
            stock_map.get(s_id, {}).get("industry", "上市其他")
            if s_id in stock_map
            else "上市其他"
        )

        processed_rows.append({
            "股票代號": s_id,
            "股票名稱": s_name,
            "市場": "上市",
            "產業": industry,
            "外資": foreign,
            "投信": trust,
            "自營商": dealer,
            "合計": foreign + trust + dealer,
        })
      except Exception:
        continue

  # 2. 處理上櫃資料 (TPEx OpenAPI)
  if not df_tpex.empty:
    for _, row in df_tpex.iterrows():
      try:
        s_id = str(row.get("SecuritiesCompanyCode", "")).strip()
        s_name = str(row.get(expression="SecuritiesName", default="")).strip()
        if not s_name:
          s_name = str(row.get("CompanyName", s_id)).strip()

        def clean_tpex_val(val):
          if pd.isna(val):
            return 0.0
          return float(str(val).replace(",", "").strip()) / 1000.0  # 股轉張

        foreign = clean_tpex_val(
            row.get("ForeignNetBuySell", row.get("ForeignTotal", 0))
        )
        trust = clean_tpex_val(
            row.get(
                "InvestmentTrustNetBuySell", row.get("TrustTotal", 0)
            )
        )
        dealer = clean_tpex_val(
            row.get("DealerNetBuySell", row.get("DealerTotal", 0))
        )

        industry = (
            stock_map.get(s_id, {}).get("industry", "上櫃其他")
            if s_id in stock_map
            else "上櫃其他"
        )

        processed_rows.append({
            "股票代號": s_id,
            "股票名稱": s_name,
            "市場": "上櫃",
            "產業": industry,
            "外資": foreign,
            "投信": trust,
            "自營商": dealer,
            "合計": foreign + trust + dealer,
        })
      except Exception:
        continue

  df_final = pd.DataFrame(processed_rows)

  if df_final.empty:
    st.error("解析官方 API 資料格式時發生錯誤，請稍後再試。")
  else:
    # 版面一：板塊資金流向總覽
    st.header("📊 板塊資金流向總覽（單位：張）")
    sector_agg = (
        df_final.groupby("產業")[["外資", "投信", "自營商", "合計"]]
        .sum()
        .sort_values(by="合計", ascending=False)
    )

    st.dataframe(
        sector_agg.style.format("{:,.2f}").background_gradient(
            cmap="coolwarm", subset=["合計"]
        ),
        use_container_width=True,
    )

    # 版面二：個股資金流向排行榜
    st.header("🔍 個股資金流向排行榜")
    c1, c2, c3 = st.columns(3)
    with c1:
      market_filter = st.selectbox("市場選擇", ["全部", "上市", "上櫃"])
    with c2:
      investor_col = st.selectbox(
          "排序法人", ["合計", "外資", "投信", "自營商"]
      )
    with c3:
      sort_dir = st.radio(
          "排序方向", ["買超最多 (多->少)", "賣超最多 (少->多)"], horizontal=True
      )

    df_view = df_final.copy()
    if market_filter != "全部":
      df_view = df_view[df_view["市場"] == market_filter]

    is_asc = True if "賣超" in sort_dir else False
    df_view = df_view.sort_values(by=investor_col, ascending=is_asc)

    st.dataframe(
        df_view[
            ["股票代號", "股票名稱", "市場", "產業", "外資", "投信", "自營商", "合計"]
        ].style.format({
            "外資": "{:,.2f}",
            "投信": "{:,.2f}",
            "自營商": "{:,.2f}",
            "合計": "{:,.2f}",
        }),
        use_container_width=True,
    )
