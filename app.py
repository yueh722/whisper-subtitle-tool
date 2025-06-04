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
import asyncio

# 設定日誌
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化全局變量
if 'model' not in st.session_state:
    try:
        st.session_state.model = whisper.load_model("base")
    except Exception as e:
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
        background-color: var(--upload-bg);
        border: 2px dashed var(--upload-border);
        border-radius: 10px;
        padding: 20px;
        margin: 20px 0;
    }

    /* 確保上傳區域內的所有文字都是可見的 */
    .stFileUploader > div {
        color: var(--text-color) !important;
        background-color: rgba(74, 144, 226, 0.1) !important;
    }

    .stFileUploader p {
        color: var(--text-color) !important;
    }

    .stFileUploader span {
        color: var(--text-color) !important;
    }

    .stFileUploader small {
        color: var(--text-color) !important;
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

    /* 按鈕樣式 */
    .stButton > button {
        width: 100% !important;
        height: 46px !important;
        margin: 10px 0 !important;
        background-color: var(--primary-color) !important;
        color: white !important;
        border: none !important;
        border-radius: 5px !important;
        font-size: 16px !important;
        font-weight: 500 !important;
        cursor: pointer !important;
        transition: all 0.3s ease !important;
    }

    .stButton > button:disabled {
        background-color: rgba(74, 144, 226, 0.3) !important;
        cursor: not-allowed !important;
    }

    .stButton > button:not(:disabled):hover {
        background-color: #357ABD !important;
        transform: translateY(-2px) !important;
    }

    /* 狀態訊息樣式 */
    .status-message {
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
        text-align: center;
        background-color: rgba(74, 144, 226, 0.1);
        border: 1px solid var(--primary-color);
        color: var(--text-color);
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

    /* 上傳按鈕樣式 */
    .stFileUploader button {
        background-color: #4A90E2 !important;
        color: white !important;
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
        width: 100% !important;
        max-width: 800px !important;
    }

    /* 訊息區域樣式 */
    #status-area {
        margin: 20px 0 !important;
        padding: 20px !important;
        border-radius: 10px !important;
        background-color: rgba(36, 36, 68, 0.4) !important;
        min-height: 60px !important;
        width: 100% !important;
        max-width: 800px !important;
        border: 1px solid #4A90E2 !important;
        box-sizing: border-box !important;
    }

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

    /* 確保所有容器寬度一致 */
    .main .block-container {
        max-width: 800px !important;
        padding: 0 !important;
        margin: 0 auto !important;
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

def format_timestamp(seconds, always_include_hours=False):
    """將秒數轉換為 SRT/VTT 時間戳格式"""
    assert seconds >= 0, "非負數秒數"
    milliseconds = round(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds -= hours * 3_600_000

    minutes = milliseconds // 60_000
    milliseconds -= minutes * 60_000

    seconds = milliseconds // 1_000
    milliseconds -= seconds * 1_000

    hours_marker = f"{hours:02d}:" if always_include_hours or hours > 0 else ""
    return f"{hours_marker}{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

def clean_text(text):
    return text.strip()

def merge_short_segments(segments, min_duration=2.0):
    merged = []
    current_text = []
    current_start = None
    
    for segment in segments:
        if not current_start:
            current_start = segment['start']
            current_text.append(segment['text'].strip())
        else:
            duration = segment['end'] - current_start
            if duration < min_duration:
                current_text.append(segment['text'].strip())
            else:
                merged.append({
                    'start': current_start,
                    'end': segment['end'],
                    'text': ' '.join(current_text)
                })
                current_start = segment['start']
                current_text = [segment['text'].strip()]
    
    if current_text:
        merged.append({
            'start': current_start,
            'end': segments[-1]['end'],
            'text': ' '.join(current_text)
        })
    
    return merged

def write_srt(segments):
    segments = merge_short_segments(segments)
    output = []
    for i, segment in enumerate(segments, start=1):
        output.append(f"{i}")
        output.append(
            f"{format_timestamp(segment['start'], always_include_hours=True)} --> "
            f"{format_timestamp(segment['end'], always_include_hours=True)}"
        )
        output.append(clean_text(segment['text']))
        output.append("")
    return "\n".join(output)

def write_vtt(segments):
    segments = merge_short_segments(segments)
    output = ["WEBVTT", ""]
    for segment in segments:
        output.append(
            f"{format_timestamp(segment['start'])} --> "
            f"{format_timestamp(segment['end'])}"
        )
        output.append(clean_text(segment['text']))
        output.append("")
    return "\n".join(output)

def check_ffmpeg():
    """檢查 ffmpeg 是否可用"""
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def process_audio(audio_file, formats):
    """處理音訊檔案並生成字幕"""
    try:
        with st.spinner('正在處理音訊...'):
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
                try:
                    temp_audio.write(audio_file.getvalue())
                    temp_audio_path = temp_audio.name
                    
                    if st.session_state.model is None:
                        raise Exception("模型未正確載入")
                    
                    with torch.inference_mode():
                        result = st.session_state.model.transcribe(temp_audio_path, verbose=False)
                    
                    outputs = {}
                    processed_segments = merge_short_segments(result['segments'])
                    
                    for fmt in formats:
                        if fmt == 'txt':
                            outputs['txt'] = '\n'.join(clean_text(segment['text']) for segment in processed_segments)
                        elif fmt == 'srt':
                            outputs['srt'] = write_srt(result['segments'])
                        elif fmt == 'vtt':
                            outputs['vtt'] = write_vtt(result['segments'])
                        elif fmt == 'tsv':
                            outputs['tsv'] = '開始時間\t結束時間\t文字內容\n' + '\n'.join(
                                f"{format_timestamp(seg['start'])}\t{format_timestamp(seg['end'])}\t{clean_text(seg['text'])}"
                                for seg in processed_segments
                            )
                        elif fmt == 'json':
                            clean_result = {
                                'text': '\n'.join(clean_text(segment['text']) for segment in processed_segments),
                                'segments': [{
                                    'start': segment['start'],
                                    'end': segment['end'],
                                    'text': clean_text(segment['text'])
                                } for segment in processed_segments]
                            }
                            outputs['json'] = json.dumps(clean_result, ensure_ascii=False, indent=2)
                    
                    return outputs
                    
                except Exception as e:
                    logger.error(f"處理失敗：{str(e)}")
                    raise
                finally:
                    try:
                        os.unlink(temp_audio_path)
                    except:
                        pass
    except Exception as e:
        logger.error(f"處理失敗：{str(e)}")
        raise

def create_zip_file(outputs, filename_prefix):
    """將所有輸出打包成ZIP檔案"""
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fmt, content in outputs.items():
            output_filename = f"{filename_prefix}.{fmt}"
            zf.writestr(output_filename, content)
    memory_file.seek(0)
    return memory_file

def main():
    try:
        st.title("智能字幕提取系統")
        
        # 檔案上傳
        st.markdown('<div class="section-title">選擇影音檔：</div>', unsafe_allow_html=True)
        st.markdown('<div class="upload-text">支援多種影音格式，包括 MP3、WAV、MP4、MKV 等</div>', unsafe_allow_html=True)
        
        uploaded_file = st.file_uploader(
            "上傳檔案",
            type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'],
            help="支援多種影音格式，包括 MP3、WAV、MP4、MKV 等",
            on_change=lambda: setattr(st.session_state, 'downloaded', False)
        )
        
        # 格式選擇
        st.markdown('<div class="section-title">選擇輸出格式：</div>', unsafe_allow_html=True)
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            txt_format = st.checkbox('純文字\n(.txt)', value=True)
        with col2:
            srt_format = st.checkbox('字幕檔\n(.srt)', value=True)
        with col3:
            vtt_format = st.checkbox('網頁字幕\n(.vtt)', value=True)
        with col4:
            tsv_format = st.checkbox('Excel格式\n(.tsv)', value=True)
        with col5:
            json_format = st.checkbox('JSON格式\n(.json)', value=True)
        
        formats = []
        if txt_format:
            formats.append('txt')
        if srt_format:
            formats.append('srt')
        if vtt_format:
            formats.append('vtt')
        if tsv_format:
            formats.append('tsv')
        if json_format:
            formats.append('json')
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button('開始提取', disabled=not (uploaded_file and formats) or st.session_state.get('processing', False)):
                try:
                    st.session_state.processing = True
                    st.session_state.downloaded = False
                    
                    with st.spinner('正在提取字幕...'):
                        outputs = process_audio(uploaded_file, formats)
                        st.session_state.outputs = outputs
                        st.session_state.filename = os.path.splitext(uploaded_file.name)[0]
                        st.session_state.processed = True
                        st.success('處理完成！請點擊右側按鈕下載字幕檔')
                except Exception as e:
                    st.error(f'處理失敗：{str(e)}')
                    logger.error(f"處理失敗：{str(e)}")
                finally:
                    st.session_state.processing = False
        
        with col2:
            if st.session_state.get('outputs') and not st.session_state.get('downloaded', False):
                zip_file = create_zip_file(st.session_state.outputs, st.session_state.filename)
                if st.download_button(
                    label='下載字幕檔',
                    data=zip_file,
                    file_name=f"{st.session_state.filename}_subtitles.zip",
                    mime='application/zip'
                ):
                    st.session_state.downloaded = True
                    st.success('下載完成！可以繼續處理新的檔案')
            else:
                st.button('下載字幕檔', disabled=True)

    except Exception as e:
        logger.error(f"主程式錯誤：{str(e)}")
        st.error(f"應用程式發生錯誤：{str(e)}")

if __name__ == '__main__':
    main()
