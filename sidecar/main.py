"""
main.py — Imladris sidecar entry point.

Runs four concurrent services:
  1. Order poller — polls OpenMRS REST API for new radiology orders,
                    creates DICOM worklist entries (blocking thread)
  2. Acquisition loop — polls MWL, auto C-STOREs studies to PACS (blocking thread)
  3. PACS change watcher — watches Orthanc PACS for StableStudy events,
                           sends HL7 ORU^R01 back to OpenMRS (asyncio)
  4. Modality console web — Flask UI for rad-tech worklist + image acquisition
"""

import asyncio
import logging
import threading

import acquisition_loop
import hl7_bridge
import modality_console_web
import order_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


def _run_in_thread(name: str, fn):
    def target():
        try:
            fn()
        except Exception as e:
            log.error(f"{name} crashed: {e}", exc_info=True)
    t = threading.Thread(target=target, daemon=True, name=name)
    t.start()
    return t


if __name__ == "__main__":
    log.info("Imladris sidecar starting")

    _run_in_thread("order-poller",    order_poller.main)
    _run_in_thread("acq-loop",        acquisition_loop.main)
    _run_in_thread("console-web",     modality_console_web.main)

    # PACS watcher runs on the main thread's asyncio loop
    asyncio.run(hl7_bridge.watch_pacs_forever())
