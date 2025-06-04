import os
import whisper
from flask import Flask, request, send_file, render_template_string, redirect, jsonify, make_response
from werkzeug.utils import secure_filename
import subprocess
import uuid
import zipfile
import io
import shutil
import logging
import threading
import time
import traceback
import webbrowser
import socket
import json
import atexit

# 設定日誌
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
# 使用 C:\ffmpeg\bin 作為基礎路徑
BASE_DIR = r'C:\ffmpeg\bin'
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
FFMPEG_PATH = os.path.join(BASE_DIR, 'ffmpeg.exe')
TASKS_FILE = os.path.join(BASE_DIR, 'tasks.json')

# 確保資料夾存在
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# 儲存處理狀態
processing_tasks = {}

def save_tasks():
    """將任務狀態儲存到檔案"""
    try:
        with open(TASKS_FILE, 'w', encoding='utf-8') as f:
            # 只儲存已完成的任務
            completed_tasks = {
                task_id: task for task_id, task in processing_tasks.items()
                if task['status'] == 'completed' and os.path.exists(task.get('zip_path', ''))
            }
            json.dump(completed_tasks, f, ensure_ascii=False, indent=2)
        logger.info("任務狀態已儲存")
    except Exception as e:
        logger.error(f"儲存任務狀態時發生錯誤：{str(e)}")

def load_tasks():
    """從檔案載入任務狀態"""
    global processing_tasks
    try:
        if os.path.exists(TASKS_FILE):
            with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                loaded_tasks = json.load(f)
                # 驗證每個任務的輸出檔案是否存在
                valid_tasks = {}
                for task_id, task in loaded_tasks.items():
                    if os.path.exists(task.get('zip_path', '')):
                        valid_tasks[task_id] = task
                    else:
                        logger.warning(f"任務 {task_id} 的輸出檔案不存在，將被忽略")
                processing_tasks = valid_tasks
            logger.info(f"已載入 {len(processing_tasks)} 個有效任務")
    except Exception as e:
        logger.error(f"載入任務狀態時發生錯誤：{str(e)}")
        processing_tasks = {}

# 程式啟動時載入任務狀態
load_tasks()

# 註冊程式結束時的處理函數
atexit.register(save_tasks)

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

