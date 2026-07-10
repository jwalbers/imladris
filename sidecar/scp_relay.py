"""
scp_relay.py — DICOM C-STORE SCP that relays received instances to AdvaPACS.

Listens for incoming DICOM C-STORE (e.g., Secondary Capture from qure-sim)
and immediately forwards each received instance to the AdvaPACS gateway.

qure-sim → C-STORE → [this SCP] → C-STORE → ADVAPACS_GW:11112

Environment variables
---------------------
SCP_AE             IML_CR_01
SCP_PORT           4242
ADVAPACS_GW_HOST   host.docker.internal
ADVAPACS_GW_PORT   11112
ADVAPACS_GW_AE     ADVAPACS_GW
"""

import logging
import os
import threading
import time
from collections import OrderedDict

from pynetdicom import AE, StoragePresentationContexts, evt
from pynetdicom.sop_class import Verification

log = logging.getLogger("scp_relay")

SCP_AE           = os.getenv("SCP_AE",            "IML_CR_01")
SCP_PORT         = int(os.getenv("SCP_PORT",       "4242"))
ADVAPACS_GW_HOST = os.getenv("ADVAPACS_GW_HOST",   "host.docker.internal")
ADVAPACS_GW_PORT = int(os.getenv("ADVAPACS_GW_PORT", "11112"))
ADVAPACS_GW_AE   = os.getenv("ADVAPACS_GW_AE",    "ADVAPACS_GW")

# Dedup cache — prevents loop when AdvaPACS routes instances back to this AE.
# Keyed by SOPInstanceUID; value is monotonic timestamp. Entries expire after
# 600 s so a legitimate re-send later still works.
_INSTANCE_TTL = 600
_seen: OrderedDict[str, float] = OrderedDict()
_seen_lock = threading.Lock()


def _already_seen(sop_uid: str) -> bool:
    now = time.monotonic()
    with _seen_lock:
        cutoff = now - _INSTANCE_TTL
        while _seen and next(iter(_seen.values())) < cutoff:
            _seen.popitem(last=False)
        if sop_uid in _seen:
            return True
        _seen[sop_uid] = now
        return False


def _forward(ds) -> None:
    sop_uid = str(getattr(ds, "SOPInstanceUID", ""))
    if _already_seen(sop_uid):
        log.debug(f"Dedup: dropping already-relayed instance {sop_uid[:20]}…")
        return

    ae = AE(ae_title=SCP_AE)
    ae.add_requested_context(ds.SOPClassUID)
    assoc = ae.associate(ADVAPACS_GW_HOST, ADVAPACS_GW_PORT, ae_title=ADVAPACS_GW_AE)
    if not assoc.is_established:
        log.error(f"Cannot connect to {ADVAPACS_GW_AE}@{ADVAPACS_GW_HOST}:{ADVAPACS_GW_PORT}")
        return
    status = assoc.send_c_store(ds)
    assoc.release()
    mod = getattr(ds, "Modality", "?")
    uid = str(getattr(ds, "StudyInstanceUID", "?"))[:24]
    if status and status.Status == 0x0000:
        log.info(f"Relayed {mod} → AdvaPACS  study={uid}…")
    else:
        log.warning(f"Relay C-STORE returned 0x{status.Status:04X}" if status else "Relay C-STORE failed")


def _handle_store(event):
    ds = event.dataset
    ds.file_meta = event.file_meta
    threading.Thread(target=_forward, args=(ds,), daemon=True).start()
    return 0x0000


def main():
    ae = AE(ae_title=SCP_AE)
    ae.supported_contexts = StoragePresentationContexts
    ae.add_supported_context(Verification)
    handlers = [
        (evt.EVT_C_STORE, _handle_store),
        (evt.EVT_C_ECHO,  lambda e: 0x0000),
    ]
    log.info(
        f"DICOM SCP relay: {SCP_AE} :{SCP_PORT} "
        f"→ {ADVAPACS_GW_AE}@{ADVAPACS_GW_HOST}:{ADVAPACS_GW_PORT}"
    )
    ae.start_server(("0.0.0.0", SCP_PORT), block=True, evt_handlers=handlers)
