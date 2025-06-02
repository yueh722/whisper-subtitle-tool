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

# 初始化 session state
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = {}

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
uploaded_file = st.file_uploader("選擇影音檔案", type=['mp4', 'mkv', 'avi', 'mov', 'mp3', 'wav'])

# 選擇輸出格式
output_formats = st.multiselect(
    "選擇輸出格式",
    ['txt', 'srt', 'vtt', 'tsv', 'json'],
    default=['txt', 'srt']
)

# 選擇模型大小
model_size = st.selectbox(
    "選擇模型大小（越大越準確但處理較慢）",
    ["tiny", "base", "small", "medium", "large"],
    index=1
)

if uploaded_file and output_formats and st.button("開始提取字幕"):
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
            st.text(progress_text)
            
            subprocess.run([
                'ffmpeg',
                '-i', input_path,
                '-vn',
                '-acodec', 'pcm_s16le',
                '-ar', '16000',
                '-ac', '1',
                '-y',
                audio_path
            ], check=True)
            
            progress_bar.progress(25)
            
            # 載入模型
            progress_text = f"正在載入 Whisper {model_size} 模型..."
            st.text(progress_text)
            model = whisper.load_model(model_size)
            
            progress_bar.progress(50)
            
            # 辨識文字
            progress_text = "正在辨識文字..."
            st.text(progress_text)
            result = model.transcribe(audio_path)
            
            progress_bar.progress(75)
            
            # 產生各種格式的輸出
            progress_text = "正在產生輸出檔案..."
            st.text(progress_text)
            
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
            st.success("處理完成！")
            
            # 顯示下載按鈕
            st.markdown("### 下載字幕檔")
            for fmt, content in output_files.items():
                st.download_button(
                    label=f"下載 {fmt.upper()} 格式",
                    data=content,
                    file_name=f"{base_name}.{fmt}",
                    mime='text/plain'
                )
            
            # 預覽第一個格式的內容
            if output_files:
                first_fmt = list(output_files.keys())[0]
                st.markdown(f"### 預覽 ({first_fmt.upper()} 格式)")
                st.code(output_files[first_fmt][:1000] + 
                       ("\n..." if len(output_files[first_fmt]) > 1000 else ""))
    
    except Exception as e:
        st.error(f"處理過程中發生錯誤：{str(e)}")
