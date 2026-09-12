---- MODULE OrderFSM ----
EXTENDS FiniteSets

Statuses == {
    "CREATED",
    "RISK_REJECTED",
    "RISK_ACCEPTED",
    "ABORTED",
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

TerminalStatuses == {
    "RISK_REJECTED",
    "ABORTED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "MANUAL_REVIEW"
}

Allowed == {
    <<"CREATED", "RISK_REJECTED">>,
    <<"CREATED", "RISK_ACCEPTED">>,
    <<"CREATED", "ABORTED">>,
    <<"RISK_ACCEPTED", "SUBMITTING">>,
    <<"RISK_ACCEPTED", "ABORTED">>,
    <<"SUBMITTING", "ACKNOWLEDGED">>,
    <<"SUBMITTING", "REJECTED">>,
    <<"SUBMITTING", "UNKNOWN">>,
    <<"ACKNOWLEDGED", "PARTIALLY_FILLED">>,
    <<"ACKNOWLEDGED", "FILLED">>,
    <<"ACKNOWLEDGED", "CANCEL_PENDING">>,
    <<"PARTIALLY_FILLED", "FILLED">>,
    <<"PARTIALLY_FILLED", "CANCEL_PENDING">>,
    <<"PARTIALLY_FILLED", "CANCELLED">>,
    <<"CANCEL_PENDING", "CANCELLED">>,
    <<"CANCEL_PENDING", "PARTIALLY_FILLED">>,
    <<"CANCEL_PENDING", "FILLED">>,
    <<"CANCEL_PENDING", "UNKNOWN">>,
    <<"UNKNOWN", "RECONCILING">>,
    <<"RECONCILING", "ACKNOWLEDGED">>,
    <<"RECONCILING", "PARTIALLY_FILLED">>,
    <<"RECONCILING", "FILLED">>,
    <<"RECONCILING", "REJECTED">>,
    <<"RECONCILING", "CANCELLED">>,
    <<"RECONCILING", "MANUAL_REVIEW">>
}

ExplicitStale == {
    <<"RISK_ACCEPTED", "CREATED">>,
    <<"SUBMITTING", "CREATED">>,
    <<"SUBMITTING", "RISK_ACCEPTED">>,
    <<"ACKNOWLEDGED", "CREATED">>,
    <<"ACKNOWLEDGED", "RISK_ACCEPTED">>,
    <<"ACKNOWLEDGED", "SUBMITTING">>,
    <<"PARTIALLY_FILLED", "CREATED">>,
    <<"PARTIALLY_FILLED", "RISK_ACCEPTED">>,
    <<"PARTIALLY_FILLED", "SUBMITTING">>,
    <<"PARTIALLY_FILLED", "ACKNOWLEDGED">>,
    <<"CANCEL_PENDING", "CREATED">>,
    <<"CANCEL_PENDING", "RISK_ACCEPTED">>,
    <<"CANCEL_PENDING", "SUBMITTING">>,
    <<"CANCEL_PENDING", "ACKNOWLEDGED">>
}

Pair(c, r) == <<c, r>>
IsDuplicate(c, r) == c = r
IsAllowed(c, r) == Pair(c, r) \in Allowed
IsStale(c, r) == (c \in TerminalStatuses /\ c # r) \/ Pair(c, r) \in ExplicitStale
IsIllegal(c, r) == ~(IsDuplicate(c, r) \/ IsAllowed(c, r) \/ IsStale(c, r))

ClassificationTags(c, r) == {
    tag \in {"DUPLICATE", "APPLIED", "STALE", "ILLEGAL"} :
        (tag = "DUPLICATE" /\ IsDuplicate(c, r)) \/
        (tag = "APPLIED" /\ IsAllowed(c, r)) \/
        (tag = "STALE" /\ IsStale(c, r)) \/
        (tag = "ILLEGAL" /\ IsIllegal(c, r))
}

ClassificationIsTotalAndExclusive ==
    \A c \in Statuses : \A r \in Statuses : Cardinality(ClassificationTags(c, r)) = 1

TerminalHasNoAppliedExit ==
    \A c \in TerminalStatuses : \A r \in Statuses : ~IsAllowed(c, r)

UnknownOnlyExitsToReconciling ==
    \A r \in Statuses : IsAllowed("UNKNOWN", r) <=> r = "RECONCILING"

NoReturnToPreSubmitFromAmbiguity ==
    \A c \in {"UNKNOWN", "RECONCILING"} :
        \A r \in {"CREATED", "RISK_ACCEPTED", "SUBMITTING"} : ~IsAllowed(c, r)

AbortOnlyFromPreSubmit ==
    \A c \in Statuses : IsAllowed(c, "ABORTED") <=> c \in {"CREATED", "RISK_ACCEPTED"}

NoPostSubmitAbort ==
    \A c \in {"SUBMITTING", "ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED",
               "CANCEL_PENDING", "CANCELLED", "REJECTED", "UNKNOWN",
               "RECONCILING", "MANUAL_REVIEW"} : ~IsAllowed(c, "ABORTED")

VARIABLES status, terminalLock
vars == <<status, terminalLock>>

Init ==
    /\ status = "CREATED"
    /\ terminalLock = "NONE"

Apply(requested) ==
    /\ requested \in Statuses
    /\ IsAllowed(status, requested)
    /\ status' = requested
    /\ terminalLock' =
        IF terminalLock # "NONE"
        THEN terminalLock
        ELSE IF requested \in TerminalStatuses THEN requested ELSE "NONE"

IgnoreDuplicate(requested) ==
    /\ requested \in Statuses
    /\ IsDuplicate(status, requested)
    /\ UNCHANGED vars

IgnoreStale(requested) ==
    /\ requested \in Statuses
    /\ IsStale(status, requested)
    /\ UNCHANGED vars

Stutter == UNCHANGED vars

Next ==
    (\E requested \in Statuses :
        Apply(requested) \/ IgnoreDuplicate(requested) \/ IgnoreStale(requested))
    \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ status \in Statuses
    /\ terminalLock \in TerminalStatuses \cup {"NONE"}

TerminalAbsorption == terminalLock = "NONE" \/ status = terminalLock

====
