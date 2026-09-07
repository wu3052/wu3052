import datetime
import pandas as pd
import requests


def fetch_twse_institutional_data(date_str: str) -> pd.DataFrame:
  """抓取臺灣證券交易所 (TWSE) 三大法人買賣超資料 (上市)

  date_str 格式: YYYY-MM-DD (例如 '2026-06-07')
  """
  # 轉換為民國年月日格式 (例如 2026-06-07 -> 1150607)
  dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
  roc_year = dt.year - 1911
  roc_date = f"{roc_year}{dt.strftime('%m%d')}"

  # TWSE 官方 OpenAPI / 網頁 JSON 綜合報表端點
  # 這裡使用 TWSE 每日收盤行情兼三大法人資料，或專用 OpenAPI
  url = f"https://www.twse.com.tw/rwd/zh/fund/T86?response=json&date={roc_date}"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }

  try:
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()

    if "data" in data and data["data"]:
      # T86 欄位通常為：證券代號, 證券名稱, 外陸資買賣超股數, 投信買賣超股數, 自營商買賣超股數(自行買賣), 自營商買賣超股數(避險), 三大法人買賣超股數合計...
      columns = data["stat"] if "stat" in data else []
      df = pd.DataFrame(data["data"], columns=data["fields"])
      df["市場"] = "上市"
      return df
    else:
      print(f"TWSE {date_str} 無資料或該日為休市日。")
      return pd.DataFrame()
  except Exception as e:
    print(f"抓取 TWSE 資料失敗: {e}")
    return pd.DataFrame()


def fetch_tpex_institutional_data(date_str: str) -> pd.DataFrame:
  """抓取證券櫃檯買賣中心 (TPEx) 三大法人買賣超資料 (上櫃)

  date_str 格式: YYYY-MM-DD (例如 '2026-06-07')
  """
  dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
  roc_year = dt.year - 1911
  roc_date = f"{roc_year}/{dt.strftime('%m')}/{dt.strftime('%d')}"

  # TPEx 官方三大法人買賣超日報 API
  url = f"https://www.tpex.org.tw/web/stock/3insti/daily_trade/3insti_ch1_result.php?l=zh-tw&d={roc_date}"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      )
  }

  try:
    response = requests.get(url, headers=headers, timeout=10)
    data = response.json()

    if "aaData" in data and data["aaData"]:
      df = pd.DataFrame(data["aaData"])
      df["市場"] = "上櫃"
      return df
    else:
      print(f"TPEx {date_str} 無資料或該日為休市日。")
      return pd.DataFrame()
  except Exception as e:
    print(f"抓取 TPEx 資料失敗: {e}")
    return pd.DataFrame()


# 範例測試
if __name__ == "__main__":
  target_date = "2026-06-05"  # 請替換為目標交易日
  print(f"正在抓取 {target_date} 上市法人資料...")
  twse_df = fetch_twse_institutional_data(target_date)
  if not twse_df.empty:
    print("上市資料抓取成功，前 5 筆：")
    print(twse_df.head())

  print(f"\n正在抓取 {target_date} 上櫃法人資料...")
  tpex_df = fetch_tpex_institutional_data(target_date)
  if not tpex_df.empty:
    print("上櫃資料抓取成功，前 5 筆：")
    print(tpex_df.head())
