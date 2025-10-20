#!/bin/bash
set -e

# --- Function to Configure I2S Microphone Hardware ---
configure_i2s_mic() {
    echo "--- [HARDWARE] Configuring SPH0645 I2S Microphone (OS Level) ---"

    # Determine the correct path for config.txt based on PiOS version (Bullseye/Bookworm)
    CONFIG_FILE="/boot/config.txt"
    if [ -d "/boot/firmware" ]; then
        CONFIG_FILE="/boot/firmware/config.txt"
    fi

    if [ ! -f "$CONFIG_FILE" ]; then
        echo "[ERROR] Configuration file not found at $CONFIG_FILE. Aborting hardware setup."
        return 1
    fi

    echo "[INFO] Using configuration file: $CONFIG_FILE"

    # 1. Add the Device Tree Overlay (DTO) required for the SPH0645
    DTO_LINE="dtoverlay=googlevoicehat-soundcard"
    if grep -q "$DTO_LINE" "$CONFIG_FILE"; then
        echo "[SKIP] $DTO_LINE already exists in $CONFIG_FILE."
    else
        echo "[ACTION] Adding $DTO_LINE to $CONFIG_FILE..."
        # Add the lines to the end of the config file using tee -a (append)
        echo "" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "# Added by setup.sh for SPH0645 I2S Mic (required for arecord detection)" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "$DTO_LINE" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "[SUCCESS] Configuration line added."
        # Set flag to prompt for reboot
        REBOOT_REQUIRED=true
    fi

    # 2. Add the current user to the 'audio' group for permissions
    if ! id -nG "$USER" | grep -qw "audio"; then
        echo "[ACTION] Adding user $USER to 'audio' group for permission to use mic device."
        sudo usermod -aG audio "$USER"
        REBOOT_REQUIRED=true
    fi
    
    # 3. CONFIGURE ALSA VOLUME CONTROL (NEW STEP)
    configure_alsa_volume_control
    
    echo "--- [HARDWARE] Configuration complete. ---"
}

# --------------------------------------------------------------------------

# --- NEW Function to Create the .asoundrc Volume Control File ---
configure_alsa_volume_control() {
    local ASOUNDRC_FILE="$HOME/.asoundrc"
    
    echo "--- [ALSA] Creating and configuring $ASOUNDRC_FILE for volume control. ---"
    
    # This uses a 'here document' (EOF) to write the multi-line config block
    cat << EOF > "$ASOUNDRC_FILE"
# ====================================================================
# Configuration for SPH0645 Mic to enable Software Volume (softvol)
# Card name updated based on 'arecord -l' output: sndrpigooglevoi
# ====================================================================

# This section makes a reference to the I2S hardware after the DTO loads.
# The card name is now correctly set to 'sndrpigooglevoi'.
pcm.dmic_hw {
    type hw
    card sndrpigooglevoi
    channels 2
    format S32_LE
}

# This is the software volume control (softvol).
# It links to the hardware above (dmic_hw) and creates a control.
pcm.dmic_sv {
    type softvol
    slave.pcm dmic_hw
    control {
        name "Boost Capture Volume"
        card 1
    }
    # These min/max values allow for boosting the low-gain signal
    min_dB -3.0
    max_dB 30.0
}

pcm.!default {
    type plug
    slave.pcm "dmic_sv"
}
EOF

    echo "[SUCCESS] $ASOUNDRC_FILE created/updated with correct card name."
    echo "[INFO] You can now use the new device 'dmic_sv' in your scripts."
    echo "[INFO] To adjust volume, run 'alsamixer', press F6, select 'snd_rpi_googlevoicehat_soundcar', then F4."
}
# --------------------------------------------------------------------------

# --- SCRIPT START ---

# Ensure REBOOT_REQUIRED is initialized
REBOOT_REQUIRED=false 

echo "--- Installing System Dependencies ---"
# Install system dependencies (first time only)
sudo apt update
sudo apt install -y python3-full python3-venv python3-pip libgpiod3 alsa-utils

echo "--- Configuring Hardware and Permissions ---"
configure_i2s_mic

echo "--- Setting Up Python Virtual Environment ---"
# Create virtual environment if missing
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install Python dependencies
pip install --upgrade pip
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
else
    echo "[WARN] requirements.txt not found. Skipping pip install."
fi

# Final message
if [ "$REBOOT_REQUIRED" = true ]; then
    echo "======================================================================"
    echo "⚠️ HARDWARE CONFIGURATION UPDATED. A **REBOOT IS REQUIRED** to load the"
    echo "   I2S microphone driver and update user permissions."
    echo "   Please run: **sudo reboot**"
    echo "======================================================================"
else
    echo "✅ Setup complete. No reboot needed."
    echo "To adjust mic volume: run **alsamixer**, press **F6**, select **'sndrpii2scard'**, then **F4**."
    echo "To run the application: source venv/bin/activate && python main.py"
fi
