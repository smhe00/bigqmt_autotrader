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
CancelActivePhases == {"ACKNOWLEDGED", "PARTIALLY_FILLED", "CANCEL_PENDING"}
CancelTerminalPhases == {"FILLED", "CANCELLED", "REJECTED"}

VARIABLES phase,
          reservation,
          submitCalls,
          brokerExists,
          crashed,
          sessionReconciled,
          abandonedReservation,
          unknownGate,
          cancelReservation,
          cancelCalls,
          cancelResolved,
          brokerCancelled,
          abandonedCancelReservation

vars == <<phase, reservation, submitCalls, brokerExists, crashed,
          sessionReconciled, abandonedReservation, unknownGate,
          cancelReservation, cancelCalls, cancelResolved,
          brokerCancelled, abandonedCancelReservation>>

Init ==
    /\ phase = "CREATED"
    /\ reservation = FALSE
    /\ submitCalls = 0
    /\ brokerExists = FALSE
    /\ crashed = FALSE
    /\ sessionReconciled = TRUE
    /\ abandonedReservation = FALSE
    /\ unknownGate = FALSE
    /\ cancelReservation = FALSE
    /\ cancelCalls = 0
    /\ cancelResolved = FALSE
    /\ brokerCancelled = FALSE
    /\ abandonedCancelReservation = FALSE

RiskAccept ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "CREATED"
    /\ phase' = "RISK_ACCEPTED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

RiskReject ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "CREATED"
    /\ phase' = "RISK_REJECTED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

ReserveSubmit ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "RISK_ACCEPTED"
    /\ ~reservation
    /\ submitCalls = 0
    /\ phase' = "SUBMITTING"
    /\ reservation' = TRUE
    /\ UNCHANGED <<submitCalls, brokerExists, crashed, sessionReconciled,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

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
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

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
    /\ UNCHANGED <<reservation, crashed, sessionReconciled, abandonedReservation,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

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
    /\ UNCHANGED <<reservation, crashed, sessionReconciled, abandonedReservation,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

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
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

\* Explicit hard-crash window: durable SUBMITTING exists, the broker call has
\* happened, but no ACK/UNKNOWN result has been committed yet.
SubmitCallAcceptedBeforePersist ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = phase
    /\ submitCalls' = 1
    /\ brokerExists' = TRUE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

SubmitCallNotAcceptedBeforePersist ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 0
    /\ phase' = phase
    /\ submitCalls' = 1
    /\ brokerExists' = FALSE
    /\ UNCHANGED <<reservation, crashed, sessionReconciled,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

PersistSubmitAckAfterSideEffect ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 1
    /\ brokerExists
    /\ phase' = "ACKNOWLEDGED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

PersistSubmitUnknownAfterSideEffect ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ reservation
    /\ submitCalls = 1
    /\ phase' = "UNKNOWN"
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

CancelRequest ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"ACKNOWLEDGED", "PARTIALLY_FILLED"}
    /\ ~cancelReservation
    /\ cancelCalls = 0
    /\ phase' = "CANCEL_PENDING"
    /\ cancelReservation' = TRUE
    /\ cancelResolved' = FALSE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelCalls, brokerCancelled, abandonedCancelReservation>>

CancelAcceptedAck ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 0
    /\ ~cancelResolved
    /\ phase' = "CANCELLED"
    /\ cancelCalls' = 1
    /\ cancelResolved' = TRUE
    /\ brokerCancelled' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, abandonedCancelReservation>>

CancelAcceptedResponseLost ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 0
    /\ ~cancelResolved
    /\ phase' = "UNKNOWN"
    /\ cancelCalls' = 1
    /\ brokerCancelled' = TRUE
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, cancelReservation,
                   cancelResolved, abandonedCancelReservation>>

