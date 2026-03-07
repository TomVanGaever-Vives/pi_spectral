"""
main.py — entry point for the Pi HDMI audio visualizer.

Usage:
  python main.py                          # live UDP from ESP32 AP
  python main.py --esp-ip 192.168.4.1    # explicit ESP32 IP
  python main.py --demo                  # synthetic signal, no WiFi needed
  python main.py --windowed              # non-fullscreen window (1280×720)
"""

import argparse
import queue
import sys
import threading
import time
import traceback
import logging
import numpy as np

from udp_handler import UdpHandler
from audio_processor import AudioProcessor
from visualizer import Visualizer
from web_server import WebServer

LOG_FILE = "/tmp/spectral.log"

# Log to both stderr AND a file so we can always read the crash after the fact
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_FILE, mode="w"),
    ],
)


def _demo_thread(sample_q: queue.Queue) -> None:
    """Push a synthetic 440 Hz + 880 Hz + noise signal for testing."""
    sr = 48000
    n  = 512
    t  = 0
    while True:
        frame = np.arange(t, t + n, dtype=np.float32)
        sig = (np.sin(2 * np.pi * 440  * frame / sr) * 18000
             + np.sin(2 * np.pi * 880  * frame / sr) *  5000
             + np.sin(2 * np.pi * 1760 * frame / sr) *  2000
             + np.random.randn(n).astype(np.float32)  *   400)
        samples = tuple(sig.astype(np.int16).tolist())
        try:
            sample_q.put_nowait(samples)
        except queue.Full:
            pass
        t += n
        time.sleep(n / sr)


def main() -> None:
    p = argparse.ArgumentParser(description="Spectral Pi HDMI visualizer")
    p.add_argument("--esp-ip",   default="", help="ESP32 IP (auto-discover if empty)")
    p.add_argument("--udp-port", type=int, default=4210, help="UDP port (default: 4210)")
    p.add_argument("--fft-size", type=int, default=2048)
    p.add_argument("--windowed", action="store_true", help="Run in a window (1280×720)")
    p.add_argument("--demo",     action="store_true",  help="Synthetic signal, no WiFi needed")
    p.add_argument("--web-port", type=int, default=8080, help="Web controls port (default: 8080)")
    args = p.parse_args()

    sample_q  = queue.Queue(maxsize=200)
    processor = AudioProcessor(sample_rate=48000, fft_size=args.fft_size)

    if args.demo:
        t = threading.Thread(target=_demo_thread, args=(sample_q,), daemon=True)
        t.start()
        logging.info("Demo mode: synthetic 440/880/1760 Hz signal")
    else:
        udp = UdpHandler(esp_ip=args.esp_ip or None, port=args.udp_port, sample_queue=sample_q)
        udp.start()
        logging.info("UDP receiver started — connecting to %s:%d", args.esp_ip, args.udp_port)

    try:
        web = WebServer(port=args.web_port)
        web.start()
    except Exception:
        logging.critical("CRASH during WebServer startup:\n%s", traceback.format_exc())
        raise

    try:
        vis = Visualizer(fullscreen=not args.windowed)
    except Exception:
        logging.critical("CRASH during Visualizer init:\n%s", traceback.format_exc())
        web.stop()
        raise

    try:
        running = True
        while running:
            if not vis.paused:
                for _ in range(10):
                    try:
                        samples = sample_q.get_nowait()
                        processor.add_samples(samples)
                    except queue.Empty:
                        break

            waveform = (
                processor.get_triggered_waveform(
                    n=vis.n_samples,
                    trigger_level=vis.trigger_level,
                )
                if vis.trigger_mode != "OFF"
                else processor.get_waveform(n=vis.n_samples)
            )
            fft_db   = processor.get_fft_db()
            freqs    = processor.freqs

            status = ""
            if not args.demo:
                s = udp.stats
                status = f"OK:{s['ok']}  CRC:{s['crc_err']}  SEQ:{s['seq_drop']}  Q:{s['dropped']}"

            running = vis.process_events()
            vis.draw(waveform, fft_db, freqs, status=status)

            # Forward function-gen commands from both pygame and web controls
            try:
                all_cmds = vis.get_pending_commands() + web.drain()
            except Exception:
                logging.error("Error draining commands:\n%s", traceback.format_exc())
                all_cmds = []
            for cmd in all_cmds:
                logging.info("CMD → ESP32: %s", cmd)
                if not args.demo:
                    udp.send_command(cmd)

            vis.tick(30)

    except Exception:
        logging.critical("CRASH in main loop:\n%s", traceback.format_exc())
        raise
    finally:
        vis.quit()
        web.stop()
        if not args.demo:
            udp.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.critical("FATAL unhandled exception:\n%s", traceback.format_exc())
        sys.exit(1)
