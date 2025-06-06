import os
import sys
import streamlit as st
import subprocess
import uuid
import json
import logging
import tempfile
import zipfile
import io
import shutil
from datetime import datetime
import torch
import whisper

from utils import process_audio, create_zip_file

# 確保臨時目錄存在
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'whisper_subtitle_tool')
os.makedirs(TEMP_DIR, exist_ok=True)

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(TEMP_DIR, 'app.log'))
    ]
)
logger = logging.getLogger(__name__)

# 初始化全局變量
if 'model' not in st.session_state:
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cpu":
            logger.info("使用 CPU 進行推論")
        st.session_state.model = whisper.load_model("base").to(device)
        logger.info("模型載入成功")
    except Exception as e:
        logger.error(f"模型載入失敗：{str(e)}")
        st.error(f"模型載入失敗：{str(e)}")
        st.session_state.model = None

# 設定頁面
st.set_page_config(
    page_title="字幕提取器",
    page_icon="🎬",
    layout="centered"
)

# 自定義 CSS
st.markdown("""
<style>
    /* 基礎顏色變量 */
    :root {
        --primary-color: #4A90E2;
        --background-color: #1E1E1E;
        --text-color: #FFFFFF;
        --upload-bg: rgba(74, 144, 226, 0.1);
        --upload-border: #4A90E2;
    }

    .stApp {
        background-color: var(--background-color);
    }

    .main {
        color: var(--text-color);
    }

    /* 標題樣式 */
    h1 {
        color: var(--text-color) !important;
        text-align: center;
        padding: 20px 0;
    }

    /* 上傳區域樣式 */
    .stFileUploader {
        background-color: rgba(52, 73, 94, 0.7) !important;
        border: 2px dashed var(--upload-border) !important;
        border-radius: 10px !important;
        padding: 20px !important;
        margin: 20px 0 !important;
    }

    /* 上傳區域內的所有文字 */
    .stFileUploader > div,
    .stFileUploader p,
    .stFileUploader span,
    .stFileUploader small,
    .stFileUploader label,
    .stFileUploader [data-testid="stFileUploadDropzone"] > div,
    .stFileUploader [data-testid="stFileUploadDropzone"] p,
    .stFileUploader [data-testid="stFileUploadDropzone"] span {
        color:rgb(30, 200, 200) !important;
        font-weight: 500 !important;
        
    }

    /* 上傳區域的拖放區域 */
    .stFileUploader [data-testid="stFileUploadDropzone"] {
        background-color: rgba(52, 73, 94, 0.9) !important;
        color: #FFFFFF !important;
        padding: 20px !important;
        border-radius: 5px !important;
        border: 2px dashed rgba(74, 144, 226, 0.5) !important;
    }

    /* 上傳按鈕樣式 */
    .stFileUploader button {
        background-color: #4A90E2 !important;
        color: white !important;
        border: none !important;
        padding: 8px 16px !important;
        border-radius: 4px !important;
        cursor: pointer !important;
        transition: all 0.3s ease !important;
        font-weight: 500 !important;
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2) !important;
    }

    .stFileUploader button:hover {
        background-color: #357ABD !important;
        transform: translateY(-2px) !important;
    }

    /* 上傳文件名稱樣式 */
    .stFileUploader [data-testid="stMarkdownContainer"] p {
        color: #FFFFFF !important;
        font-weight: 500 !important;
        background-color: rgba(74, 144, 226, 0.2) !important;
        padding: 8px 12px !important;
        border-radius: 4px !important;
        margin: 8px 0 !important;
    }

    /* Browse files 按鈕樣式 */
    .stFileUploader [data-testid="stFileUploadDropzone"] button {
        background-color: #4A90E2 !important;
        color: white !important;
        border: none !important;
        padding: 8px 20px !important;
        font-size: 1em !important;
        font-weight: 500 !important;
        border-radius: 4px !important;
        cursor: pointer !important;
        transition: all 0.3s ease !important;
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2) !important;
        margin: 10px 0 !important;
    }

    .stFileUploader [data-testid="stFileUploadDropzone"] button:hover {
        background-color: #357ABD !important;
        transform: translateY(-2px) !important;
    }

    /* 標題文字樣式 */
    .section-title {
        color: var(--text-color) !important;
        font-size: 1.2em;
        margin: 20px 0 10px 0;
        font-weight: 500;
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.2);
    }

    /* 上傳說明文字樣式 */
    .upload-text {
        color: var(--text-color) !important;
        background-color: rgba(74, 144, 226, 0.1);
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
    }

    /* 按鈕樣式統一 */
    .stButton > button,
    .stDownloadButton > button {
        width: 100% !important;
        height: 46px !important;
        margin: 10px 0 !important;
        background-color: rgba(36, 36, 68, 0.6) !important;
        color: rgba(255, 255, 255, 0.3) !important;
        border: 1px solid #4A90E2 !important;
        border-radius: 5px !important;
        font-size: 16px !important;
        font-weight: 500 !important;
        cursor: not-allowed !important;
        transition: all 0.3s ease !important;
    }

    .stButton > button:disabled,
    .stDownloadButton > button:disabled {
        background-color: rgba(36, 36, 68, 0.6) !important;
        color: rgba(255, 255, 255, 0.3) !important;
        border-color: rgba(74, 144, 226, 0.3) !important;
        cursor: not-allowed !important;
    }

    .stButton > button:not(:disabled),
    .stDownloadButton > button:not(:disabled) {
        background-color: #4A90E2 !important;
        color: white !important;
        border-color: #4A90E2 !important;
        cursor: pointer !important;
    }

    .stButton > button:not(:disabled):hover,
    .stDownloadButton > button:not(:disabled):hover {
        background-color: #357ABD !important;
        border-color: #357ABD !important;
        transform: translateY(-2px) !important;
    }

    /* 狀態訊息樣式 */
    .status-message {
        margin: 10px 0;
        padding: 15px;
        border-radius: 5px;
        text-align: center;
        font-weight: 500;
        font-size: 1.1em;
        letter-spacing: 0.5px;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
        filter: brightness(1.5);
    }

    /* Checkbox 樣式 */
    .stCheckbox {
        color: var(--text-color) !important;
    }

    .stCheckbox label {
        color: var(--text-color) !important;
    }

    /* 標題文字樣式 */
    .section-title {
        color: var(--text-color) !important;
        font-size: 1.2em;
        margin: 20px 0 10px 0;
        display: block !important;
        text-align: left !important;
        line-height: 1.4 !important;
        padding: 2px 0 !important;
    }

    /* 按鈕容器樣式 */
    div.element-container:has(> div.stButton), 
    div.element-container:has(> div.stDownloadButton) {
        margin: 0 !important;
        padding: 0 !important;
        width: 100% !important;
    }

    div.row-widget.stButton,
    div.row-widget.stDownloadButton {
        margin: 0 !important;
        padding: 0 !important;
    }

    /* 按鈕行容器 */
    div.css-1kyxreq {
        display: flex !important;
        gap: 20px !important;
        margin: 20px 0 !important;
        align-items: stretch !important;
    }

    div.css-1kyxreq > div {
        flex: 1 !important;
        margin: 0 !important;
    }

    /* 格式選擇區域樣式 */
    div.row-widget.stCheckbox {
        background-color: rgba(36, 36, 68, 0.4) !important;
        border: 1px solid #4A90E2 !important;
        border-radius: 5px !important;
        padding: 10px !important;
        margin: 5px 0 !important;
        height: 70px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: relative !important;
    }

    div.row-widget.stCheckbox:hover {
        background-color: rgba(74, 144, 226, 0.2) !important;
        border-color: #4A90E2 !important;
    }

    /* Checkbox 容器 */
    div.row-widget.stCheckbox > div {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        width: 100% !important;
        height: 100% !important;
        position: relative !important;
        padding-left: 35px !important;
    }

    /* Checkbox 本身 */
    div.row-widget.stCheckbox input[type="checkbox"] {
        appearance: none !important;
        -webkit-appearance: none !important;
        width: 18px !important;
        height: 18px !important;
        border: 2px solid white !important;
        border-radius: 3px !important;
        margin: 0 !important;
        cursor: pointer !important;
        position: absolute !important;
        left: 10px !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        background-color: transparent !important;
        z-index: 1 !important;
    }

    div.row-widget.stCheckbox input[type="checkbox"]:checked {
        background-color: #4A90E2 !important;
        border-color: #4A90E2 !important;
    }

    div.row-widget.stCheckbox input[type="checkbox"]:checked::after {
        content: '✓' !important;
        position: absolute !important;
        color: white !important;
        font-size: 14px !important;
        font-weight: bold !important;
        left: 2px !important;
        top: -2px !important;
    }

    /* 標籤文字 */
    div.row-widget.stCheckbox label {
        color: white !important;
        font-size: 0.9em !important;
        font-weight: 500 !important;
        text-align: center !important;
        width: 100% !important;
        cursor: pointer !important;
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5) !important;
        line-height: 1.2 !important;
        display: flex !important;
        flex-direction: column !important;
        align-items: center !important;
        justify-content: center !important;
        min-height: 40px !important;
        gap: 4px !important;
    }

    /* 格式選項文字樣式 */
    .css-1djdyxw.ek41t0m0 {
        color: white !important;
        font-size: 0.95em !important;
        margin: 2px 0 !important;
        display: block !important;
        text-align: center !important;
        line-height: 1.4 !important;
        padding: 2px 0 !important;
    }

    .css-1djdyxw.ek41t0m0:last-child {
        font-size: 0.85em !important;
        opacity: 0.9 !important;
        margin-top: 4px !important;
    }

    /* 格式選擇容器 */
    div.stColumns {
        gap: 10px !important;
    }

    div.stColumns > div {
        flex: 1 1 0 !important;
        width: calc(20% - 8px) !important;
        min-width: 0 !important;
    }

    /* 確保所有文字都是白色 */
    div.row-widget.stCheckbox * {
        color: white !important;
    }

    /* 提示訊息容器 */
    div.stAlert {
        background-color: rgba(36, 36, 68, 0.4) !important;
        border: 1px solid #4A90E2 !important;
        border-radius: 5px !important;
        padding: 16px !important;
        margin: 20px 0 !important;
        text-align: center !important;
        min-height: 60px !important;
        height: 60px !important;
        width: 100% !important;
        max-width: 800px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        position: fixed !important;
        bottom: 20px !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        z-index: 1000 !important;
    }

    /* 提示訊息文字樣式 */
    div.stAlert > div {
        color: white !important;
        font-size: 1.1em !important;
        font-weight: 500 !important;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.2) !important;
        opacity: 1 !important;
        filter: brightness(2) !important;
    }

    /* 成功訊息樣式 */
    div.stAlert.success {
        background-color: rgba(46, 204, 113, 0.2) !important;
        border-color: #2ecc71 !important;
    }

    div.stAlert.success div {
        color: #7bed9f !important;
        filter: brightness(2) !important;
    }

    /* 錯誤訊息樣式 */
    div.stAlert.error {
        background-color: rgba(231, 76, 60, 0.2) !important;
        border-color: #e74c3c !important;
    }

    div.stAlert.error div {
        color: #ff7675 !important;
        filter: brightness(2) !important;
    }

    /* 資訊訊息樣式 */
    div.stAlert.info {
        background-color: rgba(52, 152, 219, 0.2) !important;
        border-color: #3498db !important;
    }

    div.stAlert.info div {
        color: #5dade2 !important;
        filter: brightness(2) !important;
    }

    /* 確保按鈕容器和提示訊息容器寬度一致 */
    div.row-widget.stButton,
    div.row-widget.stDownloadButton,
    div.element-container div.stAlert {
        width: 100% !important;
        max-width: 800px !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }

    /* 為提示訊息預留空間 */
    .main .block-container {
        padding-bottom: 100px !important;
    }

    /* 狀態訊息樣式 */
    .status-info {
        background-color: rgba(52, 152, 219, 0.2);
        color: #5dade2;
        border: 1px solid rgba(52, 152, 219, 0.3);
    }

    .status-error {
        background-color: rgba(231, 76, 60, 0.2);
        color: #ff7675;
        border: 1px solid rgba(231, 76, 60, 0.3);
    }

    .status-success {
        background-color: rgba(46, 204, 113, 0.2);
        color: #7bed9f;
        border: 1px solid rgba(46, 204, 113, 0.3);
    }

    .status-processing {
        background-color: rgba(241, 196, 15, 0.2);
        color: #ffeaa7;
        border: 1px solid rgba(241, 196, 15, 0.3);
        animation: pulse 2s infinite;
    }

    @keyframes pulse {
        0% { opacity: 0.6; }
        50% { opacity: 1; }
        100% { opacity: 0.6; }
    }

    /* 隱藏 Streamlit 的 spinner */
    .stSpinner {
        display: none !important;
    }

    /* 隱藏 Streamlit 預設的漢堡選單和頁尾 */
    #MainMenu, footer {
        visibility: hidden;
    }
</style>
""", unsafe_allow_html=True)