CancelNotAcceptedResponseLost ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 0
    /\ ~cancelResolved
    /\ phase' = "UNKNOWN"
    /\ cancelCalls' = 1
    /\ brokerCancelled' = FALSE
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, cancelReservation,
                   cancelResolved, abandonedCancelReservation>>

\* Same hard-crash window for cancel. The original broker order still exists;
\* brokerCancelled records whether the cancel side effect actually took effect.
CancelCallAcceptedBeforePersist ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 0
    /\ ~cancelResolved
    /\ phase' = phase
    /\ cancelCalls' = 1
    /\ brokerCancelled' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelResolved, abandonedCancelReservation>>

CancelCallNotAcceptedBeforePersist ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 0
    /\ ~cancelResolved
    /\ phase' = phase
    /\ cancelCalls' = 1
    /\ brokerCancelled' = FALSE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelResolved, abandonedCancelReservation>>

PersistCancelAckAfterSideEffect ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 1
    /\ brokerCancelled
    /\ ~cancelResolved
    /\ phase' = "CANCELLED"
    /\ cancelResolved' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, brokerCancelled,
                   abandonedCancelReservation>>

PersistCancelUnknownAfterSideEffect ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase \in {"CANCEL_PENDING", "PARTIALLY_FILLED"}
    /\ cancelReservation
    /\ cancelCalls = 1
    /\ ~cancelResolved
    /\ phase' = "UNKNOWN"
    /\ unknownGate' = TRUE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

PartialFill ==
    /\ ~crashed
    /\ brokerExists
    /\ ~brokerCancelled
    /\ phase \in {"ACKNOWLEDGED", "CANCEL_PENDING"}
    /\ phase' = "PARTIALLY_FILLED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

Fill ==
    /\ ~crashed
    /\ brokerExists
    /\ ~brokerCancelled
    /\ phase \in {"ACKNOWLEDGED", "PARTIALLY_FILLED", "CANCEL_PENDING"}
    /\ phase' = "FILLED"
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, unknownGate,
                   cancelReservation, cancelCalls, cancelResolved,
                   brokerCancelled, abandonedCancelReservation>>

Crash ==
    /\ ~crashed
    /\ crashed' = TRUE
    /\ sessionReconciled' = FALSE
    /\ UNCHANGED <<phase, reservation, submitCalls, brokerExists,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

Restart ==
    /\ crashed
    /\ LET submitAmbiguous == phase = "SUBMITTING"
            cancelAmbiguous == cancelReservation /\ ~cancelResolved /\ phase \in CancelActivePhases
            cancelTerminal == cancelReservation /\ ~cancelResolved /\ phase \in CancelTerminalPhases
       IN /\ crashed' = FALSE
          /\ phase' = IF submitAmbiguous \/ cancelAmbiguous THEN "UNKNOWN" ELSE phase
          /\ unknownGate' = IF submitAmbiguous \/ cancelAmbiguous THEN TRUE ELSE unknownGate
          /\ abandonedReservation' =
                (abandonedReservation \/ (submitAmbiguous /\ submitCalls = 0))
          /\ abandonedCancelReservation' =
                (abandonedCancelReservation \/ (cancelAmbiguous /\ cancelCalls = 0))
          /\ cancelResolved' = IF cancelTerminal THEN TRUE ELSE cancelResolved
          /\ UNCHANGED <<reservation, submitCalls, brokerExists, sessionReconciled,
                         cancelReservation, cancelCalls, brokerCancelled>>

BeginReconcile ==
    /\ ~crashed
    /\ phase = "UNKNOWN"
    /\ phase' = "RECONCILING"
    /\ unknownGate' = FALSE
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   sessionReconciled, abandonedReservation, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

ReconcileFound ==
    /\ ~crashed
    /\ phase = "RECONCILING"
    /\ brokerExists
    /\ phase' = IF brokerCancelled THEN "CANCELLED" ELSE "ACKNOWLEDGED"
    /\ sessionReconciled' = TRUE
    /\ cancelResolved' = IF cancelReservation THEN TRUE ELSE cancelResolved
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, brokerCancelled, abandonedCancelReservation>>

