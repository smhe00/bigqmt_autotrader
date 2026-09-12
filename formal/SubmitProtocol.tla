---- MODULE SubmitProtocol ----
EXTENDS Naturals

Phases == {
    "CREATED",
    "RISK_REJECTED",
    "RISK_ACCEPTED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCEL_PENDING",
    "CANCELLED",
    "REJECTED",
    "UNKNOWN",
    "RECONCILING",
    "MANUAL_REVIEW"
}

RecoveryCandidates == {"SUBMITTING", "UNKNOWN", "RECONCILING"}
BrokerKnownPhases == {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED"}

VARIABLES phase,
          reservation,
          submitCalls,
          brokerExists,
          crashed,
          sessionReconciled,
          abandonedReservation,
          unknownGate

vars == <<phase, reservation, submitCalls, brokerExists, crashed,
          sessionReconciled, abandonedReservation, unknownGate>>

Init ==
    /\ phase = "CREATED"
    /\ reservation = FALSE
    /\ submitCalls = 0
    /\ brokerExists = FALSE
    /\ crashed = FALSE
    /\ sessionReconciled = TRUE
    /\ abandonedReservation = FALSE
    /\ unknownGate = FALSE

RiskAccept ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "CREATED"
    /\ phase' = "RISK_ACCEPTED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

RiskReject ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "CREATED"
    /\ phase' = "RISK_REJECTED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

ReserveSubmit ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "RISK_ACCEPTED"
    /\ ~reservation
    /\ submitCalls = 0
    /\ phase' = "SUBMITTING"
    /\ reservation' = TRUE
    /\ UNCHANGED <<submitCalls, brokerExists, crashed, sessionReconciled,
                   abandonedReservation, unknownGate>>

SubmitAcceptedAck ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = "ACKNOWLEDGED"
    /\ submitCalls' = 1
    /\ brokerExists' = TRUE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled,
                   abandonedReservation, unknownGate>>

SubmitAcceptedResponseLost ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = "UNKNOWN"
    /\ submitCalls' = 1
    /\ brokerExists' = TRUE
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled, abandonedReservation>>

SubmitNotAcceptedResponseLost ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = "UNKNOWN"
    /\ submitCalls' = 1
    /\ brokerExists' = FALSE
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled, abandonedReservation>>

SubmitRejected ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = "REJECTED"
    /\ submitCalls' = 1
    /\ brokerExists' = FALSE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled,
                   abandonedReservation, unknownGate>>

Crash ==
    /\ ~crashed
    /\ crashed' = TRUE
    /\ sessionReconciled' = FALSE
    /\ UNCHANGED <<phase, reservation, submitCalls, brokerExists,
                   abandonedReservation, unknownGate>>

Restart ==
    /\ crashed
    /\ crashed' = FALSE
    /\ phase' = IF phase = "SUBMITTING" THEN "UNKNOWN" ELSE phase
    /\ unknownGate' = IF phase = "SUBMITTING" THEN TRUE ELSE unknownGate
    /\ abandonedReservation' =
        (abandonedReservation \/ (phase = "SUBMITTING" /\ submitCalls = 0))
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, sessionReconciled>>

BeginReconcile ==
    /\ ~crashed
    /\ phase = "UNKNOWN"
    /\ phase' = "RECONCILING"
    /\ unknownGate' = FALSE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation>>

ReconcileFound ==
    /\ ~crashed
    /\ phase = "RECONCILING"
    /\ brokerExists
    /\ phase' = "ACKNOWLEDGED"
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate>>

ReconcileNotFound ==
    /\ ~crashed
    /\ phase = "RECONCILING"
    /\ ~brokerExists
    /\ phase' = "MANUAL_REVIEW"
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate>>

RecoverNoCandidate ==
    /\ ~crashed
    /\ ~sessionReconciled
    /\ phase \notin RecoveryCandidates
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<phase, reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate>>

CancelRequest ==
    /\ ~crashed
    /\ phase \in {"ACKNOWLEDGED", "PARTIALLY_FILLED"}
    /\ phase' = "CANCEL_PENDING"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

CancelAck ==
    /\ ~crashed
    /\ phase = "CANCEL_PENDING"
    /\ phase' = "CANCELLED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

CancelOutcomeUnknown ==
    /\ ~crashed
    /\ phase = "CANCEL_PENDING"
    /\ phase' = "UNKNOWN"
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation>>

PartialFill ==
    /\ ~crashed
    /\ phase \in {"ACKNOWLEDGED", "CANCEL_PENDING"}
    /\ phase' = "PARTIALLY_FILLED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

Fill ==
    /\ ~crashed
    /\ phase \in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "CANCEL_PENDING"}
    /\ phase' = "FILLED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate>>

Stutter == UNCHANGED vars

Next ==
    RiskAccept \/ RiskReject \/ ReserveSubmit \/
    SubmitAcceptedAck \/ SubmitAcceptedResponseLost \/
    SubmitNotAcceptedResponseLost \/ SubmitRejected \/
    Crash \/ Restart \/ BeginReconcile \/ ReconcileFound \/ ReconcileNotFound \/
    RecoverNoCandidate \/ CancelRequest \/ CancelAck \/ CancelOutcomeUnknown \/
    PartialFill \/ Fill \/ Stutter

Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ SF_vars(Restart)
    /\ SF_vars(BeginReconcile)
    /\ SF_vars(ReconcileFound)
    /\ SF_vars(ReconcileNotFound)
    /\ SF_vars(RecoverNoCandidate)

TypeOK ==
    /\ phase \in Phases
    /\ reservation \in BOOLEAN
    /\ submitCalls \in 0..1
    /\ brokerExists \in BOOLEAN
    /\ crashed \in BOOLEAN
    /\ sessionReconciled \in BOOLEAN
    /\ abandonedReservation \in BOOLEAN
    /\ unknownGate \in BOOLEAN

AtMostOneSubmit == submitCalls <= 1
SubmitSideEffectRequiresReservation == submitCalls = 0 \/ reservation
BrokerOrderRequiresSubmit == ~brokerExists \/ (reservation /\ submitCalls = 1)
KnownBrokerLifecycleHasBroker == phase \notin BrokerKnownPhases \/ brokerExists
CrashedSessionIsNotReconciled == ~crashed \/ ~sessionReconciled
UnknownMustPassReconcile == ~unknownGate \/ phase = "UNKNOWN"
AbandonedReservationNeverResubmitted == ~abandonedReservation \/ submitCalls = 0
PostSubmitNeverReturnsToRisk ==
    ~(reservation /\ phase \in {"CREATED", "RISK_ACCEPTED"})

UnknownEventuallyBeginsReconcile ==
    (phase = "UNKNOWN" /\ ~crashed) ~> (phase = "RECONCILING")

ReconcilingEventuallySettles ==
    (phase = "RECONCILING" /\ ~crashed) ~>
        (phase \in {"ACKNOWLEDGED", "MANUAL_REVIEW"})

====
