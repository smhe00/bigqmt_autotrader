---- MODULE BrokerEvidenceBoundary ----

ControlResults == {
    "SHADOW_ACCEPTED",
    "SIMULATION_CALL_RETURNED",
    "REJECTED_EXPIRED"
}
BrokerSources == {"ORDER", "DEAL", "QUERY"}
BrokerStatuses == {
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED"
}
OmsStatuses == BrokerStatuses \cup {"UNKNOWN"}

VARIABLES omsStatus,
          commandResultSeen,
          brokerEvidenceSeen,
          controlPromotions

vars == <<omsStatus, commandResultSeen, brokerEvidenceSeen, controlPromotions>>

Init ==
    /\ omsStatus = "UNKNOWN"
    /\ commandResultSeen = FALSE
    /\ brokerEvidenceSeen = FALSE
    /\ controlPromotions = 0

IngestCommandResult(r) ==
    /\ r \in ControlResults
    /\ commandResultSeen' = TRUE
    /\ UNCHANGED <<omsStatus, brokerEvidenceSeen, controlPromotions>>

IngestBrokerEvidence(source, status) ==
    /\ source \in BrokerSources
    /\ status \in BrokerStatuses
    /\ brokerEvidenceSeen' = TRUE
    /\ omsStatus' = status
    /\ UNCHANGED <<commandResultSeen, controlPromotions>>

Stutter == UNCHANGED vars

Next ==
    (\E r \in ControlResults : IngestCommandResult(r))
    \/ (\E source \in BrokerSources, status \in BrokerStatuses :
        IngestBrokerEvidence(source, status))
    \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ omsStatus \in OmsStatuses
    /\ commandResultSeen \in BOOLEAN
    /\ brokerEvidenceSeen \in BOOLEAN
    /\ controlPromotions \in {0}

CommandResultCannotCreateBrokerLifecycleState ==
    ~brokerEvidenceSeen => omsStatus = "UNKNOWN"

CommandResultCannotCreateBrokerAck ==
    ~brokerEvidenceSeen => omsStatus # "ACKNOWLEDGED"

OnlyBrokerEvidenceCanPromoteOms ==
    controlPromotions = 0

====
