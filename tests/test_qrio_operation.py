from datetime import datetime, timezone

import pytest

import hedp.adapters.qrio as qrio_read_api
from hedp.adapters.qrio import LockPosition
from hedp.adapters.qrio.operation import (
    DispatchStatus,
    OperationOutcome,
    QrioCommand,
    QrioJobStatus,
    QrioOperationAdapter,
    QrioOperationTimeout,
    QrioOperationTransportError,
    QrioOperationRequest,
    QrioReadbackError,
    QrioVendorReceipt,
    VerificationStatus,
)
from hedp.adapters.qrio.models import LockStatus
from hedp.observations import ObservationTime, ObservedValue, Quality


NOW = datetime(2026, 7, 26, 1, 0, tzinfo=timezone.utc)
TIME = ObservationTime(
    observed_at="2026-07-26T01:00:00+00:00",
    received_at="2026-07-26T01:00:00+00:00",
)


class FakeTransport:
    def __init__(self, receipt=None, error=None):
        self.receipt = receipt or QrioVendorReceipt(DispatchStatus.ACCEPTED)
        self.error = error
        self.calls = []

    def dispatch(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.receipt


class FakeReader:
    def __init__(self, position=LockPosition.LOCKED, error=None):
        self.position = position
        self.error = error
        self.calls = []

    def status(self):
        self.calls.append(True)
        if self.error:
            raise self.error
        return LockStatus(
            target_ref="entrance-lock",
            position=ObservedValue(self.position, Quality.GOOD),
            time=TIME,
        )


class FakeJobChecker:
    def __init__(self, status):
        self.status = status
        self.calls = []

    def check(self, vendor_reference):
        self.calls.append(vendor_reference)
        return self.status


def request(command=QrioCommand.LOCK):
    return QrioOperationRequest(
        operation_id="op-001",
        target_alias="entrance-lock",
        command=command,
        requested_at=NOW,
    )


def test_read_only_package_does_not_export_operation_adapter():
    assert not hasattr(qrio_read_api, "QrioOperationAdapter")


def test_lock_dispatches_once_and_requires_matching_readback():
    transport = FakeTransport()
    reader = FakeReader(LockPosition.LOCKED)
    result = QrioOperationAdapter(
        transport, reader, clock=lambda: NOW
    ).execute(request())
    assert len(transport.calls) == 1
    assert reader.calls == [True]
    assert result.receipt.attempt_number == 1
    assert result.verification.status is VerificationStatus.MATCHED
    assert result.outcome is OperationOutcome.COMPLETED


def test_unlock_uses_strict_allowlisted_enum():
    transport = FakeTransport()
    result = QrioOperationAdapter(
        transport, FakeReader(LockPosition.UNLOCKED), clock=lambda: NOW
    ).execute(request(QrioCommand.UNLOCK))
    assert result.outcome is OperationOutcome.COMPLETED
    assert transport.calls[0]["command"] is QrioCommand.UNLOCK
    with pytest.raises(ValueError):
        QrioCommand("open")


def test_rejected_is_failed_without_readback_or_retry():
    transport = FakeTransport(QrioVendorReceipt(DispatchStatus.REJECTED))
    reader = FakeReader()
    result = QrioOperationAdapter(
        transport, reader, clock=lambda: NOW
    ).execute(request())
    assert len(transport.calls) == 1
    assert reader.calls == []
    assert result.outcome is OperationOutcome.FAILED
    assert result.verification.status is VerificationStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "status",
    [
        DispatchStatus.TIMEOUT,
        DispatchStatus.TRANSPORT_ERROR,
        DispatchStatus.UNKNOWN,
    ],
)
def test_ambiguous_receipt_is_unknown_without_readback_or_retry(status):
    transport = FakeTransport(QrioVendorReceipt(status))
    reader = FakeReader()
    result = QrioOperationAdapter(
        transport, reader, clock=lambda: NOW
    ).execute(request())
    assert len(transport.calls) == 1
    assert reader.calls == []
    assert result.outcome is OperationOutcome.UNKNOWN


def test_timeout_exception_is_unknown_receipt_and_never_retried():
    transport = FakeTransport(
        error=QrioOperationTimeout("secret vendor response")
    )
    result = QrioOperationAdapter(
        transport, FakeReader(), clock=lambda: NOW
    ).execute(request())
    assert len(transport.calls) == 1
    assert result.receipt.status is DispatchStatus.TIMEOUT
    assert result.outcome is OperationOutcome.UNKNOWN
    assert "secret" not in repr(result)


