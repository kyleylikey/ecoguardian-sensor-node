import os
import sys
import signal
from edge_impulse_linux.audio import AudioImpulseRunner

# --- Configuration ---
# Your model path (relative to this script's location)
MODEL_PATH = "gunshot-and-chainsaw-detection-70%-accuracy-linux-aarch64-v1.eim"
# The audio device ID for your microphone, based on your input ([6] default)
AUDIO_DEVICE_ID = 6
# Confidence threshold (in percent)
CONFIDENCE_THRESHOLD = 60.0 

runner = None
last_prediction = None # To track the previously reported event

def signal_handler(sig, frame):
    """Gracefully handles Ctrl+C interruption."""
    print('\n[INFO] Interrupted by user. Cleaning up...')
    global runner
    if runner:
        # Stop the AudioImpulseRunner process
        try:
            runner.stop()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

def run_live_inference():
    """
    Runs continuous, real-time audio classification inference using the 
    Edge Impulse SDK's built-in audio capture and classification loop.
    """
    global runner, last_prediction
    
    # Dynamically build the absolute path to the model file using the script's directory
    script_dir = os.path.dirname(os.path.realpath(__file__))
    modelfile_path = os.path.join(script_dir, MODEL_PATH)

    print("--- Starting Live Audio Inference via Edge Impulse SDK ---")
    print(f"--- Model Path: {modelfile_path} ---")
    print(f"--- Audio Device ID: {AUDIO_DEVICE_ID} ---")
    print(f"Confidence Threshold: {CONFIDENCE_THRESHOLD:.1f}%")

    # 1. Check for model file and permissions
    if not os.path.exists(modelfile_path):
        print(f"\n[FATAL] The required model file was not found at: '{modelfile_path}'")
        sys.exit(1)
    if not os.access(modelfile_path, os.X_OK):
        print("\n[CRITICAL] Model file does NOT have executable permission.")
        print(f"Action Required: Run 'chmod +x {MODEL_PATH}' in this directory.")
        sys.exit(1)

    try:
        # 2. Initialize Model Runner using a context manager
        with AudioImpulseRunner(modelfile_path) as runner:
            model_info = runner.init()
            labels = model_info['model_parameters']['labels']
            print(f"\nModel Project: {model_info['project']['owner']}/{model_info['project']['name']}")
            print(f"Model labels: {labels}")

            # 3. Start the continuous classification loop
            # This handles audio capture, normalization, and windowing internally.
            for res, audio in runner.classifier(device_id=AUDIO_DEVICE_ID):
                
                # Check for classification results
                if "classification" not in res["result"].keys():
                    continue
                
                classification_result = res['result']['classification']
                max_confidence = 0.0
                predicted_label = 'Unknown'
                
                # Find the label with the highest confidence
                for label, confidence_val in classification_result.items():
                    if confidence_val > max_confidence:
                        max_confidence = confidence_val
                        predicted_label = label
                
                confidence = max_confidence * 100
                
                # 🛠️ FIX: Safely calculate the current time by summing DSP and Classification time.
                # This prevents KeyError: 'total' if the key is missing.
                dsp_time = res['timing'].get('dsp', 0)
                classification_time = res['timing'].get('classification', 0)
                current_time_ms = dsp_time + classification_time
                
                # 4. Event Reporting 
                is_ignored_class = predicted_label.lower() in ['noise', 'silence']

                if confidence >= CONFIDENCE_THRESHOLD and not is_ignored_class:
                    if predicted_label != last_prediction:
                        # Report a new, high-confidence event
                        print(f"[{current_time_ms:07.0f}ms] ** {predicted_label.upper()} ** (Conf: {confidence:.2f}%)")
                        last_prediction = predicted_label
                elif last_prediction is not None and confidence < CONFIDENCE_THRESHOLD:
                    # Confidence dropped for the previously reported event
                    if not last_prediction.lower() in ['noise', 'silence']:
                        print(f"[{current_time_ms:07.0f}ms] -> Confidence for {last_prediction} dropped below {CONFIDENCE_THRESHOLD:.1f}%...")
                    last_prediction = None
                
    except Exception as e:
        # Catch any unexpected errors that occur outside the classification loop
        print(f"\n[FATAL ERROR] An unexpected error occurred: {e}")
    finally:
        # If the script exits cleanly, cleanup still runs via the context manager
        pass


if __name__ == "__main__":
    run_live_inference()
