import streamlit as st
import whisper
import os
import subprocess
import tempfile
import json
from datetime import timedelta

# 設定頁面
st.set_page_config(
    page_title="影片字幕提取工具",
    page_icon="🎬",
    layout="centered"
)

# 標題和說明
st.title("影片字幕提取工具")
st.markdown("上傳影片或音訊檔案，自動提取字幕並轉換成多種格式。")

@st.cache_resource
def load_whisper_model(model_name):
    return whisper.load_model(model_name)

def format_timestamp(seconds):
    """格式化時間戳"""
    td = timedelta(seconds=seconds)
    hours = int(td.total_seconds() // 3600)
    minutes = int((td.total_seconds() % 3600) // 60)
    secs = int(td.total_seconds() % 60)
    millis = int((td.total_seconds() % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def write_srt(segments, output_path):
    """寫入 SRT 格式字幕"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for i, segment in enumerate(segments, 1):
            f.write(f"{i}\n")
            start = format_timestamp(segment['start'])
            end = format_timestamp(segment['end'])
            f.write(f"{start} --> {end}\n")
            f.write(f"{segment['text'].strip()}\n\n")

def write_vtt(segments, output_path):
    """寫入 VTT 格式字幕"""
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("WEBVTT\n\n")
        for segment in segments:
            start = format_timestamp(segment['start']).replace(',', '.')
            end = format_timestamp(segment['end']).replace(',', '.')
            f.write(f"{start} --> {end}\n")
            f.write(f"{segment['text'].strip()}\n\n")

# 檔案上傳
uploaded_file = st.file_uploader(
    "選擇影音檔案",
    type=['mp4', 'mkv', 'avi', 'mov', 'mp3', 'wav'],
    help="支援的格式：MP4, MKV, AVI, MOV, MP3, WAV"
)

# 選擇輸出格式
output_formats = st.multiselect(
    "選擇輸出格式",
    ['txt', 'srt', 'vtt', 'tsv', 'json'],
    default=['txt', 'srt'],
    help="可以選擇多種輸出格式"
)

# 選擇模型大小
model_size = st.selectbox(
    "選擇模型大小",
    ["tiny", "base", "small"],
    index=1,
    help="tiny：最快但較不準確\nbase：平衡速度和準確度\nsmall：較慢但更準確"
)

if uploaded_file and output_formats and st.button("開始提取字幕", help="點擊開始處理"):
    try:
        # 建立臨時目錄
        with tempfile.TemporaryDirectory() as temp_dir:
            # 保存上傳的檔案
            input_path = os.path.join(temp_dir, uploaded_file.name)
            with open(input_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            # 轉換音訊
            audio_path = os.path.join(temp_dir, "audio.wav")
            progress_text = "正在轉換音訊..."
            progress_bar = st.progress(0)
            status_text = st.empty()
            status_text.text(progress_text)
            
            try:
                subprocess.run([
                    'ffmpeg',
                    '-i', input_path,
                    '-vn',
                    '-acodec', 'pcm_s16le',
                    '-ar', '16000',
                    '-ac', '1',
                    '-y',
                    audio_path
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                st.error(f"音訊轉換失敗：{e.stderr.decode()}")
                st.stop()
            
            progress_bar.progress(25)
            
            # 載入模型
            status_text.text(f"正在載入 Whisper {model_size} 模型...")
            model = load_whisper_model(model_size)
            
            progress_bar.progress(50)
            
            # 辨識文字
            status_text.text("正在辨識文字...")
            result = model.transcribe(audio_path)
            
            progress_bar.progress(75)
            
            # 產生各種格式的輸出
            status_text.text("正在產生輸出檔案...")
            
            output_files = {}
            base_name = os.path.splitext(uploaded_file.name)[0]
            
            for fmt in output_formats:
                output_path = os.path.join(temp_dir, f"{base_name}.{fmt}")
                
                if fmt == 'txt':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        for segment in result['segments']:
                            f.write(segment['text'].strip() + '\n')
                
                elif fmt == 'srt':
                    write_srt(result['segments'], output_path)
                
                elif fmt == 'vtt':
                    write_vtt(result['segments'], output_path)
                
                elif fmt == 'tsv':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        f.write('start\tend\ttext\n')
                        for segment in result['segments']:
                            f.write(f"{segment['start']}\t{segment['end']}\t{segment['text']}\n")
                
                elif fmt == 'json':
                    with open(output_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                
                # 讀取檔案內容以供下載
                with open(output_path, 'r', encoding='utf-8') as f:
                    output_files[fmt] = f.read()
            
            progress_bar.progress(100)
            status_text.text("處理完成！")
            
            # 顯示下載按鈕
            st.success("字幕提取完成！請下載您需要的格式。")
            
            col1, col2 = st.columns(2)
            for i, (fmt, content) in enumerate(output_files.items()):
                with col1 if i % 2 == 0 else col2:
                    st.download_button(
                        label=f"下載 {fmt.upper()} 格式",
                        data=content,
                        file_name=f"{base_name}.{fmt}",
                        mime='text/plain',
                        help=f"下載 {fmt.upper()} 格式的字幕檔"
                    )
            
            # 預覽第一個格式的內容
            if output_files:
                first_fmt = list(output_files.keys())[0]
                st.markdown(f"### 預覽 ({first_fmt.upper()} 格式)")
                st.code(output_files[first_fmt][:1000] + 
                       ("\n..." if len(output_files[first_fmt]) > 1000 else ""))
    
    except Exception as e:
        st.error(f"處理過程中發生錯誤：{str(e)}")
        st.exception(e)