def test_transport_exception_is_privacy_safe_unknown_receipt():
    result = QrioOperationAdapter(
        FakeTransport(error=QrioOperationTransportError("private endpoint")),
        FakeReader(),
        clock=lambda: NOW,
    ).execute(request())
    assert result.receipt.status is DispatchStatus.TRANSPORT_ERROR
    assert result.outcome is OperationOutcome.UNKNOWN
    assert "private" not in repr(result)


def test_readback_failure_after_acceptance_is_unknown_without_redispatch():
    transport = FakeTransport()
    reader = FakeReader(error=QrioReadbackError("private endpoint"))
    result = QrioOperationAdapter(
        transport, reader, clock=lambda: NOW
    ).execute(request())
    assert len(transport.calls) == 1
    assert reader.calls == [True]
    assert result.outcome is OperationOutcome.UNKNOWN


def test_readback_mismatch_is_explicit_failure():
    result = QrioOperationAdapter(
        FakeTransport(), FakeReader(LockPosition.UNLOCKED), clock=lambda: NOW
    ).execute(request(QrioCommand.LOCK))
    assert result.verification.status is VerificationStatus.NOT_MATCHED
    assert result.outcome is OperationOutcome.FAILED


def test_job_must_finish_before_status_readback():
    transport = FakeTransport(
        QrioVendorReceipt(
            DispatchStatus.ACCEPTED,
            vendor_reference="job-001",
        )
    )
    reader = FakeReader(LockPosition.LOCKED)
    checker = FakeJobChecker(QrioJobStatus.SUCCEEDED)
    result = QrioOperationAdapter(
        transport,
        reader,
        job_checker=checker,
        clock=lambda: NOW,
    ).execute(request())
    assert checker.calls == ["job-001"]
    assert reader.calls == [True]
    assert result.outcome is OperationOutcome.COMPLETED
    assert not hasattr(result.receipt, "vendor_reference")
    assert "job-001" not in repr(result)


@pytest.mark.parametrize(
    ("job_status", "outcome"),
    [
        (QrioJobStatus.FAILED, OperationOutcome.FAILED),
        (QrioJobStatus.PENDING, OperationOutcome.UNKNOWN),
        (QrioJobStatus.UNAVAILABLE, OperationOutcome.UNKNOWN),
    ],
)
def test_nonterminal_or_failed_job_is_not_redispatched_or_read_back(
    job_status, outcome
):
    transport = FakeTransport(
        QrioVendorReceipt(
            DispatchStatus.ACCEPTED,
            vendor_reference="job-001",
        )
    )
    reader = FakeReader()
    result = QrioOperationAdapter(
        transport,
        reader,
        job_checker=FakeJobChecker(job_status),
        clock=lambda: NOW,
    ).execute(request())
    assert len(transport.calls) == 1
    assert reader.calls == []
    assert result.outcome is outcome


def test_job_reference_without_checker_is_unknown():
    transport = FakeTransport(
        QrioVendorReceipt(
            DispatchStatus.ACCEPTED,
            vendor_reference="job-001",
        )
    )
    reader = FakeReader()
    result = QrioOperationAdapter(
        transport, reader, clock=lambda: NOW
    ).execute(request())
    assert reader.calls == []
    assert result.outcome is OperationOutcome.UNKNOWN


def test_unexpected_transport_bug_is_not_hidden_or_retried():
    transport = FakeTransport(error=RuntimeError("programming bug"))
    with pytest.raises(RuntimeError, match="programming bug"):
        QrioOperationAdapter(
            transport, FakeReader(), clock=lambda: NOW
        ).execute(request())
    assert len(transport.calls) == 1


def test_unexpected_reader_bug_is_not_hidden_or_redispatched():
    transport = FakeTransport()
    with pytest.raises(RuntimeError, match="programming bug"):
        QrioOperationAdapter(
            transport,
            FakeReader(error=RuntimeError("programming bug")),
            clock=lambda: NOW,
        ).execute(request())
    assert len(transport.calls) == 1


def test_references_and_receipt_summary_are_privacy_safe():
    with pytest.raises(ValueError):
        QrioOperationRequest(
            operation_id="op 1",
            target_alias="entrance",
            command=QrioCommand.LOCK,
            requested_at=NOW,
        )
    with pytest.raises(ValueError):
        QrioVendorReceipt(
            DispatchStatus.ACCEPTED,
            vendor_reference="https://private.invalid/job/1",
        )
