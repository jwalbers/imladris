# Issue: Modality Worklist Resilience During Network Outage

## Context

The current MWL pipeline has two sequential hops that both require network connectivity:

1. **OpenMRS → AdvaPACS** (`order_poller.py` sends ORM^O01 via MLLP to the AdvaPACS gateway on port 2576)
2. **AdvaPACS → Modality** (`fhir_mwl_poller.py` polls AdvaPACS FHIR every 30 s and writes `.wl` files)

If the WAN link to AdvaPACS is down — which is exactly when the lab is most dependent on local clinical operations continuing — **both hops fail** and the modality worklist goes empty.

## Failure scenarios to address in policy/process

| Outage type | Effect on MWL | Modality can still acquire? |
|---|---|---|
| WAN down, OpenMRS up | New OpenMRS orders never reach AdvaPACS; FHIR poll fails; `.wl` files stale/empty | Only if `.wl` files pre-date the outage |
| AdvaPACS gateway down (local) | ORM send fails; FHIR poll fails | No |
| OpenMRS down, AdvaPACS up | No new orders enter AdvaPACS; existing `.wl` files remain | Yes, for pre-existing orders |
| Full local network down | Nothing works | No |

## Design options

### A. Direct fallback write (belt + suspenders)
`order_poller.py` sends ORM to AdvaPACS **and** writes a `.wl` file directly via MwlManager.
- Pro: Modality always has a worklist even if AdvaPACS is unreachable.
- Con: Duplicates when both paths succeed (FHIR poller and direct write both create entries). Requires deduplication or a "source" tag on `.wl` filenames to let FHIR poller avoid stepping on direct writes.
- Con: Bypasses the AdvaPACS station-assignment step — staff never see the order in the AdvaPACS console.

### B. Retry queue with local cache
`order_poller.py` queues ORM sends; on gateway failure it writes to a local pending file. When connectivity restores, it drains the queue. `.wl` files are still only written by `fhir_mwl_poller.py`.
- Pro: Orders eventually reach AdvaPACS; no duplicate `.wl` entries.
- Con: During an outage the modality sees no new orders until connectivity restores and the FHIR poll succeeds. Does not help with acquiring on existing orders.

### C. Emergency local worklist mode
Operator-triggered (e.g., a button in the tool cabinet or a env flag): sidecar switches to writing `.wl` files directly from OpenMRS orders, bypassing AdvaPACS entirely. Normal mode resumes when connectivity is confirmed.
- Pro: Clinical operations continue with minimal workflow change.
- Con: Orders placed during outage never appear in AdvaPACS unless a reconciliation step is run post-recovery.

### D. Persist last-known worklist
`fhir_mwl_poller.py` keeps `.wl` files until the order explicitly leaves draft — it does **not** delete them on a failed FHIR poll (current behavior). If the FHIR poll fails, the last-known set of `.wl` files remains, giving the modality its most recent worklist.
- Pro: Cheapest to implement — one `if r.status_code != 200: return owned` guard (already there).
- Con: Stale entries stay until connectivity returns. Completed or cancelled orders are not removed during an outage.

## Questions for clinical operations policy

1. How long is a typical WAN outage at Bophelong? (minutes, hours, days?)
2. Can a rad tech manually enter patient/study info at the modality console when the worklist is empty, or is that workflow not trained?
3. Is it acceptable for an order placed during an outage to be missing from AdvaPACS post-recovery, requiring manual reconciliation?
4. What is the priority: zero-duplicate worklist entries, or zero-missed acquisitions?
5. Are there regulatory/audit requirements that every acquisition must trace to a system-of-record order?

## Recommendation (pending policy answers)

Option D (keep stale `.wl` files on failed FHIR poll) is already implemented and provides a no-cost safety net for short outages. Option C (operator-triggered emergency mode) is the most operationally clean for longer outages. These two can be layered.

Defer A and B until the clinical operations policy defines the acceptable gap between "order placed" and "order visible on modality worklist."
