import os
import whisper
import streamlit as st
from datetime import datetime
import subprocess
import uuid
import json
import logging
import tempfile

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
    .stButton > button {
        width: 100%;
        background-color: #2196F3;
        color: white;
    }
    .stButton > button:hover {
        background-color: #1976D2;
        color: white;
    }
    .status-info {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #e3f2fd;
        color: #0d47a1;
    }
    .status-error {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #ffebee;
        color: #c62828;
    }
    .status-success {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #e8f5e9;
        color: #2e7d32;
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
        
        # 清理臨時檔案
        os.unlink(temp_audio_path)
        
        return outputs
        
    except Exception as e:
        logger.error(f"處理失敗：{str(e)}")
        raise

def main():
    st.title("智能字幕提取系統")
    
    # 檔案上傳
    uploaded_file = st.file_uploader("選擇影音檔", type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov'])
    
    # 格式選擇
    col1, col2 = st.columns(2)
    with col1:
        txt_format = st.checkbox('純文字 (.txt)', value=True)
    with col2:
        srt_format = st.checkbox('字幕檔 (.srt)', value=True)
    
    formats = []
    if txt_format:
        formats.append('txt')
    if srt_format:
        formats.append('srt')
    
    if uploaded_file is not None and formats and st.button('開始提取'):
        try:
            # 處理檔案
            outputs = process_audio(uploaded_file, formats)
            
            # 顯示下載按鈕
            st.success('處理完成！')
            
            # 為每個格式創建下載按鈕
            for fmt, content in outputs.items():
                filename = f"{os.path.splitext(uploaded_file.name)[0]}.{fmt}"
                st.download_button(
                    label=f'下載 {fmt.upper()} 檔案',
                    data=content.encode('utf-8'),
                    file_name=filename,
                    mime='text/plain'
                )
                
        except Exception as e:
            st.error(f'處理失敗：{str(e)}')
            logger.error(f"處理失敗：{str(e)}")

if __name__ == '__main__':
    main()
