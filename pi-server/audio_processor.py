"""
audio_processor.py — thread-safe ring buffer + numpy FFT + oscilloscope trigger.

Callers push int16 sample tuples via add_samples().
The main (render) thread reads get_waveform() / get_triggered_waveform()
and get_fft_db() at any time.
"""

import threading
import numpy as np
from collections import deque


class AudioProcessor:
    def __init__(self, sample_rate: int = 48000, fft_size: int = 2048):
        self.sample_rate = sample_rate
        self.fft_size = fft_size

        # Buffer is large enough for trigger search: 4× a generous display window
        self._buf_max = max(fft_size, 48000)   # ~1 second at 48 kHz
        self._buf: deque[int] = deque(maxlen=self._buf_max)
        self._lock = threading.Lock()

        self._window = np.hanning(fft_size).astype(np.float32)
        self._freqs  = np.fft.rfftfreq(fft_size, 1.0 / sample_rate).astype(np.float32)

    def add_samples(self, samples: tuple) -> None:
        with self._lock:
            self._buf.extend(samples)

    @property
    def freqs(self) -> np.ndarray:
        return self._freqs

    def has_data(self) -> bool:
        with self._lock:
            return len(self._buf) > 0

    def get_waveform(self, n: int = 512) -> np.ndarray:
        """Last n samples normalised to [-1, 1]."""
        with self._lock:
            buf = list(self._buf)

        if not buf:
            return np.zeros(n, dtype=np.float32)

        data = np.array(buf[-n:], dtype=np.float32)
        return data / 32768.0

    def get_triggered_waveform(self, n: int = 512,
                               trigger_level: float = 0.0) -> np.ndarray:
        """Return n samples aligned to a rising-edge trigger crossing.

        Searches backwards from the newest data for a rising-edge crossing
        of *trigger_level* (normalised, -1 to 1).  The trigger point is
        placed ~20% from the left edge so pre-trigger context is visible.

        If no trigger is found, falls back to the newest n samples.

        Returns normalised float32 array of length n.
        """
        with self._lock:
            buf = list(self._buf)

        if len(buf) < n:
            return np.zeros(n, dtype=np.float32)

        data = np.array(buf, dtype=np.float32) / 32768.0

        pre_samples = n // 5          # ~20 % pre-trigger
        search_start = pre_samples    # earliest valid trigger index
        search_end   = len(data) - n + pre_samples  # latest valid

        if search_end <= search_start:
            search_end = len(data) - n
            search_start = 0

        # Search backwards (most recent first) for rising edge crossing
        trig_idx = None
        for i in range(search_end, search_start - 1, -1):
            if i < 1:
                break
            if data[i - 1] <= trigger_level < data[i]:
                trig_idx = i
                break

        if trig_idx is not None:
            start = trig_idx - pre_samples
            return data[start: start + n].copy()

        # No trigger found — fall back to the latest samples
        return data[-n:]

    def get_fft_db(self) -> np.ndarray:
        """FFT magnitude in dB (0 dB = full-scale sine)."""
        with self._lock:
            buf = list(self._buf)

        data = np.zeros(self.fft_size, dtype=np.float32)
        if buf:
            chunk = np.array(buf, dtype=np.float32) / 32768.0
            n = min(len(chunk), self.fft_size)
            data[-n:] = chunk[-n:]

        data *= self._window
        mag = np.abs(np.fft.rfft(data)) / (self.fft_size / 2)
        return (20.0 * np.log10(mag + 1e-10)).astype(np.float32)
