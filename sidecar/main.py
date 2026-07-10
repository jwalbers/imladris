"""
main.py — Imladris sidecar entry point.

Runs five concurrent services:
  1. Order poller     — polls OpenMRS REST, sends ORM^O01 to AdvaPACS via MLLP
  2. FHIR MWL poller  — polls AdvaPACS FHIR ServiceRequest, writes .wl files
  3. Acquisition loop — polls .wl files, C-STOREs studies to AdvaPACS gateway
  4. SCP relay        — DICOM C-STORE SCP; relays SC from qure-sim → AdvaPACS
  5. Console web      — Flask UI for rad-tech worklist + manual image acquisition

  PACS change watcher (HL7 bridge) runs on the main asyncio loop.
"""

import asyncio
import logging
import threading

import acquisition_loop
import fhir_mwl_poller
import hl7_bridge
import modality_console_web
import order_poller
import scp_relay

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
    _run_in_thread("fhir-mwl",        fhir_mwl_poller.main)
    _run_in_thread("acq-loop",        acquisition_loop.main)
    _run_in_thread("scp-relay",       scp_relay.main)
    _run_in_thread("console-web",     modality_console_web.main)

    # PACS watcher runs on the main thread's asyncio loop
    asyncio.run(hl7_bridge.watch_pacs_forever())
