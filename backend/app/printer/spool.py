"""Track a single submitted print job through the Windows spooler queue.

GDI's StartDoc/EndDoc only proves the job entered the spooler — paper-out,
offline, or driver errors after that point go undetected by default. We
locate the job by its document name (set deterministically per print-web
job id) and poll EnumJobs for terminal status bits.

Best-effort: if the job disappears from the queue before we see PRINTED,
we treat that as success (most drivers purge completed jobs immediately).
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass

if sys.platform == "win32":
    import win32print

log = logging.getLogger(__name__)

# JOB_STATUS_* bits (winspool.h). pywin32 doesn't expose these as constants.
_JOB_STATUS_PAUSED = 0x00000001
_JOB_STATUS_ERROR = 0x00000002
_JOB_STATUS_DELETING = 0x00000004
_JOB_STATUS_SPOOLING = 0x00000008
_JOB_STATUS_PRINTING = 0x00000010
_JOB_STATUS_OFFLINE = 0x00000020
_JOB_STATUS_PAPEROUT = 0x00000040
_JOB_STATUS_PRINTED = 0x00000080
_JOB_STATUS_DELETED = 0x00000100
_JOB_STATUS_BLOCKED_DEVQ = 0x00000200
_JOB_STATUS_USER_INTERVENTION = 0x00000400

# Bits that mean "this job is not going to print without help".
_FATAL_BITS = (
    _JOB_STATUS_ERROR
    | _JOB_STATUS_DELETED
    | _JOB_STATUS_DELETING
    | _JOB_STATUS_BLOCKED_DEVQ
)

# Bits that mean "stuck, but recoverable if the operator fixes the printer".
# We surface these in the message but keep waiting until the timeout — manual
# retry is the recovery path per project decision (no auto-retry).
_STUCK_BITS = (
    _JOB_STATUS_OFFLINE
    | _JOB_STATUS_PAPEROUT
    | _JOB_STATUS_PAUSED
    | _JOB_STATUS_USER_INTERVENTION
)


def _decode(status: int) -> str:
    parts = []
    for bit, label in [
        (_JOB_STATUS_ERROR, "ERROR"),
        (_JOB_STATUS_DELETED, "DELETED"),
        (_JOB_STATUS_DELETING, "DELETING"),
        (_JOB_STATUS_BLOCKED_DEVQ, "BLOCKED"),
        (_JOB_STATUS_OFFLINE, "OFFLINE"),
        (_JOB_STATUS_PAPEROUT, "PAPEROUT"),
        (_JOB_STATUS_PAUSED, "PAUSED"),
        (_JOB_STATUS_USER_INTERVENTION, "USER_INTERVENTION"),
        (_JOB_STATUS_PRINTED, "PRINTED"),
        (_JOB_STATUS_PRINTING, "PRINTING"),
        (_JOB_STATUS_SPOOLING, "SPOOLING"),
    ]:
        if status & bit:
            parts.append(label)
    return "|".join(parts) or f"0x{status:08x}"


@dataclass(frozen=True)
class SpoolResult:
    success: bool
    message: str          # human-readable summary for logs / status_message
    last_status: int      # raw bitfield from the last EnumJobs hit (0 if never seen)


def _enum_jobs(printer_name: str) -> list[dict]:
    h = win32print.OpenPrinter(printer_name)
    try:
        # EnumJobs(handle, first_job_index, num_jobs, level=1)
        return list(win32print.EnumJobs(h, 0, 999, 1))
    finally:
        win32print.ClosePrinter(h)


def _find_by_doc(jobs: list[dict], doc_name: str) -> dict | None:
    for j in jobs:
        if j.get("pDocument") == doc_name:
            return j
    return None


def wait_for_completion(
    printer_name: str,
    doc_name: str,
    *,
    timeout_seconds: float = 180.0,
    poll_interval: float = 1.0,
    grace_seconds: float = 5.0,
) -> SpoolResult:
    """Poll the spooler for a job matching doc_name until it succeeds, fails,
    or times out.

    Resolution rules (in order):
      1. Last seen status had a fatal bit (ERROR/DELETED/...) → failure.
      2. Last seen status had PRINTED bit → success.
      3. Job is no longer in the queue and we saw it at least once → success
         (typical fast path: driver purges completed jobs).
      4. Job never appeared in the queue and grace_seconds elapsed → success
         (some drivers spool synchronously inside EndDoc and purge before we
         get a chance to observe it).
      5. timeout_seconds elapsed without resolution → failure with the most
         recent stuck bits in the message.
    """
    if sys.platform != "win32":
        return SpoolResult(True, "non-windows: skipped spool tracking", 0)

    start = time.monotonic()
    seen_at_least_once = False
    last_status = 0
    last_stuck_label = ""

    while True:
        elapsed = time.monotonic() - start
        try:
            jobs = _enum_jobs(printer_name)
        except Exception as e:
            log.warning("EnumJobs failed for %s: %s", printer_name, e)
            jobs = []

        job = _find_by_doc(jobs, doc_name)
        if job is not None:
            seen_at_least_once = True
            last_status = int(job.get("Status", 0))

            if last_status & _FATAL_BITS:
                return SpoolResult(False, f"spooler 보고: {_decode(last_status)}", last_status)

            if last_status & _JOB_STATUS_PRINTED:
                return SpoolResult(True, "PRINTED", last_status)

            if last_status & _STUCK_BITS:
                last_stuck_label = _decode(last_status & _STUCK_BITS)
        else:
            # Job not in queue right now.
            if seen_at_least_once:
                return SpoolResult(True, "queue 비움 (PRINTED 추정)", last_status)
            if elapsed >= grace_seconds:
                return SpoolResult(True, "queue에서 즉시 사라짐 (PRINTED 추정)", 0)

        if elapsed >= timeout_seconds:
            msg = f"타임아웃 {int(timeout_seconds)}s"
            if last_stuck_label:
                msg += f" (마지막 상태: {last_stuck_label})"
            elif last_status:
                msg += f" (마지막 상태: {_decode(last_status)})"
            return SpoolResult(False, msg, last_status)

        time.sleep(poll_interval)
