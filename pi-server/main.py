"""
main.py -- entry point for the Pi HDMI audio visualizer.

Usage:
  python main.py                          # live UART from ESP32 (default /dev/ttyUSB0)
  python main.py --port /dev/ttyAMA0      # explicit serial port
  python main.py --udp                    # use WiFi UDP instead of UART
  python main.py --esp-ip 192.168.4.1    # explicit ESP32 IP (UDP mode)
  python main.py --demo                  # synthetic signal, no hardware needed
  python main.py --windowed              # non-fullscreen window (1280x720)
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
from serial_handler import SerialHandler
from audio_processor import AudioProcessor
from visualizer import Visualizer
from web_server import WebServer

LOG_FILE = "/tmp/spectral.log"

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
    p.add_argument("--port",     default="/dev/ttyUSB0", help="Serial port (default: /dev/ttyUSB0)")
    p.add_argument("--baud",     type=int, default=460800, help="UART baud rate (default: 460800)")
    p.add_argument("--udp",      action="store_true", help="Use WiFi UDP instead of UART")
    p.add_argument("--esp-ip",   default="", help="ESP32 IP for UDP mode (auto-discover if empty)")
    p.add_argument("--udp-port", type=int, default=4210, help="UDP port (default: 4210)")
    p.add_argument("--fft-size", type=int, default=2048)
    p.add_argument("--windowed", action="store_true", help="Run in a window (1280x720)")
    p.add_argument("--demo",     action="store_true", help="Synthetic signal, no hardware needed")
    p.add_argument("--web-port", type=int, default=8080, help="Web controls port (default: 8080)")
    args = p.parse_args()

    sample_q  = queue.Queue(maxsize=200)
    processor = AudioProcessor(sample_rate=48000, fft_size=args.fft_size)

    if args.demo:
        t = threading.Thread(target=_demo_thread, args=(sample_q,), daemon=True)
        t.start()
        logging.info("Demo mode: synthetic 440/880/1760 Hz signal")
        transport = None
    elif args.udp:
        transport = UdpHandler(esp_ip=args.esp_ip or None, port=args.udp_port, sample_queue=sample_q)
        transport.start()
        logging.info("UDP receiver started -- %s:%d", args.esp_ip or "auto", args.udp_port)
    else:
        transport = SerialHandler(port=args.port, baud=args.baud, sample_queue=sample_q)
        transport.start()
        logging.info("Serial receiver started -- %s @ %d baud", args.port, args.baud)

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
            fft_db = processor.get_fft_db()
            freqs  = processor.freqs

            status = ""
            if transport is not None:
                s = transport.stats
                if args.udp:
                    status = f"OK:{s['ok']}  CRC:{s['crc_err']}  SEQ:{s['seq_drop']}  Q:{s['dropped']}"
                else:
                    status = f"OK:{s['ok']}  CRC:{s['crc_err']}  Q:{s['dropped']}"

            running = vis.process_events()
            vis.draw(waveform, fft_db, freqs, status=status)

            try:
                all_cmds = vis.get_pending_commands() + web.drain()
            except Exception:
                logging.error("Error draining commands:\n%s", traceback.format_exc())
                all_cmds = []
            for cmd in all_cmds:
                logging.info("CMD -> ESP32: %s", cmd)
                if args.udp and transport is not None:
                    transport.send_command(cmd)

            vis.tick(30)

    except Exception:
        logging.critical("CRASH in main loop:\n%s", traceback.format_exc())
        raise
    finally:
        vis.quit()
        web.stop()
        if transport is not None:
            transport.stop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.critical("FATAL unhandled exception:\n%s", traceback.format_exc())
        sys.exit(1)