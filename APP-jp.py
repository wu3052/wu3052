import streamlit as st
import requests
from bs4 import BeautifulSoup

st.set_page_config(
    page_title="日語學習互動 App",
    page_icon="🇯🇵",
    layout="wide"
)

# 側邊欄導覽
st.sidebar.title("🇯🇵 日語學習小幫手")
page = st.sidebar.radio("選擇功能", ["影片與學習講義", "單字/筆記本"])

# 目標網址常數
BILIBILI_URL = "https://www.player.bilibili.com/player.html?bvid=BV1Qx411D7oA&page=1"
TINGROOM_URL = "https://jp.tingroom.com/rumen/zary/list_17.html"

@st.cache_data
def fetch_tingroom_content(url):
    """抓取 tingroom 講義內容"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(url, headers=headers)
        response.encoding = 'gbk' # tingroom 常見編碼
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            content_div = soup.find('div', class_='article_content') or soup.find('div', class_='text')
            
            if content_div:
                return content_div.get_text(separator="\n")
            else:
                return "成功連線，但未找到指定排版區塊。建議直接點擊下方連結閱讀原始講義。"
        else:
            return f"無法讀取網頁，狀態碼：{response.status_code}"
    except Exception as e:
        return f"解析發生錯誤：{str(e)}"

if page == "影片與學習講義":
    st.title("📺 日語教學影片與對應講義")
    st.markdown("邊看影片邊對照講義，輕鬆學習日語發音與基礎對話！")
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("🎬 教學影片 (Bilibili)")
        bilibili_iframe = f"""
        <iframe src="{BILIBILI_URL}" scrolling="no" border="0" frameborder="no" framespacing="0" allowfullscreen="true" width="100%" height="400px"> </iframe>
        """
        st.components.v1.html(bilibili_iframe, height=400)
        st.markdown("[🔗 點此在 Bilibili 原網站觀看](https://www.bilibili.com/video/BV1Qx411D7oA/)")

    with col2:
        st.subheader("📖 學習講義")
        with st.spinner("正在載入講義內容..."):
            講義內容 = fetch_tingroom_content(TINGROOM_URL)
        
        st.text_area("講義內容：", value=講義內容, height=400)
        st.markdown(f"[🔗 點此查看原始 tingroom 講義](https://jp.tingroom.com/rumen/zary/list_17.html)")

elif page == "單字/筆記本":
    st.title("📝 學習筆記與生字本")
    st.markdown("在這裡記錄您在影片中學到的日語單字或文法：")
    
    user_note = st.text_area("輸入您的筆記：", "例：\nこんにちは - 你好\nありがとう - 謝謝")
    if st.button("保存筆記"):
        st.success("筆記已暫存！")
    
    if user_note:
        st.markdown("### 您的筆記預覽：")
        st.info(user_note)
