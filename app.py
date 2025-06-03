import os
import whisper
import streamlit as st
from datetime import datetime
import subprocess
import uuid
import json
import logging
import tempfile
import zipfile
import io

# 設定日誌
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 設定頁面
st.set_page_config(
    page_title="智能字幕提取系統",
    page_icon="🎬",
    layout="centered"
)

# 自定義 CSS
st.markdown("""
<style>
    .stApp {
        background-color: #f5f5f5;
    }
    
    .main {
        background-color: white;
        padding: 2rem;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
    
    h1 {
        color: #333;
        text-align: center;
        margin-bottom: 30px;
        font-size: 2.2em;
        padding-bottom: 15px;
        border-bottom: 4px solid #2196F3;
    }
    
    .stButton > button {
        width: 100%;
        background-color: #cccccc;
        color: #666666;
        padding: 0.8rem;
        font-size: 1.1em;
        border: none;
        border-radius: 4px;
        cursor: not-allowed;
        transition: all 0.3s ease;
    }
    
    .stButton > button.active {
        background-color: #2196F3;
        color: white;
        cursor: pointer;
    }
    
    .stButton > button.active:hover {
        background-color: #1976D2;
    }
    
    div[data-testid="stFileUploader"] {
        background-color: white;
        border: 1px solid #ddd;
        border-radius: 4px;
        padding: 1rem;
    }
    
    .stCheckbox {
        background-color: white;
        padding: 0.5rem;
        margin: 0.5rem 0;
    }
    
    div[data-testid="stMarkdownContainer"] {
        color: #333;
    }
    
    .status-info {
        padding: 1rem;
        border-radius: 4px;
        background-color: #e3f2fd;
        color: #0d47a1;
        margin: 1rem 0;
    }
    
    .status-error {
        padding: 1rem;
        border-radius: 4px;
        background-color: #ffebee;
        color: #c62828;
        margin: 1rem 0;
    }
    
    .status-success {
        padding: 1rem;
        border-radius: 4px;
        background-color: #e8f5e9;
        color: #2e7d32;
        margin: 1rem 0;
    }
    
    .checkbox-group {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 20px 0;
        justify-content: center;
    }
    
    .format-option {
        flex: 1;
        min-width: 150px;
        max-width: 200px;
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
    uploaded_file = st.file_uploader(
        "選擇影音檔",
        type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'],
        help="支援多種影音格式，包括 MP3、WAV、MP4、MKV 等"
    )
    
    # 格式選擇
    st.write("選擇輸出格式：")
    
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        txt_format = st.checkbox('純文字 (.txt)', value=True)
    with col2:
        srt_format = st.checkbox('字幕檔 (.srt)', value=True)
    with col3:
        vtt_format = st.checkbox('網頁字幕 (.vtt)')
    with col4:
        tsv_format = st.checkbox('Excel格式 (.tsv)')
    with col5:
        json_format = st.checkbox('JSON格式')
    
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
    
    # 處理按鈕
    process_btn = st.empty()
    download_btn = st.empty()
    
    # 根據狀態設定按鈕樣式
    process_btn_disabled = not (uploaded_file and formats)
    process_btn_class = "" if process_btn_disabled else "active"
    
    if process_btn.button('開始提取', disabled=process_btn_disabled, key='process_btn'):
        try:
            with st.spinner('正在處理中...'):
                # 處理檔案
                outputs = process_audio(uploaded_file, formats)
                st.session_state.outputs = outputs
                st.session_state.filename = os.path.splitext(uploaded_file.name)[0]
                st.session_state.processed = True
            
            # 顯示成功訊息
            st.success('處理完成！請點擊下方按鈕下載字幕檔')
            
        except Exception as e:
            st.error(f'處理失敗：{str(e)}')
            logger.error(f"處理失敗：{str(e)}")
            st.session_state.processed = False
    
    # 下載按鈕
    if st.session_state.processed and st.session_state.outputs:
        zip_file = create_zip_file(st.session_state.outputs, st.session_state.filename)
        download_btn.download_button(
            label='下載字幕檔',
            data=zip_file,
            file_name=f"{st.session_state.filename}_subtitles.zip",
            mime='application/zip',
            key='download_btn'
        )
    else:
        download_btn.button('下載字幕檔', disabled=True, key='download_btn')
    
    # 顯示說明
    if uploaded_file is None:
        st.info('請選擇要處理的影音檔案')
    elif not formats:
        st.warning('請至少選擇一種輸出格式')

if __name__ == '__main__':
    main()
