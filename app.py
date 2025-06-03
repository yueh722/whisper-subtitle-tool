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

# 設定日誌
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 設定頁面
st.set_page_config(
    page_title="字幕提取器",
    page_icon="🎬",
    layout="centered"
)

# 初始化 session state
if 'model' not in st.session_state:
    st.session_state.model = None
    st.session_state.model_loaded = False

# 延遲載入 whisper 和 torch
def load_whisper_model():
    if not st.session_state.model_loaded:
        try:
            import whisper
            st.session_state.model = whisper.load_model("base")
            st.session_state.model_loaded = True
            return True
        except Exception as e:
            logger.error(f"模型載入失敗：{str(e)}")
            return False
    return True

# 自定義 CSS
st.markdown("""
<style>
    /* 基本樣式 */
    :root {
        --primary-color: #2196F3;
        --primary-dark: #1976D2;
        --background-color: #1a1a2e;
        --text-color: #ffffff;
    }

    /* 上傳區域樣式 */
    .stFileUploader {
        background-color: rgba(36, 36, 68, 0.4) !important;
        border: 1px solid var(--primary-color) !important;
        border-radius: 5px !important;
        padding: 20px !important;
        margin-bottom: 20px !important;
    }

    /* 上傳區域內的所有文字 */
    .stFileUploader div,
    .stFileUploader p,
    .stFileUploader span,
    .stFileUploader small {
        color: var(--text-color) !important;
        opacity: 1 !important;
    }

    /* 檔案名稱和大小 */
    .stFileUploader [data-testid="stMarkdownContainer"] p {
        color: var(--text-color) !important;
        font-weight: 500 !important;
        font-size: 1.1em !important;
        text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.3) !important;
    }

    /* 拖放區域文字 */
    [data-testid="stFileUploadDropzone"] {
        color: var(--text-color) !important;
        background-color: transparent !important;
    }

    /* 上傳按鈕 */
    .stFileUploader button {
        background-color: var(--primary-color) !important;
        color: var(--text-color) !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        font-weight: 500 !important;
    }

    /* 標題樣式 */
    .section-title {
        color: var(--text-color) !important;
        font-size: 1.2em !important;
        font-weight: 500 !important;
        margin: 1em 0 0.5em 0 !important;
    }

    /* 確保所有文字可見 */
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
        # 確保模型已載入
        if not load_whisper_model():
            raise Exception("無法載入語音識別模型，請重新啟動應用程式")
        
        # 建立臨時檔案
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_audio:
            try:
                temp_audio.write(audio_file.getvalue())
                temp_audio_path = temp_audio.name
                
                # 使用 Whisper 處理
                import torch
                with torch.inference_mode():
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
        
        # 初始化 session state
        if 'processed' not in st.session_state:
            st.session_state.processed = False
            st.session_state.outputs = None
            st.session_state.filename = None
            st.session_state.status_message = "請選擇要處理的影音檔案"
            st.session_state.status_type = "info"
            st.session_state.processing = False
            st.session_state.downloaded = False
        
        # 檔案上傳
        st.markdown('<div class="section-title">選擇影音檔：</div>', unsafe_allow_html=True)
        uploaded_file = st.file_uploader(
            "上傳檔案",
            type=['mp3', 'wav', 'mp4', 'mkv', 'avi', 'mov', 'wmv', 'flv', 'webm'],
            help="支援多種影音格式，包括 MP3、WAV、MP4、MKV 等",
            label_visibility="collapsed",
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
        
        # 使用自定義的按鈕容器
        st.markdown('<div class="button-container">', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        
        with col1:
            process_btn_disabled = not (uploaded_file and formats) or st.session_state.processing
            process_btn_class = "" if process_btn_disabled else "active"
            if st.button('開始提取', disabled=process_btn_disabled, key='process_btn'):
                try:
                    st.session_state.processing = True
                    st.session_state.downloaded = False
                    st.session_state.status_message = "字幕提取中..."
                    st.session_state.status_type = "info"
                    
                    outputs = process_audio(uploaded_file, formats)
                    st.session_state.outputs = outputs
                    st.session_state.filename = os.path.splitext(uploaded_file.name)[0]
                    st.session_state.processed = True
                    st.session_state.processing = False
                    st.session_state.status_message = "處理完成！請點擊右側按鈕下載字幕檔"
                    st.session_state.status_type = "success"
                except Exception as e:
                    st.session_state.processing = False
                    st.session_state.status_message = f"處理失敗：{str(e)}"
                    st.session_state.status_type = "error"
                    logger.error(f"處理失敗：{str(e)}")
                    st.session_state.processed = False
        
        with col2:
            download_btn_disabled = not st.session_state.processed or st.session_state.downloaded
            if st.session_state.outputs and not st.session_state.downloaded:
                zip_file = create_zip_file(st.session_state.outputs, st.session_state.filename)
                if st.download_button(
                    label='下載字幕檔',
                    data=zip_file,
                    file_name=f"{st.session_state.filename}_subtitles.zip",
                    mime='application/zip',
                    disabled=download_btn_disabled,
                    key='download_btn'
                ):
                    st.session_state.downloaded = True
                    st.session_state.status_message = "下載完成！可以繼續處理新的檔案"
                    st.session_state.status_type = "success"
                    st.rerun()
            else:
                st.button('下載字幕檔', disabled=True, key='download_btn_disabled')
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # 更新狀態訊息
        if not uploaded_file:
            st.session_state.status_message = "請選擇要處理的影音檔案"
            st.session_state.status_type = "info"
        elif not formats:
            st.session_state.status_message = "請至少選擇一種輸出格式"
            st.session_state.status_type = "warning"
        
        # 顯示狀態訊息
        st.markdown(
            f'<div id="status-area"><div class="status-message status-{st.session_state.status_type}">{st.session_state.status_message}</div></div>',
            unsafe_allow_html=True
        )
    except Exception as e:
        logger.error(f"主程式錯誤：{str(e)}")
        st.error(f"應用程式發生錯誤：{str(e)}")

if __name__ == '__main__':
    main()
