"""
main.py — Imladris sidecar entry point.

Runs two concurrent services:
  1. HL7 bridge (MLLP server + Orthanc PACS change watcher) — asyncio
  2. Acquisition loop (MWL poll → auto C-STORE to PACS) — background thread
"""

import asyncio
import logging
import threading

import acquisition_loop
import hl7_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


def _run_acquisition_loop():
    """Run the blocking acquisition loop in a daemon thread."""
    try:
        acquisition_loop.main()
    except Exception as e:
        log.error(f"Acquisition loop crashed: {e}", exc_info=True)


if __name__ == "__main__":
    log.info("Imladris sidecar starting")

    t = threading.Thread(target=_run_acquisition_loop, daemon=True, name="acq-loop")
    t.start()
    log.info("Acquisition loop thread started")

    asyncio.run(hl7_bridge.run_forever())
