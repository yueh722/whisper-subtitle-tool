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
    .stApp {
        background-color: #1a1a2e;
    }
    
    .main {
        background-color: #242444;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        border: 1px solid #3498db;
    }
    
    h1 {
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        font-size: 2.2em;
        text-transform: uppercase;
        letter-spacing: 2px;
        position: relative;
        padding-bottom: 15px;
    }
    
    h1:after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 50%;
        transform: translateX(-50%);
        width: 60px;
        height: 4px;
        background: #2196F3;
        border-radius: 2px;
    }
    
    .stButton > button {
        width: 100%;
        background-color: rgba(33, 150, 243, 0.8);
        color: white;
        padding: 0.8rem;
        font-size: 1.1em;
        border: none;
        border-radius: 5px;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    
    .stButton > button:hover {
        background-color: #1976D2;
        transform: translateY(-2px);
    }
    
    .stButton > button:disabled {
        background-color: rgba(36, 36, 68, 0.6);
        cursor: not-allowed;
    }
    
    div[data-testid="stFileUploader"] {
        background-color: rgba(36, 36, 68, 0.6);
        border: 1px solid #3498db;
        border-radius: 5px;
        padding: 1rem;
    }
    
    .stCheckbox {
        background-color: rgba(36, 36, 68, 0.6);
        padding: 1rem;
        border-radius: 5px;
        border: 1px solid #3498db;
        margin: 0.5rem 0;
    }
    
    .stCheckbox label {
        color: white !important;
    }
    
    div[data-testid="stMarkdownContainer"] {
        color: white;
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

def main():
    st.title("智能字幕提取系統")
    
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
    if uploaded_file is not None and formats and st.button('開始提取', key='process_btn'):
        try:
            with st.spinner('正在處理中...'):
                # 處理檔案
                outputs = process_audio(uploaded_file, formats)
            
            # 顯示成功訊息
            st.success('處理完成！請點擊下方按鈕下載字幕檔')
            
            # 為每個格式創建下載按鈕
            cols = st.columns(len(outputs))
            for i, (fmt, content) in enumerate(outputs.items()):
                with cols[i]:
                    filename = f"{os.path.splitext(uploaded_file.name)[0]}.{fmt}"
                    mime_type = 'text/plain'
                    if fmt == 'json':
                        mime_type = 'application/json'
                    elif fmt == 'tsv':
                        mime_type = 'text/tab-separated-values'
                    
                    st.download_button(
                        label=f'下載 {fmt.upper()} 檔案',
                        data=content.encode('utf-8'),
                        file_name=filename,
                        mime=mime_type,
                        key=f'download_{fmt}'
                    )
                
        except Exception as e:
            st.error(f'處理失敗：{str(e)}')
            logger.error(f"處理失敗：{str(e)}")
    
    # 顯示說明
    if uploaded_file is None:
        st.info('請選擇要處理的影音檔案')
    elif not formats:
        st.warning('請至少選擇一種輸出格式')

if __name__ == '__main__':
    main()
