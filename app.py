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
# 使用相對路徑作為基礎路徑以支援雲端部署
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'outputs')
FFMPEG_PATH = 'ffmpeg'  # 在雲端環境中使用系統安裝的 ffmpeg
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

        .file-input-label:hover {
            background-color: rgba(36, 36, 68, 0.8);
            border-color: var(--primary-color);
        }

        .file-input {
            position: absolute;
            left: -9999px;
        }

        .format-options {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin-top: 20px;
        }

        .format-option {
            flex: 1;
            min-width: 100px;
        }

        .format-checkbox {
            display: none;
        }

        .format-label {
            display: block;
            padding: 10px;
            background-color: rgba(36, 36, 68, 0.6);
            color: var(--text-color);
            border: 1px solid var(--border-color);
            border-radius: 5px;
            cursor: pointer;
            text-align: center;
            transition: all 0.3s ease;
        }

        .format-checkbox:checked + .format-label {
            background-color: var(--primary-color);
            border-color: var(--primary-dark);
        }

        .format-label:hover {
            background-color: rgba(36, 36, 68, 0.8);
            border-color: var(--primary-color);
        }

        .submit-btn {
            background-color: var(--primary-color);
            color: var(--text-color);
            border: none;
            padding: 15px 30px;
            border-radius: 5px;
            cursor: pointer;
            width: 100%;
            font-size: 1.2em;
            transition: all 0.3s ease;
        }

        .submit-btn:hover {
            background-color: var(--primary-dark);
        }

        .submit-btn:disabled {
            background-color: #ccc;
            cursor: not-allowed;
        }

        .status-container {
            margin-top: 30px;
            padding: 20px;
            border-radius: 5px;
            background-color: rgba(36, 36, 68, 0.6);
            display: none;
        }

        .status-container.show {
            display: block;
        }

        .status-text {
            margin: 0;
            color: var(--text-color);
            text-align: center;
            font-size: 1.1em;
        }

        .download-btn {
            display: inline-block;
            background-color: var(--primary-color);
            color: var(--text-color);
            text-decoration: none;
            padding: 10px 20px;
            border-radius: 5px;
            margin-top: 15px;
            transition: all 0.3s ease;
        }

        .download-btn:hover {
            background-color: var(--primary-dark);
        }

        .error-text {
            color: #ff6b6b;
            text-align: center;
            margin-top: 10px;
        }

        #selectedFileName {
            margin-top: 10px;
            text-align: center;
            color: var(--text-color);
            font-style: italic;
        }

        .progress-container {
            width: 100%;
            background-color: rgba(255, 255, 255, 0.1);
            border-radius: 5px;
            margin-top: 15px;
            overflow: hidden;
            display: none;
        }

        .progress-bar {
            width: 0%;
            height: 10px;
            background-color: var(--primary-color);
            border-radius: 5px;
            transition: width 0.3s ease;
        }

        @media (max-width: 600px) {
            .container {
                padding: 20px;
            }

            .format-option {
                min-width: calc(50% - 5px);
            }
        }
    </style>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const form = document.getElementById('uploadForm');
            const fileInput = document.getElementById('file');
            const submitBtn = document.getElementById('submitBtn');
            const selectedFileName = document.getElementById('selectedFileName');
            const statusContainer = document.getElementById('statusContainer');
            const statusText = document.getElementById('statusText');
            const progressContainer = document.getElementById('progressContainer');
            const progressBar = document.getElementById('progressBar');
            const downloadBtn = document.getElementById('downloadBtn');
            const errorText = document.getElementById('errorText');
            let taskId = null;

            fileInput.addEventListener('change', function() {
                if (this.files.length > 0) {
                    selectedFileName.textContent = '已選擇檔案：' + this.files[0].name;
                    submitBtn.disabled = false;
                } else {
                    selectedFileName.textContent = '';
                    submitBtn.disabled = true;
                }
            });

            form.addEventListener('submit', async function(e) {
                e.preventDefault();
                
                const formData = new FormData(form);
                const formats = Array.from(document.querySelectorAll('input[name="formats"]:checked')).map(cb => cb.value);
                
                if (formats.length === 0) {
                    alert('請至少選擇一種輸出格式！');
                    return;
                }
                
                formData.delete('formats');
                formats.forEach(format => formData.append('formats', format));

                submitBtn.disabled = true;
                statusContainer.style.display = 'block';
                progressContainer.style.display = 'block';
                statusText.textContent = '正在上傳檔案...';
                errorText.textContent = '';
                progressBar.style.width = '0%';

                try {
                    const response = await fetch('/process', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        taskId = data.task_id;
                        checkStatus();
                    } else {
                        throw new Error(data.error || '上傳失敗');
                    }
                } catch (error) {
                    statusText.textContent = '處理失敗';
                    errorText.textContent = error.message;
                    submitBtn.disabled = false;
                    progressContainer.style.display = 'none';
                }
            });

            async function checkStatus() {
                if (!taskId) return;

                try {
                    const response = await fetch(`/status/${taskId}`);
                    const data = await response.json();

                    if (data.status === 'processing') {
                        statusText.textContent = '正在處理檔案...';
                        progressBar.style.width = '50%';
                        setTimeout(checkStatus, 2000);
                    } else if (data.status === 'completed') {
                        statusText.textContent = '處理完成！';
                        progressBar.style.width = '100%';
                        downloadBtn.href = `/download/${taskId}`;
                        downloadBtn.style.display = 'inline-block';
                        submitBtn.disabled = false;
                    } else if (data.status === 'failed') {
                        throw new Error(data.error || '處理失敗');
                    }
                } catch (error) {
                    statusText.textContent = '處理失敗';
                    errorText.textContent = error.message;
                    submitBtn.disabled = false;
                    progressContainer.style.display = 'none';
                }
            }
        });
    </script>
