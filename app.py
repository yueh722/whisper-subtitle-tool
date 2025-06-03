import os
import whisper
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

# 設定日誌
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 設定頁面
st.set_page_config(
    page_title="字幕提取器",
    page_icon="🎬",
    layout="centered"
)

# 自定義 CSS
st.markdown("""
<style>
    :root {
        --primary-color: #2196F3;
        --primary-dark: #1976D2;
        --background-color: #1a1a2e;
        --container-bg: #242444;
        --text-color: #ffffff;
        --border-color: #3498db;
    }

    .stApp {
        background-color: var(--background-color);
    }

    .main {
        background-color: var(--container-bg);
        color: var(--text-color);
        max-width: 800px;
        margin: 0 auto;
    }

    h1 {
        color: var(--text-color) !important;
        text-align: center !important;
        margin-bottom: 30px !important;
        font-size: 2.2em !important;
        text-transform: uppercase !important;
        letter-spacing: 2px !important;
        position: relative !important;
        padding-bottom: 15px !important;
    }

    h1:after {
        content: '' !important;
        position: absolute !important;
        bottom: 0 !important;
        left: 50% !important;
        transform: translateX(-50%) !important;
        width: 60px !important;
        height: 4px !important;
        background: var(--primary-color) !important;
        border-radius: 2px !important;
    }

    /* 檔案上傳區域樣式 */
    section[data-testid="stFileUploader"] {
        background-color: transparent !important;
        border: 1px solid var(--border-color) !important;
        border-radius: 5px !important;
        padding: 0 !important;
        margin-bottom: 20px !important;
    }

    section[data-testid="stFileUploader"] [data-testid="stFileUploadDropzone"] {
        background-color: transparent !important;
        border: none !important;
        padding: 20px !important;
    }

    /* 修改上傳按鈕文字 */
    button[data-testid="baseButton-secondary"] {
        display: none !important;
    }

    button[data-testid="baseButton-secondary"] + div::before {
        content: '選擇檔案' !important;
        display: inline-block !important;
        background-color: transparent !important;
        border: 1px solid var(--border-color) !important;
        color: white !important;
        padding: 8px 16px !important;
        border-radius: 4px !important;
        cursor: pointer !important;
    }

    /* 上傳區域文字樣式 */
    section[data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {
        color: var(--text-color) !important;
        font-size: 1.1em !important;
        margin: 5px 0 !important;
    }

    section[data-testid="stFileUploader"] small {
        color: rgba(255, 255, 255, 0.7) !important;
    }

    /* 標題文字樣式 */
    .section-title {
        color: white !important;
        font-size: 1.1em !important;
        font-weight: 500 !important;
        margin-bottom: 0.5em !important;
        margin-top: 1em !important;
    }

    /* 格式選擇區域樣式 */
    div.row-widget.stCheckbox {
        background-color: rgba(36, 36, 68, 0.4) !important;
        border: 1px solid var(--border-color) !important;
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
        background-color: rgba(33, 150, 243, 0.2) !important;
        border-color: var(--primary-color) !important;
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
        background-color: #ff4b4b !important;
        border-color: #ff4b4b !important;
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

    /* 提示訊息和按鈕容器樣式 */
    div.stAlert {
        background-color: rgba(36, 36, 68, 0.4) !important;
        border: 1px solid var(--border-color) !important;
        border-radius: 5px !important;
        padding: 16px !important;
        margin: 20px 0 !important;
        text-align: left !important;
        min-height: 60px !important;
    }

    /* 按鈕容器 */
    div.element-container:has(> div.stButton), 
    div.element-container:has(> div.stDownloadButton) {
        margin: 0 !important;
        padding: 0 !important;
    }

    div.row-widget.stButton,
    div.row-widget.stDownloadButton {
        margin: 0 !important;
        padding: 0 !important;
    }

    .stButton > button,
    .stDownloadButton > button {
        width: 100% !important;
        height: 42px !important;
        margin: 0 !important;
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

    /* 隱藏 Streamlit 預設的漢堡選單和頁尾 */
    #MainMenu, footer {
        visibility: hidden;
    }

    /* 確保所有文字容器中的文字可見 */
    div[data-testid="stMarkdownContainer"] {
        color: var(--text-color) !important;
    }
</style>
""", unsafe_allow_html=True)

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
        # 載入模型（如果尚未載入）
        if 'model' not in st.session_state:
            with st.spinner('正在載入 Whisper 模型...'):
                st.session_state.model = whisper.load_model("base")
        
        # 建立臨時檔案
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
            temp_audio.write(audio_file.getvalue())
            temp_audio_path = temp_audio.name

        # 使用 Whisper 處理
        with st.spinner('正在提取字幕...'):
            result = st.session_state.model.transcribe(temp_audio_path, verbose=False)

        # 生成不同格式的輸出
        outputs = {}
        processed_segments = merge_short_segments(result['segments'])
        
        if 'txt' in formats:
            outputs['txt'] = '\n'.join(clean_text(segment['text']) for segment in processed_segments)
        
        if 'srt' in formats:
            outputs['srt'] = write_srt(result['segments'])
            
        if 'vtt' in formats:
            outputs['vtt'] = write_vtt(result['segments'])
            
        if 'tsv' in formats:
            outputs['tsv'] = '開始時間\t結束時間\t文字內容\n' + '\n'.join(
                f"{format_timestamp(seg['start'])}\t{format_timestamp(seg['end'])}\t{clean_text(seg['text'])}"
                for seg in processed_segments
            )
            
        if 'json' in formats:
            clean_result = {
                'text': '\n'.join(clean_text(segment['text']) for segment in processed_segments),
                'segments': [{
                    'start': segment['start'],
                    'end': segment['end'],
                    'text': clean_text(segment['text'])
                } for segment in processed_segments]
            }
            outputs['json'] = json.dumps(clean_result, ensure_ascii=False, indent=2)
        
        # 清理臨時檔案
        os.unlink(temp_audio_path)
        
        return outputs
        
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
    st.title("智能字幕提取系統")
    
    # 初始化 session state
    if 'processed' not in st.session_state:
        st.session_state.processed = False
        st.session_state.outputs = None
        st.session_state.filename = None
    
    # 檔案上傳
    st.markdown('<div class="section-title">選擇影音檔：</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "",
        type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'],
        help="支援多種影音格式，包括 MP3、WAV、MP4、MKV 等"
    )
    
    # 格式選擇
    st.markdown('<div class="section-title">選擇輸出格式：</div>', unsafe_allow_html=True)
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        txt_format = st.checkbox('純文字\n(.txt)', value=True)
    with col2:
        srt_format = st.checkbox('字幕檔\n(.srt)', value=True)
    with col3:
        vtt_format = st.checkbox('網頁字幕\n(.vtt)')
    with col4:
        tsv_format = st.checkbox('Excel格式\n(.tsv)')
    with col5:
        json_format = st.checkbox('JSON格式\n(.json)')
    
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
    
    # 使用自定義的按鈕容器
    st.markdown('<div class="button-container">', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    
    with col1:
        process_btn_disabled = not (uploaded_file and formats)
        if st.button('開始提取', disabled=process_btn_disabled, key='process_btn'):
            try:
                with st.spinner('正在處理中...'):
                    outputs = process_audio(uploaded_file, formats)
                    st.session_state.outputs = outputs
                    st.session_state.filename = os.path.splitext(uploaded_file.name)[0]
                    st.session_state.processed = True
                st.success('處理完成！請點擊右側按鈕下載字幕檔')
            except Exception as e:
                st.error(f'處理失敗：{str(e)}')
                logger.error(f"處理失敗：{str(e)}")
                st.session_state.processed = False
    
    with col2:
        if st.session_state.processed and st.session_state.outputs:
            zip_file = create_zip_file(st.session_state.outputs, st.session_state.filename)
            st.download_button(
                label='下載字幕檔',
                data=zip_file,
                file_name=f"{st.session_state.filename}_subtitles.zip",
                mime='application/zip',
                key='download_btn'
            )
        else:
            st.button('下載字幕檔', disabled=True, key='download_btn')
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # 顯示說明
    if uploaded_file is None:
        st.info('請選擇要處理的影音檔案')
    elif not formats:
        st.warning('請至少選擇一種輸出格式')

if __name__ == '__main__':
    main()
