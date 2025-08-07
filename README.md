# Eufy Robovac L60 Integration (Enhanced Fork)

This is a custom integration for Tuya-based Eufy L60 vacuums (T2267) only in Home Assistant. This is a frankensteined version that can be ran alongside damacus/robovac integration if necessary until this model gets fixed there.

### ✅ Key Features
- Full DPS payload mapping (e.g., start, pause, spot clean, fan modes).
- On its own domain.
- Will skip unsupported models found in account to eliminate additional ghost entities.
- Plenty of attributes to monitor and possibly discover new codes with.
- Docker-friendly setup with persistent file handling.

### 🔧 Installation
1. Clone the repo and copy `custom_components/robovacl60`.
2. Restart Home Assistant.
3. Add Eufy RoboVac L60 integration.
4. Enjoy!

### 🛠 Advanced Integration
This fork adds:
- Dedicated domain handling.
- DPS 152/153 decoding.
- Vacuum status tracking.
- Battery level.

Feel free to fork and enhance!