</head>
<body>
    <div class="container">
        <h2>字幕提取器</h2>
        <form id="uploadForm">
            <div class="form-group">
                <div class="file-input-container">
                    <label for="file" class="file-input-label">
                        點擊選擇影音檔案
                    </label>
                    <input type="file" id="file" name="file" class="file-input" accept="audio/*,video/*" required>
                </div>
                <div id="selectedFileName"></div>
            </div>

            <div class="form-group">
                <label>選擇輸出格式：</label>
                <div class="format-options">
                    <div class="format-option">
                        <input type="checkbox" id="txt" name="formats" value="txt" class="format-checkbox" checked>
                        <label for="txt" class="format-label">TXT</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="srt" name="formats" value="srt" class="format-checkbox" checked>
                        <label for="srt" class="format-label">SRT</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="vtt" name="formats" value="vtt" class="format-checkbox">
                        <label for="vtt" class="format-label">VTT</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="tsv" name="formats" value="tsv" class="format-checkbox">
                        <label for="tsv" class="format-label">TSV</label>
                    </div>
                    <div class="format-option">
                        <input type="checkbox" id="json" name="formats" value="json" class="format-checkbox">
                        <label for="json" class="format-label">JSON</label>
                    </div>
                </div>
            </div>

            <button type="submit" id="submitBtn" class="submit-btn" disabled>開始處理</button>

            <div id="statusContainer" class="status-container">
                <p id="statusText" class="status-text">準備開始處理...</p>
                <div id="progressContainer" class="progress-container">
                    <div id="progressBar" class="progress-bar"></div>
                </div>
                <p id="errorText" class="error-text"></p>
                <div style="text-align: center;">
                    <a id="downloadBtn" class="download-btn" style="display: none;">下載字幕檔案</a>
                </div>
            </div>
        </form>
    </div>
