# ChirpStack Codec Quick Reference

## 🎯 Quick Answer

**Q: Are senddata1.py and senddata2.py compatible with the ChirpStack v4 decoder?**

**A: YES! ✅ They are fully compatible. No changes needed.**

## 📋 Quick Facts

- **Format:** JSON (compact serialization)
- **Encoding:** UTF-8 bytes
- **Encryption:** LoRaWAN ABP with AES-128
- **Packet Types:** Reading (sensor data) and Alert (risk detection)

## 📊 Packet Formats

### Reading Packet
```json
{"type":"reading","nodeID":1,"temp":25.5,"humidity":60,"co_ppm":5.2,"latitude":14.5995,"longitude":120.9842,"altitude":50,"gps_fix":true}
```

### Alert Packet
```json
{"type":"alert","nodeID":1,"risk_type":"chainsaw","risk_level":1,"confidence":85.5}
```

## 🔑 Key Differences

| | senddata1.py | senddata2.py |
|---|---|---|
| **nodeID** | 1 | 2 |
| **DevAddr** | 0060276b | 01122765 |
| **Keys** | Different | Different |

## 🚀 Usage

```bash
# Run node 1
python3 pySX127x/senddata1.py

# Run node 2
python3 pySX127x/senddata2.py
```

## 📚 Documentation

For detailed information, see:
- [`CODEC_COMPATIBILITY.md`](./CODEC_COMPATIBILITY.md) - Examples and usage
- [`CODEC_VERIFICATION_REPORT.md`](./CODEC_VERIFICATION_REPORT.md) - Detailed analysis

## ✅ Verified Compatible

- All required fields present
- Correct data types
- Proper null handling
- JSON serialization correct
- Encryption working

**Last verified:** 2025-12-14