FORM_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>字幕提取器</title>
    <meta charset="UTF-8">
    <style>
        :root {
            --primary-color: #2196F3;
            --primary-dark: #1976D2;
            --background-color: #1a1a2e;
            --container-bg: #242444;
            --text-color: #ffffff;
            --border-color: #3498db;
        }

        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 40px 20px;
            background-color: var(--background-color);
            color: var(--text-color);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        .container {
            background-color: var(--container-bg);
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
            backdrop-filter: blur(4px);
            border: 1px solid var(--border-color);
            width: 90%;
            max-width: 800px;
        }

        h2 {
            color: var(--text-color);
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.2em;
            text-transform: uppercase;
            letter-spacing: 2px;
            position: relative;
            padding-bottom: 15px;
        }

        h2:after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%);
            width: 60px;
            height: 4px;
            background: var(--primary-color);
            border-radius: 2px;
        }

        .form-group {
            margin-bottom: 30px;
        }

        .form-group label {
            display: block;
            margin-bottom: 10px;
            font-size: 1.1em;
            color: var(--text-color);
        }

        .file-input-container {
            position: relative;
            margin-bottom: 20px;
        }

        .file-input-label {
            display: inline-block;
            padding: 15px 20px;
            background-color: rgba(36, 36, 68, 0.6);
            color: var(--text-color);
            border-radius: 5px;
            cursor: pointer;
            width: 100%;
            text-align: center;
            transition: all 0.3s ease;
            border: 1px solid var(--border-color);
            font-size: 1.5em;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .file-input-label.has-file {
            background-color: rgba(33, 150, 243, 0.15);
            border-color: var(--primary-color);
            filter: brightness(1.5);
        }

        .file-input-label:hover {
            background-color: rgba(33, 150, 243, 0.3);
        }

        .file-input {
            position: absolute;
            left: -9999px;
        }

        .checkbox-group {
            display: flex;
            justify-content: center;
            gap: 10px;
            margin: 20px 0;
            flex-wrap: nowrap;
        }

        .format-option {
            flex: 1;
            max-width: 150px;
        }

        .format-option input[type="checkbox"] {
            display: none;
        }

        .format-option label {
            display: block;
            padding: 12px 15px;
            text-align: center;
            background-color: rgba(36, 36, 68, 0.6);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-size: 0.9em;
            color: var(--text-color);
            opacity: 0.6;
        }

        .format-option input[type="checkbox"]:checked + label {
            background-color: rgba(33, 150, 243, 0.15);
            border-color: var(--primary-color);
            opacity: 1;
            filter: brightness(1.5);
        }

        .format-option label:hover {
            opacity: 0.8;
            background-color: rgba(33, 150, 243, 0.2);
        }

        .button-group {
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-bottom: 20px;
        }

        .button {
            flex: 1;
            max-width: 250px;
            padding: 12px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1em;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
            background-color: rgba(36, 36, 68, 0.6); /* 預設為暗色 */
            color: rgba(255, 255, 255, 0.3);
            filter: brightness(0.8);
        }

        .button.active {
            background-color: rgba(33, 150, 243, 0.8);
            color: white;
            filter: brightness(1);
            cursor: pointer;
        }

        .button.active:hover {
            background-color: var(--primary-color);
            transform: translateY(-2px);
            filter: brightness(1.2);
        }

        .button:disabled {
            background-color: rgba(36, 36, 68, 0.6);
            cursor: not-allowed;
            color: rgba(255, 255, 255, 0.3);
            transform: none;
            filter: brightness(0.8);
        }

        #status-area {
            margin-top: 30px;
            padding: 20px;
            border-radius: 10px;
            background-color: rgba(36, 36, 68, 0.4);
            min-height: 60px;
            font-size: 1.2em;
        }

        .status-message {
            margin: 10px 0;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
        }

        .status-info {
            background-color: rgba(52, 152, 219, 0.1);
            color: rgba(52, 152, 219, 0.8);
        }

        .status-error {
            background-color: rgba(231, 76, 60, 0.1);
            color: rgba(231, 76, 60, 0.8);
        }

        .status-success {
            background-color: rgba(46, 204, 113, 0.1);
            color: rgba(46, 204, 113, 0.8);
        }

        .loading {
            display: inline-block;
            width: 24px;
            height: 24px;
            border: 3px solid rgba(255, 255, 255, 0.3);
            border-top: 3px solid var(--primary-color);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-right: 10px;
            vertical-align: middle;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .hidden {
            display: none;
        }

        /* 新增的動畫效果 */
        .container {
            animation: fadeIn 0.5s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .button, .file-input-label {
            position: relative;
            overflow: hidden;
        }

        .button:after, .file-input-label:after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(
                to right,
                rgba(255, 255, 255, 0) 0%,
                rgba(255, 255, 255, 0.3) 50%,
                rgba(255, 255, 255, 0) 100%
            );
            transform: rotate(45deg);
            transition: all 0.5s;
            opacity: 0;
        }

        .button:hover:not(:disabled):after,
        .file-input-label:hover:after {
            animation: shine 1.5s ease-out infinite;
        }

        @keyframes shine {
            0% { transform: rotate(45deg) translateX(-200%); }
            100% { transform: rotate(45deg) translateX(200%); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>智能字幕提取系統</h2>
        <form id="uploadForm">
            <div class="form-group">
                <div class="file-input-container">
                    <label class="file-input-label" for="media-file">
                        選擇影音檔
                    </label>
                    <input type="file" id="media-file" name="media" required class="file-input" 
                        accept="audio/*,video/*,.mkv,.mp4,.avi,.mov,.wmv,.flv,.webm">
                </div>
            </div>
            
            <div class="form-group">
                <label>選擇輸出格式：</label>
                <div class="checkbox-group">
                    <div class="format-option">
                        <input type="checkbox" id="format-txt" name="formats" value="txt" checked>
                        <label for="format-txt">純文字<br>(.txt)</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="format-srt" name="formats" value="srt" checked>
                        <label for="format-srt">字幕檔<br>(.srt)</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="format-vtt" name="formats" value="vtt">
                        <label for="format-vtt">網頁字幕<br>(.vtt)</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="format-tsv" name="formats" value="tsv">
                        <label for="format-tsv">Excel格式<br>(.tsv)</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="format-json" name="formats" value="json">
                        <label for="format-json">JSON格式<br>(.json)</label>
                    </div>
                </div>
            </div>
            
            <div class="button-group">
                <button type="submit" class="button" id="submitBtn" disabled>開始提取</button>
                <button type="button" class="button" id="downloadBtn" disabled>下載字幕檔</button>
            </div>
            
            <div id="status-area">
                <div class="status-message status-info">請選擇影音檔案並點擊「開始提取」按鈕</div>
            </div>
        </form>
    </div>

    <script>
        // 更新按鈕狀態
        function updateSubmitButton() {
            const submitBtn = document.getElementById('submitBtn');
            const fileInput = document.getElementById('media-file');
            const formatCheckboxes = document.querySelectorAll('input[name="formats"]:checked');
            
            if (fileInput.files.length > 0 && formatCheckboxes.length > 0) {
                submitBtn.disabled = false;
                submitBtn.classList.add('active');
            } else {
                submitBtn.disabled = true;
                submitBtn.classList.remove('active');
            }
        }

        // 監聽檔案選擇
        document.getElementById('media-file').addEventListener('change', function(e) {
            const label = document.querySelector('.file-input-label');
            if (e.target.files[0]) {
                label.textContent = e.target.files[0].name;
                label.classList.add('has-file');
            } else {
                label.textContent = '選擇影音檔';
                label.classList.remove('has-file');
            }
            updateSubmitButton();
        });

        // 監聽格式選擇
        document.querySelectorAll('input[name="formats"]').forEach(checkbox => {
            checkbox.addEventListener('change', updateSubmitButton);
        });

        // 重設表單
        function resetForm() {
            const form = document.getElementById('uploadForm');
            const label = document.querySelector('.file-input-label');
            const submitBtn = document.getElementById('submitBtn');
            const downloadBtn = document.getElementById('downloadBtn');
            
            form.reset();
            label.textContent = '選擇影音檔';
            label.classList.remove('has-file');
            submitBtn.disabled = true;
            submitBtn.classList.remove('active');
            downloadBtn.disabled = true;
            downloadBtn.classList.remove('active');
            addStatusMessage('請選擇影音檔案並點擊「開始提取」按鈕', 'info');
        }

        document.getElementById('uploadForm').onsubmit = function(e) {
            e.preventDefault();
            
            const submitBtn = document.getElementById('submitBtn');
            const downloadBtn = document.getElementById('downloadBtn');
            
            submitBtn.disabled = true;
            submitBtn.classList.remove('active');
            downloadBtn.disabled = true;
            downloadBtn.classList.remove('active');
            
            const formData = new FormData(this);
            
            addStatusMessage('開始處理檔案...', 'info');
            
            fetch('/process', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    pollStatus(data.task_id);
                } else {
                    addStatusMessage('錯誤：' + data.error, 'error');
                    updateSubmitButton();
                }
            })
            .catch(error => {
                addStatusMessage('錯誤：' + error, 'error');
                updateSubmitButton();
            });
        };
        
        function pollStatus(taskId) {
            const submitBtn = document.getElementById('submitBtn');
            const downloadBtn = document.getElementById('downloadBtn');
            
            fetch('/status/' + taskId)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'processing') {
                    addStatusMessage(data.message, 'info');
                    setTimeout(() => pollStatus(taskId), 1000);
                } else if (data.status === 'completed') {
                    addStatusMessage('處理完成！點擊「下載字幕檔」下載，或選擇新的檔案處理', 'success');
                    updateSubmitButton();
                    downloadBtn.disabled = false;
                    downloadBtn.classList.add('active');
                    downloadBtn.onclick = function() {
                        this.disabled = true;
                        this.classList.remove('active');
                        window.location.href = '/download/' + taskId;
                        setTimeout(resetForm, 1000);
                    };
                } else if (data.status === 'error') {
                    addStatusMessage('錯誤：' + data.error, 'error');
                    updateSubmitButton();
                }
            })
            .catch(error => {
                addStatusMessage('狀態檢查錯誤：' + error, 'error');
                updateSubmitButton();
            });
        }
        
        function addStatusMessage(message, type) {
            const statusArea = document.getElementById('status-area');
            statusArea.innerHTML = '';
            const messageDiv = document.createElement('div');
            messageDiv.className = 'status-message status-' + type;
            messageDiv.textContent = message;
            statusArea.appendChild(messageDiv);
        }
    </script>
