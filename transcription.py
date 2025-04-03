# transcription.py
import io
import sys
import re
import traceback
import time
import os
import subprocess

def run_transcription_job(job_id, video_path, language_code, original_filename,
                          model_name, jobs_dict_ref, lock_ref,
                          get_media_duration_func):
    """Performs transcription using Whisper CLI, updating status with the accumulated output."""
    total_duration = None
    process = None
    srt_output_path = None
    output_dir = os.path.join("outputs", job_id)

    try:
        print(f"Job {job_id}: Background thread started (subprocess, accumulating lines) for {original_filename}")

        total_duration = get_media_duration_func(video_path) # עדיין שימושי לדעת
        print(f"DEBUG (Job {job_id}): get_media_duration returned: {total_duration}")

        # --- עדכון ראשוני ---
        with lock_ref:
            initial_progress = "מתחיל תהליך תמלול..." # Or keep the old one
            if job_id in jobs_dict_ref:
                jobs_dict_ref[job_id]['status'] = 'processing'
                # Initialize progress with the starting message
                jobs_dict_ref[job_id]['progress'] = initial_progress + "\n"
                jobs_dict_ref[job_id]['last_line'] = "" # Initialize last_line
            else:
                print(f"WARN (Job {job_id}): Job ID not found in dict at start of thread.")
                return # Exit if job was somehow removed

        print(f"Job {job_id}: Starting transcription via CLI")

        os.makedirs(output_dir, exist_ok=True) # בניית פקודה ויצירת נתיב פלט SRT נכון

        # --- תיקון :שימוש בשם קובץ הקלט הזמני (video_path) לבניית שם ה-SRT ---
        input_basename = os.path.splitext(os.path.basename(video_path))[0]
        srt_filename = f"{input_basename}.srt" # השם ש Whisper CLI-באמת ייצור
        srt_output_path = os.path.join(output_dir, srt_filename)
        print(f"DEBUG (Job {job_id}): Corrected expected SRT output path: {srt_output_path}")

        command = [
            sys.executable, "-m", "whisper",
            video_path,
            "--model", model_name,
            "--output_dir", output_dir,
            "--output_format", "srt",
            "--verbose", "True" # Keep verbose to get line-by-line output
        ]
        if language_code:
            command.extend(["--language", language_code])

        print(f"Job {job_id}: Executing command: {' '.join(command)}")

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, # Capture stderr too
            text=True,
            encoding='utf-8',
            errors='replace',
            bufsize=1 # Line-buffered
        )

        captured_stderr = "" # Initialize stderr accumulator
        line_count = 0

        print(f"DEBUG (Job {job_id}): Starting to iterate over stdout lines...")
        # --- קרא stdout שורה אחר שורה ואגור ב-progress ---
        for output_line in process.stdout:
            line_count += 1
            cleaned_line = output_line.strip() # נקה רווחים לבנים מההתחלה והסוף

            # --- הדפס ללוג הראשי (אולי לא כל שורה) ---
            if line_count % 5 == 0 or cleaned_line.startswith('['): # הדפס כל 5 שורות או אם מתחיל ב- '['
                try:
                   sys.__stdout__.write(f"[Whisper CLI line {line_count}] {cleaned_line}\n")
                   sys.__stdout__.flush()
                except Exception as write_err:
                    print(f"DEBUG: Error writing to stdout: {write_err}")


            # --- עדכן את המילון הגלובלי עם השורה הנקייה ---
            if cleaned_line:
                with lock_ref:
                    if job_id in jobs_dict_ref and jobs_dict_ref[job_id]['status'] == 'processing':
                        # Append the new line to the 'progress' field
                        jobs_dict_ref[job_id]['progress'] += cleaned_line + "\n"
                        # Also update 'last_line' for potential basic display / backward compatibility
                        jobs_dict_ref[job_id]['last_line'] = cleaned_line
                    # else: Job might have been cancelled or errored out already

        print(f"DEBUG (Job {job_id}): Finished iterating over stdout lines (processed {line_count} lines).")

        # --- קרא stderr וסיים את התהליך ---
        # Wait for the process to finish and get stderr and return code
        try:
            # Reading stderr *after* stdout is finished
            captured_stderr = process.stderr.read()
        except Exception as stderr_err:
             print(f"ERROR (Job {job_id}): Exception reading stderr: {stderr_err}")
             captured_stderr = f"Error reading stderr: {stderr_err}"

        return_code = process.wait() # Wait for process to terminate and get code

        if captured_stderr:
            try:
                sys.__stdout__.write(f"\n--- Captured STDERR from CLI (Job {job_id}) ---\n{captured_stderr}\n----------------------------------\n")
                sys.__stdout__.flush()
            except Exception as write_err:
                 print(f"DEBUG: Error writing stderr to stdout: {write_err}")


        print(f"Job {job_id}: Whisper CLI process finished with return code {return_code}")

        # --- בדיקת תוצאה (עם הנתיב המתוקן) ---
        if return_code == 0 and os.path.exists(srt_output_path): # שימוש בנתיב המתוקן
            try:
                with open(srt_output_path, 'r', encoding='utf-8') as f:
                    srt_result_content = f.read()
                print(f"Job {job_id}: Successfully read SRT content from {srt_output_path}")
                # --- עדכון סופי ---
                with lock_ref:
                    if job_id in jobs_dict_ref:
                        jobs_dict_ref[job_id]['status'] = 'complete'
                        jobs_dict_ref[job_id]['result'] = srt_result_content
                        jobs_dict_ref[job_id]['progress'] = 'העיבוד הושלם בהצלחה!' # Final progress message
                        jobs_dict_ref[job_id]['last_line'] = "" # Clear last line
            except Exception as e: # שגיאה בקריאה
                print(f"ERROR: Job {job_id}: Failed to read SRT file ({srt_output_path}): {e}")
                traceback.print_exc()
                # --- עדכן כשגיאה ---
                with lock_ref:
                    if job_id in jobs_dict_ref:
                        jobs_dict_ref[job_id]['status'] = 'error'
                        jobs_dict_ref[job_id]['error_message'] = f"שגיאה בקריאת קובץ התוצאה: {e}"
                        jobs_dict_ref[job_id]['progress'] = 'שגיאה בקריאת קובץ התוצאה.' # Update progress on error
                        jobs_dict_ref[job_id]['last_line'] = "" # Clear last line
        else: # --- התהליך נכשל או קובץ חסר ---
            print(f"ERROR: Job {job_id}: Process failed (code {return_code}) or output file missing ({srt_output_path}).")
            error_output_detail = captured_stderr or "Unknown error"
            # --- עדכן כשגיאה ---
            with lock_ref:
                if job_id in jobs_dict_ref:
                    jobs_dict_ref[job_id]['status'] = 'error'
                    jobs_dict_ref[job_id]['error_message'] = f"שגיאה בתהליך התמלול (קוד: {return_code}). פרטים בלוג השרת."
                    # Add stderr snippet if available
                    if error_output_detail != "Unknown error":
                         jobs_dict_ref[job_id]['error_message'] += f" Stderr: {error_output_detail[:200]}" # Limit length
                    jobs_dict_ref[job_id]['progress'] = 'שגיאה בתהליך התמלול.' # Update progress on error
                    jobs_dict_ref[job_id]['last_line'] = "" # Clear last line

    except Exception as e: # שגיאה כללית
        print(f"ERROR: Unhandled exception in job {job_id} thread (File: {original_filename}): {e}")
        traceback.print_exc()
        # --- עדכן כשגיאה ---
        with lock_ref:
            if job_id in jobs_dict_ref:
                jobs_dict_ref[job_id]['status'] = 'error'
                jobs_dict_ref[job_id]['error_message'] = f"אירעה שגיאה פנימית לא צפויה: {e}"
                jobs_dict_ref[job_id]['progress'] = 'שגיאה לא צפויה.' # Update progress on error
                jobs_dict_ref[job_id]['last_line'] = "" # Clear last line

    finally: # --- ניקוי ---
        print(f"DEBUG (Job {job_id}): Entering finally block.")
        # --- ניקוי קובץ קלט ---
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
                print(f"Job {job_id}: Removed temporary input file: {video_path}")
            except Exception as clean_e:
                print(f"Job {job_id}: ERROR cleaning up temp input file {video_path}: {clean_e}")
        # --- ניקוי קובץ פלט ותיקייה (אופציונלי, כדאי להשאיר לדיבאג כרגע) ---
        # if srt_output_path and os.path.exists(srt_output_path):
        #     try:
        #         os.remove(srt_output_path)
        #         print(f"Job {job_id}: Removed temporary output file: {srt_output_path}")
        #     except Exception as clean_e:
        #         print(f"Job {job_id}: ERROR cleaning up temp output file {srt_output_path}: {clean_e}")
        # try:
        #     # Remove directory only if it exists and is empty
        #     if os.path.exists(output_dir) and not os.listdir(output_dir):
        #         os.rmdir(output_dir)
        #         print(f"Job {job_id}: Removed empty temporary output directory: {output_dir}")
        # except Exception as clean_e:
        #     # It's often okay if removing the dir fails (e.g., if SRT is still there)
        #     print(f"Job {job_id}: INFO - Could not remove temp output dir {output_dir}: {clean_e}")

        # --- סגירת תהליך (אם עדיין רץ במקרה חריג) ---
        if process and process.poll() is None: # Check if process is still running
             print(f"Job {job_id}: Terminating lingering subprocess.")
             try:
                 process.terminate() # Try to terminate gracefully
                 process.wait(timeout=2) # Wait a bit
             except subprocess.TimeoutExpired:
                 print(f"Job {job_id}: Subprocess terminate timed out, killing.")
                 process.kill() # Force kill if terminate doesn't work
             except Exception as term_err:
                 print(f"Job {job_id}: Error terminating/killing subprocess: {term_err}")


        print(f"Job {job_id}: Background thread finished.")