ReconcileNotFound ==
    /\ ~crashed
    /\ phase = "RECONCILING"
    /\ ~brokerExists
    /\ phase' = "MANUAL_REVIEW"
    /\ sessionReconciled' = TRUE
    /\ cancelResolved' = IF cancelReservation THEN TRUE ELSE cancelResolved
    /\ UNCHANGED <<reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, brokerCancelled, abandonedCancelReservation>>

RecoverNoCandidate ==
    /\ ~crashed
    /\ ~sessionReconciled
    /\ phase \notin RecoveryCandidates
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<phase, reservation, submitCalls, brokerExists, crashed,
                   abandonedReservation, unknownGate, cancelReservation,
                   cancelCalls, cancelResolved, brokerCancelled,
                   abandonedCancelReservation>>

Stutter == UNCHANGED vars

Next ==
    RiskAccept \/ RiskReject \/ ReserveSubmit \/
    SubmitAcceptedAck \/ SubmitAcceptedResponseLost \/
    SubmitNotAcceptedResponseLost \/ SubmitRejected \/
    SubmitCallAcceptedBeforePersist \/ SubmitCallNotAcceptedBeforePersist \/
    PersistSubmitAckAfterSideEffect \/ PersistSubmitUnknownAfterSideEffect \/
    CancelRequest \/ CancelAcceptedAck \/ CancelAcceptedResponseLost \/
    CancelNotAcceptedResponseLost \/ CancelCallAcceptedBeforePersist \/
    CancelCallNotAcceptedBeforePersist \/ PersistCancelAckAfterSideEffect \/
    PersistCancelUnknownAfterSideEffect \/ PartialFill \/ Fill \/ Crash \/
    Restart \/ BeginReconcile \/ ReconcileFound \/ ReconcileNotFound \/
    RecoverNoCandidate \/ Stutter

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
    /\ cancelReservation \in BOOLEAN
    /\ cancelCalls \in 0..1
    /\ cancelResolved \in BOOLEAN
    /\ brokerCancelled \in BOOLEAN
    /\ abandonedCancelReservation \in BOOLEAN

AtMostOneSubmit == submitCalls <= 1
SubmitSideEffectRequiresReservation == submitCalls = 0 \/ reservation
BrokerOrderRequiresSubmit == ~brokerExists \/ (reservation /\ submitCalls = 1)
KnownBrokerLifecycleHasBroker == phase \notin BrokerKnownPhases \/ brokerExists
CrashedSessionIsNotReconciled == ~crashed \/ ~sessionReconciled
UnknownMustPassReconcile == ~unknownGate \/ phase = "UNKNOWN"
AbandonedReservationNeverResubmitted == ~abandonedReservation \/ submitCalls = 0
PostSubmitNeverReturnsToRisk ==
    ~(reservation /\ phase \in {"CREATED", "RISK_ACCEPTED"})

AtMostOneCancel == cancelCalls <= 1
CancelSideEffectRequiresReservation == cancelCalls = 0 \/ cancelReservation
BrokerCancelledRequiresCancel == ~brokerCancelled \/ (cancelReservation /\ cancelCalls = 1)
CancelledLifecycleHasBrokerCancel == phase # "CANCELLED" \/ brokerCancelled
AbandonedCancelReservationNeverRecancelled ==
    ~abandonedCancelReservation \/ cancelCalls = 0
ResolvedCancelRequiresReservation == ~cancelResolved \/ cancelReservation

UnknownEventuallyBeginsReconcile ==
    (phase = "UNKNOWN" /\ ~crashed) ~> (phase = "RECONCILING")

ReconcilingEventuallySettles ==
    (phase = "RECONCILING" /\ ~crashed) ~>
        (phase \in {"ACKNOWLEDGED", "CANCELLED", "MANUAL_REVIEW"})

====
