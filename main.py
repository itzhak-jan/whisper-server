# main.py (או server.py)
import whisper
import os
import sys
import subprocess
import uuid
import threading
from threading import Lock
from flask import Flask, request, jsonify
from flask_cors import CORS
import traceback

# ייבוא הפונקציות מהקבצים האחרים
from media_utils import get_media_duration
from transcription import run_transcription_job # ודא שהפונקציה מיובאת נכון

# --- הגדרות ---
MODEL_NAME = "base"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
OUTPUT_FOLDER = "outputs"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- בדיקת ffmpeg ---
#print("Initializing server...")
#print("Checking for ffmpeg/ffprobe...")
try:
    subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True, text=True, encoding='utf-8')
    subprocess.run(["ffprobe", "-version"], check=True, capture_output=True, text=True, encoding='utf-8')
    #print("ffmpeg and ffprobe found.")
except (FileNotFoundError, subprocess.CalledProcessError) as ffmpeg_err:
    #print("=" * 40); print(f"FATAL ERROR: Could not find or run 'ffmpeg'/'ffprobe'.\n{ffmpeg_err}"); print("Please ensure ffmpeg is installed AND its location is in the system's PATH."); print("=" * 40); sys.exit(1)

# --- טעינת מודל Whisper (אופציונלי) ---
#print(f"Loading Whisper model (for potential future use): {MODEL_NAME}...")
whisper_model_object = None
try:
    whisper_model_object = whisper.load_model(MODEL_NAME)
    #print(f"Model '{MODEL_NAME}' loaded into memory successfully (though CLI will load its own).")
except Exception as e:
    #print(f"WARNING: Could not load Whisper model '{MODEL_NAME}' into memory (CLI will still be used).\n{e}")

# --- יצירת אפליקציית Flask ---
app = Flask(__name__)
CORS(app)
#print("Flask app created and CORS enabled.")

# --- ניהול מצב המשימות הגלובלי ---
jobs = {}
jobs_lock = Lock()

# --- נתיב API: התחלת תמלול ---
@app.route('/transcribe', methods=['POST'])
def handle_transcription_request():
    # ... (קוד קבלת קובץ, שפה, יצירת job_id, שמירת קובץ) ...
    # הקפד לאתחל video_path לפני ה-try
    video_path = None
    job_id = None
    original_filename = None

    try:
        # קבלת פרטים וקובץ
        if 'video' not in request.files: return jsonify({"error": "No video file part"}), 400
        file = request.files['video']
        original_filename = file.filename # שמור את השם המקורי
        if file.filename == '': return jsonify({"error": "No selected file"}), 400

        language_code = request.form.get('language', 'auto')
        if language_code == "auto" or not language_code: language_code = None
        #print(f"DEBUG: Requested language code: {language_code}")

        job_id = str(uuid.uuid4())
        _, file_extension = os.path.splitext(original_filename)
        input_filename = f"{job_id}{file_extension}"
        video_path = os.path.join(UPLOAD_FOLDER, input_filename) # הגדרת video_path

        file.save(video_path)
        #print(f"DEBUG: File saved to: {video_path} for Job ID: {job_id}")

        with jobs_lock:
            jobs[job_id] = {
                'status': 'pending', 'progress': 'ממתין בתור...', 'last_line': '',
                'result': None, 'error_message': None, 'filename': original_filename
            }

        thread = threading.Thread(
            target=run_transcription_job,
            args=(job_id, video_path, language_code, original_filename,
                  MODEL_NAME, jobs, jobs_lock, get_media_duration)
        )
        thread.start()
        #print(f"DEBUG: Started background thread (subprocess method) for Job ID: {job_id}")

        return jsonify({"job_id": job_id}), 202

    except Exception as e:
        #print(f"ERROR during request submission for {original_filename or 'unknown file'}: {e}"); traceback.print_exc()
        # --- תיקון כאן ---
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
                #print(f"DEBUG: Cleaned up input file {video_path} after submission error.")
            #except Exception as remove_err:
                #print(f"ERROR: Could not remove input file {video_path} after submission error: {remove_err}")
        # ------------------
        return jsonify({"error": f"Server error during request submission: {e}"}), 500


# --- נתיב API: קבלת סטטוס משימה (כולל שורה אחרונה) ---
@app.route('/status/<job_id>', methods=['GET'])
def get_status(job_id):
    with jobs_lock:
        job = jobs.get(job_id, {}).copy()

    if not job: return jsonify({"error": "Job not found"}), 404

    response_data = {
        "job_id": job_id,
        "status": job.get('status', 'unknown'),
        "progress": job.get('progress', ''),
        "filename": job.get('filename', ''),
        "last_line": job.get('last_line', ''), # <-- השדה הזה מועבר ללקוח
        "srt_content": job.get('result') if job.get('status') == 'complete' else None,
        "error": job.get('error_message') if job.get('status') == 'error' else None
    }
    return jsonify(response_data)

# --- הרצת השרת ---
if __name__ == '__main__':
    #print("Starting Flask development server (using Whisper CLI via subprocess)...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)