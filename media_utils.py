# media_utils.py
import subprocess
import os
import sys
import traceback # Added for better error printing

# --- פונקציה: קבלת אורך מדיה עם ffprobe ---
def get_media_duration(file_path: str) -> float | None:
    """
    Gets the duration of a media file in seconds using ffprobe.
    Returns None if duration cannot be determined or ffprobe fails.
    """
    if not os.path.exists(file_path):
        print(f"ERROR: File not found for duration check: {file_path}")
        return None
    try:
        command = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        print(f"DEBUG: Running ffprobe: {' '.join(command)}")
        result = subprocess.run(command, capture_output=True, text=True, check=True, encoding='utf-8')
        duration_str = result.stdout.strip()
        if duration_str and duration_str != 'N/A':
            duration = float(duration_str)
            print(f"DEBUG: ffprobe successful. Duration for {file_path}: {duration} seconds")
            return duration
        else:
            print(f"WARNING: ffprobe returned empty or N/A duration for {file_path}. Output: '{duration_str}'")
            return None
    except FileNotFoundError:
        print("ERROR: ffprobe command not found. Make sure ffmpeg (and ffprobe) is installed and in PATH.")
        return None
    except subprocess.CalledProcessError as e:
        print(f"ERROR: ffprobe failed for {file_path}. Return code: {e.returncode}. Error: {e.stderr.strip()}")
        return None
    except ValueError:
        print(f"ERROR: Could not parse ffprobe duration output for {file_path}: '{result.stdout.strip()}'")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error during ffprobe execution for {file_path}: {e}")
        traceback.print_exc()
        return None