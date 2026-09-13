from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol

from bigqmt_autotrader.domain import OrderStatus

from .protocol import IngressDisposition, QmtEvent
from .read_model import QmtReadModel, QmtSnapshotView
from .receiver import IngressResult


@dataclass(frozen=True)
class BrokerEvidenceCandidate:
    source: str
    source_event_id: str | None
    account_fingerprint: str
    client_order_id: str
    evidence_type: str
    requested_status: OrderStatus
    filled_quantity: int
    broker_order_id: str | None
    payload: Mapping[str, Any]
    observed_at: datetime


class EvidenceSink(Protocol):
    def ingest_broker_evidence(
        self,
        *,
        source: str,
        source_event_id: str | None,
        account_fingerprint: str,
        client_order_id: str,
        evidence_type: str,
        requested_status: OrderStatus,
        filled_quantity: int,
        broker_order_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        observed_at: datetime | None = None,
    ) -> Any: ...


EvidenceMapper = Callable[[QmtEvent], BrokerEvidenceCandidate | None]


@dataclass(frozen=True)
class HostIngestResult:
    view: QmtSnapshotView | None
    evidence_ingested: bool
    quarantined: bool


class QmtHostIngestion:
    """P3 host ingestion boundary.

    ACCOUNT/POSITION/snapshot facts update the read model. ORDER/DEAL facts are
    never translated to OMS state by guesswork: an explicit calibrated mapper
    must produce a BrokerEvidenceCandidate first. Without one they are retained
    in quarantine for later reconciliation/calibration.
    """

    def __init__(
        self,
        *,
        read_model: QmtReadModel | None = None,
        evidence_sink: EvidenceSink | None = None,
        evidence_mapper: EvidenceMapper | None = None,
        max_quarantine: int = 1024,
    ) -> None:
        if max_quarantine <= 0:
            raise ValueError("max_quarantine must be positive")
        self.read_model = read_model or QmtReadModel()
        self.evidence_sink = evidence_sink
        self.evidence_mapper = evidence_mapper
        self.max_quarantine = max_quarantine
        self.quarantine: list[QmtEvent] = []
        self.quarantine_dropped = 0

    def handle(self, result: IngressResult) -> HostIngestResult:
        if result.disposition is IngressDisposition.DUPLICATE:
            return HostIngestResult(
                view=self.read_model.view,
                evidence_ingested=False,
                quarantined=False,
            )

        view = self.read_model.apply(result)
        event = result.event

        if event.event_type not in {"order", "deal"}:
            return HostIngestResult(view=view, evidence_ingested=False, quarantined=False)

        if self.evidence_sink is None or self.evidence_mapper is None:
            self._quarantine(event)
            return HostIngestResult(view=view, evidence_ingested=False, quarantined=True)

        candidate = self.evidence_mapper(event)
        if candidate is None:
            self._quarantine(event)
            return HostIngestResult(view=view, evidence_ingested=False, quarantined=True)

        if candidate.account_fingerprint != event.account_fingerprint:
            raise ValueError("evidence mapper changed account identity")
        if candidate.source_event_id is None:
            # QMT session + sequence is stable enough for dedup within one bridge
            # session and does not expose a raw broker/account identifier.
            source_event_id = event.session_id + ":" + str(event.sequence)
        else:
            source_event_id = candidate.source_event_id

        self.evidence_sink.ingest_broker_evidence(
            source=candidate.source,
            source_event_id=source_event_id,
            account_fingerprint=candidate.account_fingerprint,
            client_order_id=candidate.client_order_id,
            evidence_type=candidate.evidence_type,
            requested_status=candidate.requested_status,
            filled_quantity=candidate.filled_quantity,
            broker_order_id=candidate.broker_order_id,
            payload=candidate.payload,
            observed_at=candidate.observed_at,
        )
        return HostIngestResult(view=view, evidence_ingested=True, quarantined=False)

    def _quarantine(self, event: QmtEvent) -> None:
        if len(self.quarantine) >= self.max_quarantine:
            del self.quarantine[0]
            self.quarantine_dropped += 1
        self.quarantine.append(event)


def observed_at_from_event(event: QmtEvent) -> datetime:
    return datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=timezone.utc)