# 初始化 session state
if 'processed' not in st.session_state:
    st.session_state.processed = False
if 'outputs' not in st.session_state:
    st.session_state.outputs = None
if 'filename' not in st.session_state:
    st.session_state.filename = None
if 'status_message' not in st.session_state:
    st.session_state.status_message = "請選擇要處理的影音檔案"
if 'status_type' not in st.session_state:
    st.session_state.status_type = "info"
if 'processing' not in st.session_state:
    st.session_state.processing = False
if 'downloaded' not in st.session_state:
    st.session_state.downloaded = False

def main():
    st.title("智能字幕提取系統")
    
    st.markdown('<div class="section-title">選擇影音檔：</div>', unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader(
            "",
            type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'],
            
            on_change=lambda: setattr(st.session_state, 'downloaded', False)
        )
    st.markdown('<div class="section-title">選擇輸出格式：</div>', unsafe_allow_html=True)
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1: txt_format = st.checkbox('純文字  \n(.txt)', value=True)
    with col2: srt_format = st.checkbox('字幕檔  \n(.srt)', value=True)
    with col3: vtt_format = st.checkbox('網頁字幕\n(.vtt)', value=True)
    with col4: tsv_format = st.checkbox('Excel格式\n(.tsv)', value=True)
    with col5: json_format = st.checkbox('JSON格式\n(.json)', value=True)

    formats = []
    if txt_format: formats.append('txt')
    if srt_format: formats.append('srt')
    if vtt_format: formats.append('vtt')
    if tsv_format: formats.append('tsv')
    if json_format: formats.append('json')
    
  
    col1, col2 = st.columns(2)

    status_area = st.container()
    status_area.markdown(
        f'<div class="status-message status-{st.session_state.status_type}">{st.session_state.status_message}</div>',
        unsafe_allow_html=True
    )

    with col1:
        if st.button('開始提取', disabled=not (uploaded_file and formats) or st.session_state.processing):
            try:
                st.session_state.processing = True
                st.session_state.downloaded = False
                st.session_state.status_message = "字幕提取中..."
                st.session_state.status_type = "info"
                
                with st.spinner('正在提取字幕...'):
                    outputs = process_audio(uploaded_file, formats)
                    st.session_state.outputs = outputs
                    st.session_state.filename = os.path.splitext(uploaded_file.name)[0]
                    st.session_state.processed = True
                    st.session_state.status_message = "處理完成！請點擊右側按鈕下載字幕檔"
                    st.session_state.status_type = "success"
            except Exception as e:
                msg = f"處理失敗：{str(e)}"
                st.session_state.status_message = msg
                st.session_state.status_type = "error"
                st.session_state.processed = False
            finally:
                st.session_state.processing = False
               

    with col2:
        if st.session_state.get('outputs') and not st.session_state.get('downloaded', False):
            zip_file = create_zip_file(st.session_state.outputs, st.session_state.filename)
            if st.download_button(
                label='下載字幕檔',
                data=zip_file,
                file_name=f"{st.session_state.filename}_subtitles.zip",
                mime='application/zip',
                #use_container_width=True
            ):
                st.session_state.downloaded = True
                st.session_state.status_message = "下載完成！可以繼續處理新的檔案"
                st.session_state.status_type = "success"
                st.rerun()
        else:
            st.button('下載字幕檔', disabled=True)

   
  

    # 狀態提示根據狀況自動補上
    if not uploaded_file:
        st.session_state.status_message = "請選擇要處理的影音檔案"
        st.session_state.status_type = "info"
    elif not formats:
        st.session_state.status_message = "請至少選擇一種輸出格式"
        st.session_state.status_type = "warning"

    

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        st.error(f"應用程式啟動失敗：{str(e)}")
        logger.error(f"應用程式啟動失敗：{str(e)}")