</body>
</html>
"""

def check_ffmpeg():
    """檢查 ffmpeg 是否可用"""
    try:
        subprocess.run([FFMPEG_PATH, '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def process_file(task_id, file_path, formats):
    """處理檔案並生成字幕"""
    try:
        # 建立輸出目錄
        task_output_dir = os.path.join(OUTPUT_FOLDER, task_id)
        os.makedirs(task_output_dir, exist_ok=True)

        # 載入 Whisper 模型
        model = whisper.load_model("base")
        
        # 使用 Whisper 處理
        result = model.transcribe(file_path)
        
        # 生成不同格式的輸出
        outputs = {}
        processed_segments = merge_short_segments(result['segments'])
        
        if 'txt' in formats:
            txt_path = os.path.join(task_output_dir, 'subtitle.txt')
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(clean_text(segment['text']) for segment in processed_segments))
            outputs['txt'] = txt_path
        
        if 'srt' in formats:
            srt_path = os.path.join(task_output_dir, 'subtitle.srt')
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(write_srt(result['segments']))
            outputs['srt'] = srt_path
            
        if 'vtt' in formats:
            vtt_path = os.path.join(task_output_dir, 'subtitle.vtt')
            with open(vtt_path, 'w', encoding='utf-8') as f:
                f.write(write_vtt(result['segments']))
            outputs['vtt'] = vtt_path
            
        if 'tsv' in formats:
            tsv_path = os.path.join(task_output_dir, 'subtitle.tsv')
            with open(tsv_path, 'w', encoding='utf-8') as f:
                f.write('開始時間\t結束時間\t文字內容\n')
                f.write('\n'.join(
                    f"{format_timestamp(seg['start'])}\t{format_timestamp(seg['end'])}\t{clean_text(seg['text'])}"
                    for seg in processed_segments
                ))
            outputs['tsv'] = tsv_path
            
        if 'json' in formats:
            json_path = os.path.join(task_output_dir, 'subtitle.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                clean_result = {
                    'text': '\n'.join(clean_text(segment['text']) for segment in processed_segments),
                    'segments': [{
                        'start': segment['start'],
                        'end': segment['end'],
                        'text': clean_text(segment['text'])
                    } for segment in processed_segments]
                }
                json.dump(clean_result, f, ensure_ascii=False, indent=2)
            outputs['json'] = json_path
        
        # 建立 ZIP 檔案
        zip_path = os.path.join(OUTPUT_FOLDER, f'{task_id}.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for fmt, path in outputs.items():
                zipf.write(path, os.path.basename(path))
        
        # 更新任務狀態
        processing_tasks[task_id]['status'] = 'completed'
        processing_tasks[task_id]['zip_path'] = zip_path
        
        # 清理臨時檔案
        shutil.rmtree(task_output_dir)
        
    except Exception as e:
        logger.error(f"處理檔案時發生錯誤：{str(e)}")
        logger.error(traceback.format_exc())
        processing_tasks[task_id]['status'] = 'failed'
        processing_tasks[task_id]['error'] = str(e)
        
        # 清理臨時檔案
        if os.path.exists(task_output_dir):
            shutil.rmtree(task_output_dir)

@app.route('/')
def index():
    return render_template_string(FORM_HTML)

@app.route('/process', methods=['POST'])
def process():
    if 'file' not in request.files:
        return jsonify({'error': '未選擇檔案'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未選擇檔案'}), 400
    
    formats = request.form.getlist('formats')
    if not formats:
        return jsonify({'error': '未選擇輸出格式'}), 400
    
    # 檢查 ffmpeg 是否可用
    if not check_ffmpeg():
        return jsonify({'error': '找不到 ffmpeg，請確保已正確安裝'}), 500
    
    try:
        # 生成唯一的任務 ID
        task_id = str(uuid.uuid4())
        
        # 儲存上傳的檔案
        filename = secure_filename(file.filename)
        file_path = os.path.join(UPLOAD_FOLDER, f'{task_id}_{filename}')
        file.save(file_path)
        
        # 初始化任務狀態
        processing_tasks[task_id] = {
            'status': 'processing',
            'file_path': file_path,
            'formats': formats
        }
        
        # 在背景執行處理
        thread = threading.Thread(target=process_file, args=(task_id, file_path, formats))
        thread.start()
        
        return jsonify({'task_id': task_id})
        
    except Exception as e:
        logger.error(f"處理上傳檔案時發生錯誤：{str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/status/<task_id>')
def status(task_id):
    if task_id not in processing_tasks:
        return jsonify({'error': '找不到指定的任務'}), 404
    
    task = processing_tasks[task_id]
    response = {'status': task['status']}
    
    if task['status'] == 'failed':
        response['error'] = task.get('error', '未知錯誤')
    
    return jsonify(response)

@app.route('/download/<task_id>')
def download(task_id):
    if task_id not in processing_tasks:
        return jsonify({'error': '找不到指定的任務'}), 404
    
    task = processing_tasks[task_id]
    if task['status'] != 'completed':
        return jsonify({'error': '任務尚未完成'}), 400
    
    if not os.path.exists(task['zip_path']):
        return jsonify({'error': '找不到輸出檔案'}), 404
    
    try:
        return send_file(
            task['zip_path'],
            as_attachment=True,
            download_name='subtitles.zip'
        )
    except Exception as e:
        logger.error(f"下載檔案時發生錯誤：{str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def find_available_port(start_port=5000, max_attempts=100):
    port = start_port
    while is_port_in_use(port) and max_attempts > 0:
        port += 1
        max_attempts -= 1
    return port if not is_port_in_use(port) else None

if __name__ == '__main__':
    # 清理舊的暫存檔案
    if os.path.exists(UPLOAD_FOLDER):
        shutil.rmtree(UPLOAD_FOLDER)
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)
    
    # 重新建立資料夾
    os.makedirs(UPLOAD_FOLDER)
    os.makedirs(OUTPUT_FOLDER)
    
    # 尋找可用的 port
    port = find_available_port()
    if port is None:
        print("無法找到可用的 port")
        sys.exit(1)
    
    # 在瀏覽器中開啟應用程式
    url = f'http://localhost:{port}'
    webbrowser.open(url)
    
    # 啟動應用程式
    app.run(port=port, debug=True)