</body>
</html>
"""

def check_ffmpeg():
    """檢查 ffmpeg 是否存在於指定路徑"""
    logger.info(f"檢查 ffmpeg 路徑: {FFMPEG_PATH}")
    if not os.path.exists(FFMPEG_PATH):
        raise RuntimeError(
            f"在路徑 {FFMPEG_PATH} 找不到 ffmpeg！\n"
            "請確認 ffmpeg.exe 是否存在於該路徑。"
        )
    logger.info("ffmpeg 檢查通過")

def process_file(task_id, file_path, formats):
    try:
        logger.info(f"開始處理任務 {task_id}")
        logger.info(f"檔案路徑: {file_path}")
        logger.info(f"選擇的格式: {formats}")
        
        processing_tasks[task_id]['status'] = 'processing'
        processing_tasks[task_id]['message'] = '正在檢查檔案...'
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"找不到上傳的檔案：{file_path}")
            
        if not os.path.exists(FFMPEG_PATH):
            raise FileNotFoundError(f"找不到 ffmpeg，請確認 {FFMPEG_PATH} 是否存在")
        
        processing_tasks[task_id]['message'] = '正在轉換音訊...'
        audio_path = os.path.join(UPLOAD_FOLDER, f"{processing_tasks[task_id]['original_filename']}_{task_id}.mp3")
        logger.info(f"準備轉換音訊到: {audio_path}")
        
        try:
            result = subprocess.run([
                FFMPEG_PATH,
                '-i', file_path,
                '-vn',
                '-ar', '16000',
                '-ac', '1',
                '-acodec', 'libmp3lame',
                '-y',
                audio_path
            ], capture_output=True, text=True, check=True)
            logger.info("音訊轉換完成")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"音訊轉換失敗：{e.stderr}")
        
        processing_tasks[task_id]['message'] = '正在提取字幕...'
        logger.info("開始使用 Whisper 提取字幕")
        
        try:
            result = model.transcribe(audio_path, verbose=False)
            logger.info("字幕提取完成")
        except Exception as e:
            raise RuntimeError(f"Whisper 處理失敗：{str(e)}")
        
        processing_tasks[task_id]['message'] = '正在產生輸出檔案...'
        memory_file = io.BytesIO()
        original_filename = processing_tasks[task_id]['original_filename']
        
        processed_segments = merge_short_segments(result['segments'])
        
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fmt in formats:
                content = ''
                if fmt == 'txt':
                    content = '\n'.join(clean_text(segment['text']) for segment in processed_segments)
                elif fmt == 'srt':
                    content = write_srt(result['segments'])
                elif fmt == 'vtt':
                    content = write_vtt(result['segments'])
                elif fmt == 'tsv':
                    content = '開始時間\t結束時間\t文字內容\n'
                    content += '\n'.join(
                        f"{format_timestamp(seg['start'])}\t{format_timestamp(seg['end'])}\t{clean_text(seg['text'])}"
                        for seg in processed_segments
                    )
                elif fmt == 'json':
                    import json
                    clean_result = {
                        'text': '\n'.join(clean_text(segment['text']) for segment in processed_segments),
                        'segments': [{
                            'start': segment['start'],
                            'end': segment['end'],
                            'text': clean_text(segment['text'])
                        } for segment in processed_segments]
                    }
                    content = json.dumps(clean_result, ensure_ascii=False, indent=2)
                
                output_filename = f"{original_filename}_{task_id}.{fmt}"
                zf.writestr(output_filename, content)
                logger.info(f"已生成 {output_filename}")

        # 儲存ZIP檔案
        memory_file.seek(0)
        zip_path = os.path.join(OUTPUT_FOLDER, f"{original_filename}_{task_id}.zip")
        with open(zip_path, 'wb') as f:
            f.write(memory_file.getvalue())
        logger.info(f"ZIP檔案已儲存到: {zip_path}")
        
        # 清理暫存檔
        try:
            logger.info("清理暫存檔")
            os.remove(audio_path)
        except Exception as e:
            logger.warning(f"清理暫存檔失敗：{str(e)}")
        
        processing_tasks[task_id]['status'] = 'completed'
        processing_tasks[task_id]['zip_path'] = zip_path
        logger.info(f"任務 {task_id} 完成")
        
    except Exception as e:
        logger.error(f"處理失敗：{str(e)}")
        logger.error(traceback.format_exc())
        processing_tasks[task_id]['status'] = 'error'
        processing_tasks[task_id]['error'] = str(e)

try:
    check_ffmpeg()
    logger.info("正在載入 Whisper 模型...")
    model = whisper.load_model("base")
    logger.info("Whisper 模型載入成功")
except Exception as e:
    logger.error(f"初始化錯誤：{str(e)}")
    model = None

@app.route('/')
def index():
    return render_template_string(FORM_HTML)

@app.route('/process', methods=['POST'])
def process():
    try:
        if model is None:
            return jsonify({'success': False, 'error': '模型載入失敗，請檢查系統設定'})

        file = request.files['media']
        if not file:
            return jsonify({'success': False, 'error': '沒有檔案'})

        formats = request.form.getlist('formats')
        if not formats:
            return jsonify({'success': False, 'error': '請至少選擇一種輸出格式'})

        task_id = str(uuid.uuid4())
        original_filename = secure_filename(file.filename)
        original_name = os.path.splitext(original_filename)[0]
        file_path = os.path.join(UPLOAD_FOLDER, f"{original_name}_{task_id}")
        file.save(file_path)

        # 初始化任務狀態
        processing_tasks[task_id] = {
            'status': 'processing',
            'message': '開始處理...',
            'file_path': file_path,
            'original_filename': original_name
        }

        # 在背景執行處理
        thread = threading.Thread(
            target=process_file,
            args=(task_id, file_path, formats)
        )
        thread.start()

        return jsonify({
            'success': True,
            'task_id': task_id
        })

    except Exception as e:
        logger.error(f"處理請求時發生錯誤：{str(e)}")
        return jsonify({
            'success': False,
            'error': str(e)
        })

@app.route('/status/<task_id>')
def status(task_id):
    if task_id not in processing_tasks:
        return jsonify({
            'status': 'error',
            'error': '找不到任務'
        })
    
    task = processing_tasks[task_id]
    return jsonify({
        'status': task['status'],
        'message': task.get('message', ''),
        'error': task.get('error', '')
    })

@app.route('/download/<task_id>')
def download(task_id):
    logger.info(f"嘗試下載任務 {task_id}")
    
    if task_id not in processing_tasks:
        logger.error(f"找不到任務 {task_id}")
        return render_template_string("""
            <script>
                alert("找不到任務，請重新上傳檔案處理");
                window.location.href = '/';
            </script>
        """)
    
    task = processing_tasks[task_id]
    if task['status'] != 'completed':
        logger.error(f"任務 {task_id} 尚未完成，目前狀態：{task['status']}")
        return render_template_string("""
            <script>
                alert("檔案尚未處理完成，請稍候再試");
                window.location.href = '/';
            </script>
        """)
    
    try:
        if not os.path.exists(task['zip_path']):
            logger.error(f"找不到ZIP檔案：{task['zip_path']}")
            return render_template_string("""
                <script>
                    alert("找不到輸出檔案，請重新處理");
                    window.location.href = '/';
                </script>
            """)
        
        response = send_file(
            task['zip_path'],
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{task['original_filename']}_{task_id}.zip"
        )
        
        # 設定不快取
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        
        # 下載完成後清理檔案和任務狀態
        try:
            os.remove(task['zip_path'])
            del processing_tasks[task_id]
        except Exception as e:
            logger.warning(f"清理檔案失敗：{str(e)}")
        
        return response
        
    except Exception as e:
        logger.error(f"下載失敗：{str(e)}")
        logger.error(traceback.format_exc())
        return render_template_string("""
            <script>
                alert("下載失敗，請重試");
                window.location.href = '/';
            </script>
        """)

def is_port_in_use(port):
    """檢查端口是否已被使用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return False
        except socket.error:
            return True

if __name__ == '__main__':
    port = 5000
    # 只在端口未被使用時才開啟瀏覽器
    if not is_port_in_use(port):
        webbrowser.open(f'http://127.0.0.1:{port}')
    app.run(debug=True, port=port)
