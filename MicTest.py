import time
import subprocess
import os
import signal
import sys

# --- Configuration ---

# CRITICAL: Update this based on the 'arecord -l' output.
# The output showed: card 1, device 0. So we use "plughw:1,0"
AUDIO_DEVICE = "default" 
DURATION_SECONDS = 5
RECORDINGS_DIR = "recordings"

# --- Setup ---

if not os.path.exists(RECORDINGS_DIR):
    os.makedirs(RECORDINGS_DIR)
    print(f"[INFO] Created directory: {RECORDINGS_DIR}")

def signal_handler(sig, frame):
    """Handle Ctrl+C to stop the loop gracefully."""
    print("\n[INFO] Audio recording stopped by user.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --- Main Recording Loop ---

def record_audio_clip():
    """Records a single audio clip using arecord."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(RECORDINGS_DIR, f"clip_{timestamp}.wav")

    # ALSA `arecord` command for capturing audio
    # -D specifies the device, -f specifies format (S16_LE = 16-bit signed),
    # -r specifies sample rate (44100 Hz), -c specifies channels (1 for mono),
    # -d specifies duration (in seconds)
    command = [
        "arecord",
        "-D", AUDIO_DEVICE,
        "-f", "S32_LE",
        "-r", "16000",
        "-c", "1",
        "-d", str(DURATION_SECONDS),
        filepath
    ]
    
    print(f"[*] Recording for {DURATION_SECONDS} seconds to {filepath}...")

    try:
        # Use subprocess.run for simple command execution
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False, # Don't raise exception on non-zero exit code
            timeout=DURATION_SECONDS + 5 # Add buffer time
        )

        if result.returncode == 0:
            print(f"[SUCCESS] Saved clip to {filepath}")
        else:
            print("[ERROR] Failed to record audio.")
            print(f"  - Arecord stderr: {result.stderr.strip()}")
            print("  - Check permissions (user in 'audio' group) and device name.")
            time.sleep(2) # Pause on error
            
    except subprocess.TimeoutExpired:
        print("[ERROR] Recording command timed out.")
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")

if __name__ == "__main__":
    print("--- SPH0645 Audio Recorder ---")
    print(f"Device: {AUDIO_DEVICE}, Duration: {DURATION_SECONDS}s")
    print("Press Ctrl+C to stop.")
    
    while True:
        record_audio_clip()
        time.sleep(2) # Wait 2 seconds before next recording
