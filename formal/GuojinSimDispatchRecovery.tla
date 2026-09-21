---- MODULE GuojinSimDispatchRecovery ----
EXTENDS Naturals

\* P6-T004-I02 finite abstraction. Reservation and immutable plan are one
\* SQLite commit; filesystem publication happens only afterwards.

OrderStates == {"READY", "RESERVED", "ORPHAN", "MANUAL_REVIEW"}
PlanStates == {"NONE", "PLANNED", "PUBLISHED", "MANUAL_REVIEW"}
SpoolStates == {"ABSENT", "INBOX", "CLAIMED", "PROCESSED", "UNKNOWN"}

VARIABLES order, plan, spool, expired, sideEffectCalls, restartSeen, blindRepublish
vars == <<order, plan, spool, expired, sideEffectCalls, restartSeen, blindRepublish>>

Init ==
    /\ order = "READY" /\ plan = "NONE" /\ spool = "ABSENT"
    /\ expired = FALSE /\ sideEffectCalls = 0
    /\ restartSeen = FALSE /\ blindRepublish = FALSE

AtomicReserveAndPlan ==
    /\ order = "READY" /\ plan = "NONE" /\ spool = "ABSENT"
    /\ order' = "RESERVED" /\ plan' = "PLANNED"
    /\ UNCHANGED <<spool, expired, sideEffectCalls, restartSeen, blindRepublish>>

\* Models a legacy/fault-injected impossible row found at startup.
InjectLegacyOrphan ==
    /\ order = "READY" /\ plan = "NONE" /\ spool = "ABSENT"
    /\ order' = "ORPHAN"
    /\ UNCHANGED <<plan, spool, expired, sideEffectCalls, restartSeen, blindRepublish>>

SweepLegacyOrphan ==
    /\ order = "ORPHAN" /\ plan = "NONE"
    /\ order' = "MANUAL_REVIEW" /\ plan' = "MANUAL_REVIEW"
    /\ restartSeen' = TRUE
    /\ UNCHANGED <<spool, expired, sideEffectCalls, blindRepublish>>

Expire ==
    /\ plan = "PLANNED" /\ spool = "ABSENT"
    /\ expired' = TRUE
    /\ UNCHANGED <<order, plan, spool, sideEffectCalls, restartSeen, blindRepublish>>

ExpirePlannedFailClosed ==
    /\ order = "RESERVED" /\ plan = "PLANNED" /\ spool = "ABSENT" /\ expired
    /\ order' = "MANUAL_REVIEW" /\ plan' = "MANUAL_REVIEW"
    /\ restartSeen' = TRUE
    /\ UNCHANGED <<spool, expired, sideEffectCalls, blindRepublish>>

PublishProvenAbsent ==
    /\ order = "RESERVED" /\ plan = "PLANNED" /\ spool = "ABSENT" /\ ~expired
    /\ plan' = "PUBLISHED" /\ spool' = "INBOX"
    /\ UNCHANGED <<order, expired, sideEffectCalls, restartSeen, blindRepublish>>

Claim ==
    /\ spool = "INBOX" /\ spool' = "CLAIMED"
    /\ UNCHANGED <<order, plan, expired, sideEffectCalls, restartSeen, blindRepublish>>

BrokerCall ==
    /\ spool = "CLAIMED" /\ sideEffectCalls = 0 /\ sideEffectCalls' = 1
    /\ UNCHANGED <<order, plan, spool, expired, restartSeen, blindRepublish>>

Persisted ==
    /\ spool = "CLAIMED" /\ sideEffectCalls = 1 /\ spool' = "PROCESSED"
    /\ UNCHANGED <<order, plan, expired, sideEffectCalls, restartSeen, blindRepublish>>

ClaimCrash ==
    /\ spool = "CLAIMED" /\ spool' = "UNKNOWN"
    /\ UNCHANGED <<order, plan, expired, sideEffectCalls, restartSeen, blindRepublish>>

RestartKnown ==
    /\ plan = "PUBLISHED" /\ spool \in {"INBOX", "CLAIMED", "PROCESSED", "UNKNOWN"}
    /\ restartSeen' = TRUE
    /\ UNCHANGED <<order, plan, spool, expired, sideEffectCalls, blindRepublish>>

HistoryAmbiguous ==
    /\ plan = "PUBLISHED" /\ spool = "ABSENT"
    /\ order' = "MANUAL_REVIEW" /\ plan' = "MANUAL_REVIEW" /\ restartSeen' = TRUE
    /\ UNCHANGED <<spool, expired, sideEffectCalls, blindRepublish>>

Stutter == UNCHANGED vars
Next == AtomicReserveAndPlan \/ InjectLegacyOrphan \/ SweepLegacyOrphan \/ Expire \/
        ExpirePlannedFailClosed \/ PublishProvenAbsent \/ Claim \/ BrokerCall \/
        Persisted \/ ClaimCrash \/ RestartKnown \/ HistoryAmbiguous \/ Stutter
Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ order \in OrderStates /\ plan \in PlanStates /\ spool \in SpoolStates
    /\ expired \in BOOLEAN /\ sideEffectCalls \in 0..1
    /\ restartSeen \in BOOLEAN /\ blindRepublish \in BOOLEAN

ReservationHasPlan ==
    order = "RESERVED" => plan \in {"PLANNED", "PUBLISHED"}

UnknownNeverBlindRepublishes ==
    spool = "UNKNOWN" => ~blindRepublish

SideEffectAtMostOnce ==
    sideEffectCalls <= 1

ExpiredNeverPublished ==
    expired => spool = "ABSENT" \/ plan = "MANUAL_REVIEW"

NoInvisibleReservedRestart ==
    restartSeen /\ order = "RESERVED" => plan # "NONE"

====
