# Spectral Analyser

Real-time audio spectrum analyser for the BSc Analog Electronics open day.  
An ESP32 captures audio and streams it over USB serial to a Raspberry Pi, which displays the waveform and FFT spectrum on an HDMI screen. A web interface lets visitors control a built-in function generator from their phone.

```
ESP32 (Olimex ADF)  --USB serial-->  Raspberry Pi  --HDMI-->  TV / monitor
                                           |
                                       port 8080
                                           |
                                       any browser
                                      (phone / laptop)
```

---

## Requirements

**Hardware**
- Raspberry Pi 4 or 5 running Raspberry Pi OS (Bookworm or newer)
- Olimex ESP32-ADF with spectral analyser firmware flashed
- USB cable connecting ESP32 to Pi
- HDMI display

**Software**
- Python 3.10 or newer (included in Raspberry Pi OS Bookworm)
- git (`sudo apt install git` if missing)

---

## Installation

```bash
git clone https://github.com/TomVanGaever-Vives/pi_spectral.git
bash pi_spectral/install.sh
```

That is all. The installer will:

- Create a Python virtual environment and install all dependencies
- Add your user to the `dialout` group for serial port access
- Place a **Spectral Analyser** launch icon on your desktop

> **Note:** If the installer adds you to `dialout` for the first time it will ask you to reboot before the serial port will work.

---

## Starting the analyser

Double-click the **Spectral Analyser** icon on the desktop, or run from a terminal:

```bash
bash pi_spectral/pi-server/run.sh
```

Plug in the ESP32 via USB before starting. The default serial port is `/dev/ttyUSB0` at 460800 baud.

### Options

| Flag | Description |
|------|-------------|
| `--port /dev/ttyAMA0` | Use a different serial port |
| `--baud 115200` | Override baud rate |
| `--udp` | Use WiFi UDP instead of USB serial |
| `--demo` | Run with a synthetic signal (no hardware needed) |
| `--windowed` | Run in a 1280×720 window instead of fullscreen |
| `--fft-size 4096` | Change FFT resolution (default: 2048) |

---

## Web controls

While the analyser is running, open a browser on any device on the same network and go to:

```
http://<pi-ip-address>:8080
```

This opens a mobile-friendly control panel for the ESP32 function generator — set waveform type, frequency, amplitude, and volume for two independent voices.

---

## Project structure

```
pi_spectral/
├── install.sh                        # one-shot installer
├── spectral-analyser.desktop         # desktop launcher (installed by install.sh)
├── ARCHITECTURE_electronics_demo.md  # full system design document
└── pi-server/
    ├── main.py                       # entry point
    ├── serial_handler.py             # UART audio receiver
    ├── udp_handler.py                # WiFi UDP audio receiver
    ├── audio_processor.py            # ring buffer + FFT
    ├── visualizer.py                 # pygame display
    ├── web_server.py                 # FastAPI web controls
    ├── run.sh                        # launch script
    ├── requirements.txt
    └── static/                       # web UI (HTML/JS/CSS)
```