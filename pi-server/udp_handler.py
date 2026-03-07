"""
udp_handler.py — receives audio packets from the ESP32 over UDP.

The Pi runs as WiFi AP (SSID: Spectral).  The ESP32 connects as a station and
streams audio to the Pi.  The ESP32's IP is learned automatically from the first
incoming packet (DHCP-assigned), or can be set explicitly with --esp-ip.

Packet format (identical to the old serial format):
  0xAA 0x55 | SEQ (uint16 LE) | LENGTH (uint16 LE) | PCM bytes (int16 LE, mono 48 kHz) | CRC8
"""

import socket
import struct
import queue
import threading
import logging
import time

SYNC             = b'\xAA\x55'
MAX_PACKET_BYTES = 4096
KEEPALIVE_S      = 5.0      # seconds between STATUS keepalives


def _crc8(data: bytes) -> int:
    """CRC-8/SMBUS (poly 0x07) — must match ESP32 firmware."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) if (crc & 0x80) else (crc << 1)
            crc &= 0xFF
    return crc


class UdpHandler:
    def __init__(self, esp_ip: str | None = None, port: int = 4210,
                 sample_queue: queue.Queue | None = None):
        self.esp_ip       = esp_ip          # None = auto-discover from first packet
        self.port         = port
        self.sample_queue = sample_queue or queue.Queue(maxsize=200)
        self._running      = False
        self._thread: threading.Thread | None = None
        self._stats        = {"ok": 0, "crc_err": 0, "dropped": 0, "seq_drop": 0}
        self._expected_seq: int | None = None
        self._sock: socket.socket | None = None

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(target=self._loop, daemon=True, name="udp-rx")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def send_command(self, cmd: str) -> None:
        """Send a text command to the ESP32 (Pi → ESP32 direction).
        Thread-safe: may be called from any thread while the receiver is running.
        Silently drops commands if the ESP32 hasn't been discovered yet.
        """
        if self._sock is not None and self.esp_ip is not None:
            self._send(self._sock, (cmd + "\n").encode())

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    # ── receiver loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Large kernel receive buffer reduces drops when the Pi is briefly busy
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)  # 1 MB
            sock.bind(("", self.port))
            sock.settimeout(0.05)   # 50 ms — short enough to detect packet gaps
        except OSError as exc:
            logging.error("Cannot bind UDP :%d — %s", self.port, exc)
            return

        if self.esp_ip:
            logging.info("UDP bound on :%d, ESP32 = %s:%d", self.port, self.esp_ip, self.port)
        else:
            logging.info("UDP bound on :%d, waiting for ESP32 to connect...", self.port)
        self._sock = sock

        last_keepalive = 0.0

        while self._running:
            now = time.monotonic()

            # Keepalive — only send if we know where the ESP32 is
            if self.esp_ip and now - last_keepalive >= KEEPALIVE_S:
                self._send(sock, b"STATUS\n")
                last_keepalive = now

            try:
                data, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError as exc:
                logging.error("UDP recv error: %s", exc)
                break

            # Auto-discover ESP32 IP from first incoming packet
            if self.esp_ip is None:
                self.esp_ip = addr[0]
                logging.info("ESP32 discovered at %s", self.esp_ip)
            elif self.esp_ip != addr[0]:
                # Update if ESP32 got a new DHCP lease
                self.esp_ip = addr[0]

            self._parse(data)

        self._sock = None
        sock.close()
        logging.info("UDP socket closed")

    def _send(self, sock: socket.socket, msg: bytes) -> None:
        try:
            sock.sendto(msg, (self.esp_ip, self.port))
        except OSError as exc:
            logging.warning("UDP send failed: %s", exc)

    def _parse(self, data: bytes) -> None:
        # Header: [0xAA][0x55][seq_lo][seq_hi][len_lo][len_hi]  (6 bytes)
        if len(data) < 7 or data[:2] != SYNC:
            return

        seq     = struct.unpack_from('<H', data, 2)[0]
        n_bytes = struct.unpack_from('<H', data, 4)[0]

        if n_bytes == 0 or n_bytes > MAX_PACKET_BYTES or n_bytes % 2 != 0:
            return
        if len(data) < 6 + n_bytes + 1:
            return

        pcm_bytes = data[6: 6 + n_bytes]
        recv_crc  = data[6 + n_bytes]

        if _crc8(pcm_bytes) != recv_crc:
            self._stats["crc_err"] += 1
            return

        # Sequence gap detection
        if self._expected_seq is not None:
            gap = (seq - self._expected_seq) & 0xFFFF
            if gap > 0:
                self._stats["seq_drop"] += gap
                logging.debug("SEQ gap: expected %d got %d (missing %d)",
                              self._expected_seq, seq, gap)
        self._expected_seq = (seq + 1) & 0xFFFF

        samples = struct.unpack(f"<{n_bytes // 2}h", pcm_bytes)
        self._stats["ok"] += 1

        try:
            self.sample_queue.put_nowait(samples)
        except queue.Full:
            self._stats["dropped"] += 1
