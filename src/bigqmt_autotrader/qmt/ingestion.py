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


class CommandResultSink(Protocol):
    def ingest_execution_command_result(
        self,
        *,
        source_event_id: str,
        account_fingerprint: str,
        command_id: str,
        command_type: str,
        client_order_id: str,
        broker_token: str | None,
        result_status: str,
        execution_mode: str,
        live_side_effect: bool,
        payload: Mapping[str, Any] | None = None,
        observed_at: datetime | None = None,
    ) -> Any: ...


EvidenceMapper = Callable[[QmtEvent], BrokerEvidenceCandidate | None]


@dataclass(frozen=True)
class HostIngestResult:
    view: QmtSnapshotView | None
    evidence_ingested: bool
    quarantined: bool
    deduplicated: bool = False
    command_result_ingested: bool = False


class QmtHostIngestion:
    """P3/P4 host ingestion boundary.

    ACCOUNT/POSITION/snapshot facts update the read model. ORDER/DEAL facts are
    never translated to OMS state by guesswork: an explicit calibrated mapper
    must produce a BrokerEvidenceCandidate first. Without one they are retained
    in quarantine for later reconciliation/calibration.

    P4 command_result events are transport/execution-plane evidence, not broker
    lifecycle evidence. When a CommandResultSink is configured they are routed
    to it explicitly; they never pass through the broker EvidenceMapper and
    therefore cannot fabricate ACKNOWLEDGED/FILLED/CANCELLED state.

    Repeated ACCOUNT callbacks with content identical to the current read-model
    account are marked as semantic duplicates. The sequence/timestamp still
    advance through the read model so protocol continuity is never hidden.
    """

    def __init__(
        self,
        *,
        read_model: QmtReadModel | None = None,
        evidence_sink: EvidenceSink | None = None,
        evidence_mapper: EvidenceMapper | None = None,
        command_result_sink: CommandResultSink | None = None,
        max_quarantine: int = 1024,
    ) -> None:
        if max_quarantine <= 0:
            raise ValueError("max_quarantine must be positive")
        self.read_model = read_model or QmtReadModel()
        self.evidence_sink = evidence_sink
        self.evidence_mapper = evidence_mapper
        self.command_result_sink = command_result_sink
        self.max_quarantine = max_quarantine
        self.quarantine: list[QmtEvent] = []
        self.quarantine_dropped = 0
        self.account_semantic_duplicates = 0

    def handle(self, result: IngressResult) -> HostIngestResult:
        if result.disposition is IngressDisposition.DUPLICATE:
            return HostIngestResult(
                view=self.read_model.view,
                evidence_ingested=False,
                quarantined=False,
                deduplicated=True,
            )

        event = result.event
        semantic_duplicate = self._is_repeated_account(event)
        view = self.read_model.apply(result)
        if semantic_duplicate:
            self.account_semantic_duplicates += 1

        if event.event_type == "command_result":
            return self._handle_command_result(event, view)

        if event.event_type not in {"order", "deal"}:
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=False,
                deduplicated=semantic_duplicate,
            )

        if self.evidence_sink is None or self.evidence_mapper is None:
            self._quarantine(event)
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=True,
                deduplicated=False,
            )

        candidate = self.evidence_mapper(event)
        if candidate is None:
            self._quarantine(event)
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=True,
                deduplicated=False,
            )

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
        return HostIngestResult(
            view=view,
            evidence_ingested=True,
            quarantined=False,
            deduplicated=False,
        )

    def _handle_command_result(
        self,
        event: QmtEvent,
        view: QmtSnapshotView | None,
    ) -> HostIngestResult:
        payload = event.payload
        client_order_id = payload.get("client_order_id")

        # REQUEST_SNAPSHOT command results deliberately carry no order identity.
        # They advance protocol/read-model sequence only.
        if client_order_id is None:
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=False,
                command_result_ingested=False,
            )

        if self.command_result_sink is None:
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=False,
                command_result_ingested=False,
            )

        command_id = payload.get("command_id")
        command_type = payload.get("command_type")
        broker_token = payload.get("broker_token")
        result_status = payload.get("result_status")
        execution_mode = payload.get("execution_mode")
        live_side_effect = payload.get("live_side_effect")
        if (
            not isinstance(command_id, str)
            or not isinstance(command_type, str)
            or not isinstance(client_order_id, str)
            or not isinstance(result_status, str)
            or not isinstance(execution_mode, str)
            or not isinstance(live_side_effect, bool)
            or (broker_token is not None and not isinstance(broker_token, str))
        ):
            self._quarantine(event)
            return HostIngestResult(
                view=view,
                evidence_ingested=False,
                quarantined=True,
                command_result_ingested=False,
            )

        self.command_result_sink.ingest_execution_command_result(
            source_event_id=event.session_id + ":" + str(event.sequence),
            account_fingerprint=event.account_fingerprint,
            command_id=command_id,
            command_type=command_type,
            client_order_id=client_order_id,
            broker_token=broker_token,
            result_status=result_status,
            execution_mode=execution_mode,
            live_side_effect=live_side_effect,
            payload=payload,
            observed_at=observed_at_from_event(event),
        )
        return HostIngestResult(
            view=view,
            evidence_ingested=False,
            quarantined=False,
            deduplicated=False,
            command_result_ingested=True,
        )

    def _is_repeated_account(self, event: QmtEvent) -> bool:
        if event.event_type != "account":
            return False
        view = self.read_model.view
        if view is None or len(view.account) != 1:
            return False
        return dict(view.account[0]) == dict(event.payload)

    def _quarantine(self, event: QmtEvent) -> None:
        if len(self.quarantine) >= self.max_quarantine:
            del self.quarantine[0]
            self.quarantine_dropped += 1
        self.quarantine.append(event)


def observed_at_from_event(event: QmtEvent) -> datetime:
    return datetime.fromtimestamp(event.timestamp_ms / 1000.0, tz=timezone.utc)
