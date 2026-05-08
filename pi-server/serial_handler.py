"""
serial_handler.py — reads binary audio packets from the Olimex ESP32-ADF.

Packet format (ESP32 → Pi):
  0xAA 0x55  |  LENGTH (uint16 LE)  |  PCM bytes (int16 LE, mono 48kHz)  |  CRC8

Text lines (STATUS: responses) are ignored here; they don't start with 0xAA.
"""

import struct
import queue
import threading
import logging
import serial


SYNC1 = 0xAA
SYNC2 = 0x55
MAX_PACKET_BYTES = 4096   # sanity cap


def _crc8(data: bytes) -> int:
    """CRC-8/SMBUS (polynomial 0x07). Must match ESP32 firmware."""
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) if (crc & 0x80) else (crc << 1)
            crc &= 0xFF
    return crc


class SerialHandler:
    def __init__(self, port: str, baud: int = 460800,
                 sample_queue: queue.Queue | None = None):
        self.port = port
        self.baud = baud
        self.sample_queue = sample_queue or queue.Queue(maxsize=200)
        self._running = False
        self._thread: threading.Thread | None = None
        self._stats = {"ok": 0, "crc_err": 0, "dropped": 0}

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="serial-rx")
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    # ------------------------------------------------------------------
    def _loop(self) -> None:
        try:
            ser = serial.Serial(self.port, self.baud, timeout=1.0)
        except serial.SerialException as exc:
            logging.error("Cannot open %s: %s", self.port, exc)
            return

        logging.info("Serial open: %s @ %d baud", self.port, self.baud)

        while self._running:
            try:
                self._find_sync(ser)

                raw_len = ser.read(2)
                if len(raw_len) < 2:
                    continue
                n_bytes = struct.unpack("<H", raw_len)[0]

                if n_bytes == 0 or n_bytes > MAX_PACKET_BYTES or n_bytes % 2 != 0:
                    continue

                pcm_bytes = ser.read(n_bytes)
                if len(pcm_bytes) < n_bytes:
                    continue

                crc_raw = ser.read(1)
                if not crc_raw:
                    continue

                if crc_raw[0] != _crc8(pcm_bytes):
                    self._stats["crc_err"] += 1
                    logging.debug("CRC mismatch (packet dropped)")
                    continue

                n_samples = n_bytes // 2
                samples = struct.unpack(f"<{n_samples}h", pcm_bytes)

                self._stats["ok"] += 1
                try:
                    self.sample_queue.put_nowait(samples)
                except queue.Full:
                    # Visualizer can't keep up — silently drop oldest implicitly
                    self._stats["dropped"] += 1

            except serial.SerialException as exc:
                logging.error("Serial error: %s — stopping", exc)
                break

        ser.close()
        logging.info("Serial closed")

    def _find_sync(self, ser: serial.Serial) -> None:
        """Consume bytes until 0xAA 0x55 is found."""
        while self._running:
            b = ser.read(1)
            if not b:
                continue
            if b[0] == SYNC1:
                b2 = ser.read(1)
                if b2 and b2[0] == SYNC2:
                    return
