import os
import uuid
import json
import subprocess
import io
import zipfile
from datetime import timedelta
import torch
import whisper

TEMP_DIR = "temp_audio"
os.makedirs(TEMP_DIR, exist_ok=True)

model = whisper.load_model("base")

def format_timestamp(seconds, always_include_hours=False):
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
    for i, segment in enumerate(segments, 1):
        output.append(f"{i}")
        output.append(f"{format_timestamp(segment['start'], True)} --> {format_timestamp(segment['end'], True)}")
        output.append(clean_text(segment['text']))
        output.append("")
    return "\n".join(output)

def write_vtt(segments):
    segments = merge_short_segments(segments)
    output = ["WEBVTT", ""]
    for segment in segments:
        output.append(f"{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}")
        output.append(clean_text(segment['text']))
        output.append("")
    return "\n".join(output)

def process_audio(file, formats):
    temp_filename = os.path.join(TEMP_DIR, f"{uuid.uuid4()}.mp3")
    with open(temp_filename, "wb") as f:
        f.write(file.getbuffer())

    # 用 Whisper 轉錄
    result = model.transcribe(temp_filename, fp16=False)

    segments = merge_short_segments(result["segments"])
    outputs = {}

    for fmt in formats:
        if fmt == "txt":
            outputs["txt"] = "\n".join(clean_text(seg["text"]) for seg in segments)
        elif fmt == "srt":
            outputs["srt"] = write_srt(result["segments"])
        elif fmt == "vtt":
            outputs["vtt"] = write_vtt(result["segments"])
        elif fmt == "tsv":
            outputs["tsv"] = "開始時間\t結束時間\t文字內容\n" + "\n".join(
                f"{format_timestamp(seg['start'])}\t{format_timestamp(seg['end'])}\t{clean_text(seg['text'])}" for seg in segments
            )
        elif fmt == "json":
            outputs["json"] = json.dumps({
                "text": "\n".join(clean_text(seg["text"]) for seg in segments),
                "segments": [
                    {"start": seg["start"], "end": seg["end"], "text": clean_text(seg["text"])} for seg in segments
                ]
            }, ensure_ascii=False, indent=2)

    os.remove(temp_filename)
    return outputs

def create_zip_file(outputs, filename_prefix):
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fmt, content in outputs.items():
            zf.writestr(f"{filename_prefix}.{fmt}", content)
    memory_file.seek(0)
    return memory_file
