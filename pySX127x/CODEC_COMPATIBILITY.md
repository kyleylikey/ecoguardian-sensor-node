# ChirpStack v4 Codec Compatibility

## Status: ✅ COMPATIBLE

Both `senddata1.py` and `senddata2.py` are **fully compatible** with the ChirpStack v4 decoder.

## JSON Payload Format

### Reading Packets

The scripts send sensor readings in this format:

```json
{
  "type": "reading",
  "nodeID": 1,
  "temp": 25.5,
  "humidity": 60.0,
  "co_ppm": 5.2,
  "latitude": 14.5995,
  "longitude": 120.9842,
  "altitude": 50.0,
  "gps_fix": true
}
```

**Decoder Output:**
```javascript
{
  type: "reading",
  nodeID: 1,
  data: {
    temp_humid: { temperature: 25.5, humidity: 60.0 },
    gas: { co_ppm: 5.2 },
    gps: { latitude: 14.5995, longitude: 120.9842, altitude: 50.0, fix: true }
  }
}
```

### Alert Packets

#### Chainsaw Alert
```json
{
  "type": "alert",
  "nodeID": 1,
  "risk_type": "chainsaw",
  "risk_level": 1,
  "confidence": 85.5
}
```

**Decoder Output:**
```javascript
{
  type: "alert",
  nodeID: 1,
  risk_type: "chainsaw",
  risk_level: 1,
  confidence: 85.5
}
```

#### Gunshots Alert
```json
{
  "type": "alert",
  "nodeID": 1,
  "risk_type": "gunshots",
  "risk_level": 2,
  "confidence": 78.3
}
```

#### Fire Alert
```json
{
  "type": "alert",
  "nodeID": 1,
  "risk_type": "fire",
  "risk_level": 3,
  "confidence": null
}
```

**Decoder Output:**
```javascript
{
  type: "alert",
  nodeID: 1,
  risk_type: "fire",
  risk_level: 3,
  confidence: null
}
```

## Implementation Details

### Function: `prepare_lora_packet_json(data, is_alert=False)`

Location: Lines 313-369 in senddata1.py and lines 313-373 in senddata2.py

This function:
1. Creates JSON packets in the exact format expected by the ChirpStack decoder
2. Handles both reading and alert packet types
3. Properly serializes data using `json.dumps()` with compact formatting
4. Encrypts the payload using LoRaWAN ABP encryption
5. Sends via LoRa radio

### Differences Between Scripts

| Feature | senddata1.py | senddata2.py |
|---------|-------------|-------------|
| DevAddr | 0060276b | 01122765 |
| NwkSKey | 4dad53a6... | 0537ed2c... |
| AppSKey | 249a97f5... | bd3b68fc... |
| nodeID  | 1 | 2 |

**⚠️ Security Note:** The scripts contain LoRaWAN credentials (DevAddr, NwkSKey, AppSKey). These are device-specific keys that should be kept secure. In production deployments:
- Keep these keys confidential
- Use separate keys for each sensor node
- Rotate keys periodically
- Consider using OTAA (Over-The-Air Activation) instead of ABP for better security

## Verification

The codec compatibility has been verified by:
- ✅ Comparing JSON structure with decoder expectations
- ✅ Testing with sample payloads
- ✅ Confirming all required fields are present
- ✅ Validating null value handling
- ✅ Checking JSON serialization format

## Usage

Simply run either script:

```bash
# For node 1
python3 pySX127x/senddata1.py

# For node 2
python3 pySX127x/senddata2.py
```

The scripts will automatically:
1. Read sensor data (temperature, humidity, CO, GPS)
2. Perform audio classification for chainsaw/gunshot detection
3. Create codec-compatible JSON packets
4. Encrypt and send via LoRaWAN

## ChirpStack Configuration

1. Copy the decoder function from the problem statement to ChirpStack
2. Navigate to: Applications → Your App → Device Profiles → Your Profile → Codec
3. Paste the `decodeUplink` function
4. Save and activate

The decoder will automatically parse incoming packets and structure them correctly for the server and dashboard.
