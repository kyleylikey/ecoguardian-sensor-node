import subprocess
import os
import time
from datetime import datetime

# --- Configuration ---
# IMPORTANT: Change this to match the output of `arecord -l`
# Format is "plughw:CARD,DEVICE"
# Based on the example, card 2, device 0 would be "plughw:2,0"
AUDIO_DEVICE = "plughw:2,0"

# Audio settings
RECORDINGS_DIR = "recordings"
DURATION = 5  # seconds
SAMPLE_RATE = 44100
# S16_LE = 16-bit Signed Little-Endian, a standard for WAV
AUDIO_FORMAT = "S16_LE"
CHANNELS = 1  # Mono, since it's a single microphone

def record_audio_clip():
    """
    Records a 5-second audio clip using arecord and saves it with a timestamp.
    """
    # Ensure the recordings directory exists
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    # Generate a unique filename with a timestamp
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_filename = f"recording_{timestamp}.wav"
    output_filepath = os.path.join(RECORDINGS_DIR, output_filename)

    print(f"[*] Recording for {DURATION} seconds...")

    # Construct the arecord command
    # -D: Specifies the audio device
    # -d: Duration in seconds
    # -r: Sample rate in Hz
    # -f: Audio format
    # -c: Number of channels
    command = [
        "arecord",
        "-D", AUDIO_DEVICE,
        "-d", str(DURATION),
        "-r", str(SAMPLE_RATE),
        "-f", AUDIO_FORMAT,
        "-c", str(CHANNELS),
        output_filepath
    ]

    try:
        # Execute the command
        subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"[+] Recording saved successfully: {output_filepath}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to record audio.")
        print(f"  - Arecord stderr: {e.stderr}")
        print("  - Please check the AUDIO_DEVICE name and ensure `arecord -l` shows the device.")
    except FileNotFoundError:
        print("[ERROR] `arecord` command not found. Is ALSA installed? (sudo apt install alsa-utils)")

if __name__ == "__main__":
    print("--- SPH0645 Audio Recorder ---")
    print(f"Device: {AUDIO_DEVICE}, Duration: {DURATION}s")
    print("Press Ctrl+C to stop.")

    try:
        while True:
            record_audio_clip()
            # Wait a moment before starting the next recording
            print("Waiting 2 seconds before next recording...")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n[INFO] Recording stopped by user.")
