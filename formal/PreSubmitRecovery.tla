---- MODULE PreSubmitRecovery ----
EXTENDS Naturals

PreSubmit == {"CREATED", "RISK_ACCEPTED"}
Phases == PreSubmit \cup {"ABORTED", "SUBMITTING", "UNKNOWN"}

VARIABLES phase,
          submitReservation,
          submitCalls,
          crashed,
          sessionReconciled

vars == <<phase, submitReservation, submitCalls, crashed, sessionReconciled>>

Init ==
    /\ phase = "CREATED"
    /\ submitReservation = FALSE
    /\ submitCalls = 0
    /\ crashed = FALSE
    /\ sessionReconciled = TRUE

RiskAccept ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "CREATED"
    /\ phase' = "RISK_ACCEPTED"
    /\ UNCHANGED <<submitReservation, submitCalls, crashed, sessionReconciled>>

ReserveSubmit ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "RISK_ACCEPTED"
    /\ ~submitReservation
    /\ submitCalls = 0
    /\ phase' = "SUBMITTING"
    /\ submitReservation' = TRUE
    /\ UNCHANGED <<submitCalls, crashed, sessionReconciled>>

BrokerSubmit ==
    /\ ~crashed
    /\ sessionReconciled
    /\ phase = "SUBMITTING"
    /\ submitReservation
    /\ submitCalls = 0
    /\ submitCalls' = 1
    /\ UNCHANGED <<phase, submitReservation, crashed, sessionReconciled>>

Crash ==
    /\ ~crashed
    /\ crashed' = TRUE
    /\ sessionReconciled' = FALSE
    /\ UNCHANGED <<phase, submitReservation, submitCalls>>

Restart ==
    /\ crashed
    /\ crashed' = FALSE
    /\ phase' = IF phase = "SUBMITTING" THEN "UNKNOWN" ELSE phase
    /\ UNCHANGED <<submitReservation, submitCalls, sessionReconciled>>

AbortPreSubmitOrphan ==
    /\ ~crashed
    /\ ~sessionReconciled
    /\ phase \in PreSubmit
    /\ ~submitReservation
    /\ submitCalls = 0
    /\ phase' = "ABORTED"
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<submitReservation, submitCalls, crashed>>

SettleNonPreSubmitRecovery ==
    /\ ~crashed
    /\ ~sessionReconciled
    /\ phase \notin PreSubmit
    /\ sessionReconciled' = TRUE
    /\ UNCHANGED <<phase, submitReservation, submitCalls, crashed>>

Stutter == UNCHANGED vars

Next ==
    RiskAccept \/ ReserveSubmit \/ BrokerSubmit \/ Crash \/ Restart \/
    AbortPreSubmitOrphan \/ SettleNonPreSubmitRecovery \/ Stutter

Spec ==
    /\ Init
    /\ [][Next]_vars
    /\ SF_vars(Restart)
    /\ SF_vars(AbortPreSubmitOrphan)
    /\ SF_vars(SettleNonPreSubmitRecovery)

TypeOK ==
    /\ phase \in Phases
    /\ submitReservation \in BOOLEAN
    /\ submitCalls \in 0..1
    /\ crashed \in BOOLEAN
    /\ sessionReconciled \in BOOLEAN

AtMostOneSubmit == submitCalls <= 1
SubmitRequiresReservation == submitCalls = 0 \/ submitReservation

AbortedHasNoBrokerSideEffect ==
    phase # "ABORTED" \/ (~submitReservation /\ submitCalls = 0)

AbortedIsTerminalForExecution ==
    phase # "ABORTED" \/ submitCalls = 0

UnreconciledPreSubmitCannotExecute ==
    ~(~sessionReconciled /\ phase \in PreSubmit) \/ submitCalls = 0

ReservationNeverAppearsInAborted ==
    phase # "ABORTED" \/ ~submitReservation

PostReservationCannotAbort ==
    ~submitReservation \/ phase # "ABORTED"

PreSubmitOrphanEventuallyAborts ==
    (~crashed /\ ~sessionReconciled /\ phase \in PreSubmit) ~> (phase = "ABORTED")

====
