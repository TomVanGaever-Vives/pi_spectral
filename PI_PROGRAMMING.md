# Raspberry Pi — Programming Guide

## Overview

The ESP32 acts as a **WiFi access point** and streams microphone audio to the Pi
over UDP. The Pi can also send text commands back to the ESP32 to control the
built-in signal generator (funcgen).

```
┌─────────────────────────────────────────────────────────────────┐
│  ESP32-ADF                                                      │
│  ┌──────────┐   I2S    ┌─────────┐                             │
│  │ funcgen  │─────────▶│ ES8388  │──▶ headphone / LOUT         │
│  └──────────┘          │  codec  │                             │
│  ┌──────────┐   I2S    │         │◀── microphone / LIN         │
│  │ mic task │◀─────────└─────────┘                             │
│  └────┬─────┘                                                   │
│       │ UDP  192.168.4.1:4210                                   │
└───────┼─────────────────────────────────────────────────────────┘
        │  WiFi  (SSID: ESP32-Audio)
┌───────┼─────────────────────────────────────────────────────────┐
│  Pi   ▼                                                         │
│  recv audio packets ──▶ FFT ──▶ spectrum display                │
│  send WAVE / VOLUME commands ──▶ ESP32                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step 1 — Connect the Pi to the ESP32 WiFi AP

| Setting  | Value           |
|----------|-----------------|
| SSID     | `ESP32-Audio`   |
| Password | `spectral2026`  |
| ESP32 IP | `192.168.4.1`   |
| Pi IP    | `192.168.4.2`  (assigned by DHCP) |

Connect from the Pi command line:
```bash
sudo nmcli dev wifi connect "ESP32-Audio" password "spectral2026"
```

Or add to `/etc/wpa_supplicant/wpa_supplicant.conf` for auto-connect:
```
network={
    ssid="ESP32-Audio"
    psk="spectral2026"
}
```

---

## Step 2 — Wake up the audio stream

The ESP32 does **not** know the Pi's IP until the Pi sends the first UDP packet.
Send any command (e.g. `STATUS`) to trigger the stream:

```python
import socket

ESP32_IP = "192.168.4.1"
UDP_PORT = 4210

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))          # listen on same port
sock.sendto(b"STATUS\n", (ESP32_IP, UDP_PORT))  # wake ESP32
```

After this the ESP32 starts sending audio packets continuously.

---

## Step 3 — Receive audio packets

### Packet format (ESP32 → Pi)

```
┌────────┬────────┬─────────┬─────────┬──────────────────┬──────┐
│  0xAA  │  0x55  │ len_lo  │ len_hi  │  PCM samples     │ CRC8 │
│ 1 byte │ 1 byte │ 1 byte  │ 1 byte  │  N × 2 bytes     │1 byte│
└────────┴────────┴─────────┴─────────┴──────────────────┴──────┘
```

- **Sync bytes:** `0xAA 0x55`
- **Length:** 16-bit little-endian byte count of the PCM payload  
  (always `512 × 2 = 1024` bytes = 512 samples)
- **PCM:** 512 × int16, little-endian, mono, 16 kHz
- **CRC8:** CRC-8 (poly 0x07) over the PCM bytes only

### Minimal receive loop

```python
import socket
import struct
import numpy as np

ESP32_IP = "192.168.4.1"
UDP_PORT = 4210
SYNC     = b'\xAA\x55'

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("", UDP_PORT))
sock.sendto(b"STATUS\n", (ESP32_IP, UDP_PORT))  # start stream

while True:
    data, _ = sock.recvfrom(2048)
    if len(data) < 5 or data[:2] != SYNC:
        continue                        # ignore non-audio packets

    n_bytes = struct.unpack_from('<H', data, 2)[0]
    pcm_bytes = data[4 : 4 + n_bytes]
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)  # 512 samples @ 16 kHz
    # --- do FFT / spectrum here ---
```

### CRC verification (optional)

```python
def crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) if (crc & 0x80) else (crc << 1)
            crc &= 0xFF
    return crc

received_crc = data[4 + n_bytes]
if crc8(pcm_bytes) != received_crc:
    print("CRC error — dropped packet")
    continue
```

---

## Step 4 — Send commands (Pi → ESP32)

All commands are plain text, terminated with `\n`.
The ESP32 replies with `ACK:<CMD>\n` or a STATUS string.

### Command reference

| Command | Example | Effect |
|---------|---------|--------|
| `WAVE<N> <TYPE> <FREQ> <AMP>` | `WAVE1 SINE 440 0.8` | Set voice N (1–4). TYPE: SINE, SQUARE, TRIANGLE, SAW. FREQ: 20–20000 Hz. AMP: 0.0–1.0 |
| `STOP<N>` | `STOP1` | Silence voice N |
| `STOP` | `STOP` | Silence all 4 voices |
| `VOLUME <0-100>` | `VOLUME 75` | Set DAC output volume % |
| `CLIP <gain>` | `CLIP 2.0` | Mic digital gain (>1.0 = clipping) |
| `STATUS` | `STATUS` | Query all 4 voices → returns `STATUS:V1=SINE,440.0,0.80;...` |

### Example

```python
def send_cmd(sock, cmd: str):
    sock.sendto((cmd + "\n").encode(), (ESP32_IP, UDP_PORT))

# Two-tone test: 440 Hz + 880 Hz
send_cmd(sock, "WAVE1 SINE 440 0.5")
send_cmd(sock, "WAVE2 SINE 880 0.5")

# Set volume
send_cmd(sock, "VOLUME 80")

# Stop generator
send_cmd(sock, "STOP")
```

---

## Audio parameters

| Parameter | Value |
|-----------|-------|
| Sample rate | 16 000 Hz |
| Bit depth | 16-bit signed integer |
| Channels | Mono |
| Samples per packet | 512 |
| Packet rate | ~31.25 packets/sec |
| Packet size | 1029 bytes (4 header + 1024 PCM + 1 CRC) |
| Useful bandwidth | ≈ 262 kbps |

---

## FFT / Spectrum example

```python
import numpy as np
import matplotlib.pyplot as plt

RATE      = 16000
N_SAMPLES = 512

# Inside receive loop — replace with your plotting/display code:
window  = np.hanning(N_SAMPLES)
fft_mag = np.abs(np.fft.rfft(samples * window))
freqs   = np.fft.rfftfreq(N_SAMPLES, d=1.0 / RATE)

# freqs[i] = frequency in Hz,  fft_mag[i] = magnitude
# Frequency resolution = 16000 / 512 = 31.25 Hz per bin
```

Frequency resolution: **31.25 Hz/bin**  
Maximum frequency: **8 000 Hz** (Nyquist)

---

## Suggested Pi-side architecture

```
recv_thread  ──▶  queue  ──▶  fft_thread  ──▶  display_thread
                                                     │
                                              WebSocket server
                                                     │
                                            browser spectrum UI
```

The UDP receive loop should be its own thread so it never blocks on FFT or
display work. Drop packets rather than block the receiver.
