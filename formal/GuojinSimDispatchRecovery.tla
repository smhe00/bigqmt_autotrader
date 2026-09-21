---- MODULE GuojinSimDispatchRecovery ----
EXTENDS Naturals

\* P6-T004 finite abstraction of the Host-owned durable dispatch plan.
\* Only a PLAN with a provably absent spool file may be published automatically.

PlanStates == {"NONE", "PLANNED", "PUBLISHED", "MANUAL_REVIEW"}
SpoolStates == {"ABSENT", "INBOX", "CLAIMED", "PROCESSED", "UNKNOWN"}

VARIABLES plan, spool, sideEffectCalls, restartSeen, blindRepublish
vars == <<plan, spool, sideEffectCalls, restartSeen, blindRepublish>>

Init ==
    /\ plan = "NONE" /\ spool = "ABSENT" /\ sideEffectCalls = 0
    /\ restartSeen = FALSE /\ blindRepublish = FALSE

PersistPlan ==
    /\ plan = "NONE" /\ spool = "ABSENT" /\ plan' = "PLANNED"
    /\ UNCHANGED <<spool, sideEffectCalls, restartSeen, blindRepublish>>

PublishProvenAbsent ==
    /\ plan = "PLANNED" /\ spool = "ABSENT"
    /\ plan' = "PUBLISHED" /\ spool' = "INBOX"
    /\ UNCHANGED <<sideEffectCalls, restartSeen, blindRepublish>>

Claim ==
    /\ spool = "INBOX" /\ spool' = "CLAIMED"
    /\ UNCHANGED <<plan, sideEffectCalls, restartSeen, blindRepublish>>

BrokerCall ==
    /\ spool = "CLAIMED" /\ sideEffectCalls = 0 /\ sideEffectCalls' = 1
    /\ UNCHANGED <<plan, spool, restartSeen, blindRepublish>>

Persisted ==
    /\ spool = "CLAIMED" /\ sideEffectCalls = 1 /\ spool' = "PROCESSED"
    /\ UNCHANGED <<plan, sideEffectCalls, restartSeen, blindRepublish>>

ClaimCrash ==
    /\ spool = "CLAIMED" /\ spool' = "UNKNOWN"
    /\ UNCHANGED <<plan, sideEffectCalls, restartSeen, blindRepublish>>

RestartKnown ==
    /\ plan = "PUBLISHED" /\ spool \in {"INBOX", "CLAIMED", "PROCESSED", "UNKNOWN"}
    /\ restartSeen' = TRUE
    /\ UNCHANGED <<plan, spool, sideEffectCalls, blindRepublish>>

HistoryAmbiguous ==
    /\ plan = "PUBLISHED" /\ spool = "ABSENT"
    /\ plan' = "MANUAL_REVIEW" /\ restartSeen' = TRUE
    /\ UNCHANGED <<spool, sideEffectCalls, blindRepublish>>

Stutter == UNCHANGED vars
Next == PersistPlan \/ PublishProvenAbsent \/ Claim \/ BrokerCall \/ Persisted \/
        ClaimCrash \/ RestartKnown \/ HistoryAmbiguous \/ Stutter
Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ plan \in PlanStates /\ spool \in SpoolStates /\ sideEffectCalls \in 0..1
    /\ restartSeen \in BOOLEAN /\ blindRepublish \in BOOLEAN
UnknownNeverBlindRepublishes == spool = "UNKNOWN" => ~blindRepublish
SideEffectAtMostOnce == sideEffectCalls <= 1

====
