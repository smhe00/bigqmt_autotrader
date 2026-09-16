---- MODULE BrokerEvidenceContract ----
EXTENDS Naturals

\* Finite abstraction of Broker Evidence Contract v1.
\* ORDER_QTY = 2; cumulative fills are abstracted to 0, 1, 2.

ORDER_QTY == 2

OmsStatuses == {
    "UNKNOWN",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "MANUAL_REVIEW"
}

TerminalStatuses == {"FILLED", "CANCELLED", "REJECTED"}

Sources == {
    "COMMAND_RESULT",
    "ORDER_CALLBACK",
    "DEAL_CALLBACK",
    "ACTIVE_ORDER_QUERY",
    "ACTIVE_DEAL_QUERY",
    "UNKNOWN_RAW"
}

EvidenceTargets == {
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED"
}

Events == {
    "cmdSubmit",
    "cmdCancel",
    "badIdentityAck",
    "unknownRawAck",
    "ack1",
    "staleAck",
    "partial1",
    "partialDuplicate",
    "partialConflict",
    "fill1",
    "cancel1",
    "reject1"
}

LogicalIds == {
    "cmdSubmit",
    "cmdCancel",
    "badIdentityAck",
    "unknownRawAck",
    "ack",
    "staleAck",
    "partial",
    "fill",
    "cancel",
    "reject"
}

Digests == {"NONE", "A", "B"}

LogicalId(e) ==
    CASE e = "partialDuplicate" -> "partial"
      [] e = "partialConflict" -> "partial"
      [] e = "partial1" -> "partial"
      [] e = "ack1" -> "ack"
      [] e = "staleAck" -> "staleAck"
      [] e = "fill1" -> "fill"
      [] e = "cancel1" -> "cancel"
      [] e = "reject1" -> "reject"
      [] e = "cmdSubmit" -> "cmdSubmit"
      [] e = "cmdCancel" -> "cmdCancel"
      [] e = "badIdentityAck" -> "badIdentityAck"
      [] e = "unknownRawAck" -> "unknownRawAck"

Digest(e) ==
    IF e = "partialConflict" THEN "B" ELSE "A"

Source(e) ==
    CASE e = "cmdSubmit" -> "COMMAND_RESULT"
      [] e = "cmdCancel" -> "COMMAND_RESULT"
      [] e = "badIdentityAck" -> "ORDER_CALLBACK"
      [] e = "unknownRawAck" -> "ORDER_CALLBACK"
      [] e = "ack1" -> "ORDER_CALLBACK"
      [] e = "staleAck" -> "ACTIVE_ORDER_QUERY"
      [] e = "partial1" -> "DEAL_CALLBACK"
      [] e = "partialDuplicate" -> "DEAL_CALLBACK"
      [] e = "partialConflict" -> "DEAL_CALLBACK"
      [] e = "fill1" -> "ACTIVE_DEAL_QUERY"
      [] e = "cancel1" -> "ACTIVE_ORDER_QUERY"
      [] e = "reject1" -> "ORDER_CALLBACK"

Target(e) ==
    CASE e = "cmdCancel" -> "CANCELLED"
      [] e = "cancel1" -> "CANCELLED"
      [] e = "partial1" -> "PARTIALLY_FILLED"
      [] e = "partialDuplicate" -> "PARTIALLY_FILLED"
      [] e = "partialConflict" -> "PARTIALLY_FILLED"
      [] e = "fill1" -> "FILLED"
      [] e = "reject1" -> "REJECTED"
      [] OTHER -> "ACKNOWLEDGED"

Qty(e) ==
    CASE e = "partial1" -> 1
      [] e = "partialDuplicate" -> 1
      [] e = "partialConflict" -> 1
      [] e = "fill1" -> 2
      [] e = "cancel1" -> 1
      [] OTHER -> 0

IdentityOk(e) == e # "badIdentityAck"

RawKnown(e) == e # "unknownRawAck"

SourceAllows(e) ==
    CASE Source(e) = "ORDER_CALLBACK" ->
        Target(e) \in EvidenceTargets
      [] Source(e) = "ACTIVE_ORDER_QUERY" ->
        Target(e) \in EvidenceTargets
      [] Source(e) = "DEAL_CALLBACK" ->
        Target(e) \in {"PARTIALLY_FILLED", "FILLED"}
      [] Source(e) = "ACTIVE_DEAL_QUERY" ->
        Target(e) \in {"PARTIALLY_FILLED", "FILLED"}
      [] OTHER -> FALSE

ValidQuantity(e) ==
    CASE Target(e) = "ACKNOWLEDGED" -> Qty(e) = 0
      [] Target(e) = "PARTIALLY_FILLED" -> Qty(e) = 1
      [] Target(e) = "FILLED" -> Qty(e) = ORDER_QTY
      [] Target(e) = "CANCELLED" -> Qty(e) \in 0..(ORDER_QTY - 1)
      [] Target(e) = "REJECTED" -> Qty(e) = 0

IsBrokerCandidate(e) ==
    /\ Source(e) \in {
        "ORDER_CALLBACK",
        "DEAL_CALLBACK",
        "ACTIVE_ORDER_QUERY",
        "ACTIVE_DEAL_QUERY"
       }
    /\ IdentityOk(e)
    /\ RawKnown(e)
    /\ SourceAllows(e)
    /\ ValidQuantity(e)

IsTerminal(s) == s \in TerminalStatuses

Rank(s) ==
    CASE s = "UNKNOWN" -> 0
      [] s = "ACKNOWLEDGED" -> 1
      [] s = "PARTIALLY_FILLED" -> 2
      [] s \in TerminalStatuses -> 3
      [] s = "MANUAL_REVIEW" -> 4

Max(a, b) == IF a >= b THEN a ELSE b

LifecycleConflict(current, target, currentFilled, newFilled) ==
    \/ /\ IsTerminal(current)
       /\ IsTerminal(target)
       /\ target # current
    \/ /\ current \in {"CANCELLED", "REJECTED"}
       /\ newFilled > currentFilled
    \/ /\ target = "REJECTED"
       /\ currentFilled > 0

AdvanceStatus(current, target, currentFilled, newFilled) ==
    IF current = "MANUAL_REVIEW"
    THEN "MANUAL_REVIEW"
    ELSE IF LifecycleConflict(current, target, currentFilled, newFilled)
         THEN "MANUAL_REVIEW"
         ELSE IF IsTerminal(current)
              THEN current
              ELSE IF target = "ACKNOWLEDGED"
                   THEN IF current = "UNKNOWN" THEN "ACKNOWLEDGED" ELSE current
                   ELSE IF target = "PARTIALLY_FILLED"
                        THEN "PARTIALLY_FILLED"
                        ELSE target

VARIABLES omsStatus,
          filled,
          seenDigest,
          applyCount,
          brokerEvidenceSeen,
          controlPromotions,
          identityMutations,
          unknownMutations,
          terminalConflict,
          semanticConflict,
          rankHighWater

vars == <<
    omsStatus,
    filled,
    seenDigest,
    applyCount,
    brokerEvidenceSeen,
    controlPromotions,
    identityMutations,
    unknownMutations,
    terminalConflict,
    semanticConflict,
    rankHighWater
>>

Init ==
    /\ omsStatus = "UNKNOWN"
    /\ filled = 0
    /\ seenDigest = [i \in LogicalIds |-> "NONE"]
    /\ applyCount = [i \in LogicalIds |-> 0]
    /\ brokerEvidenceSeen = FALSE
    /\ controlPromotions = 0
    /\ identityMutations = 0
    /\ unknownMutations = 0
    /\ terminalConflict = FALSE
    /\ semanticConflict = FALSE
    /\ rankHighWater = 0

Ingest(e) ==
    /\ e \in Events
    /\ LET lid == LogicalId(e)
           digest == Digest(e)
       IN
       IF seenDigest[lid] # "NONE"
       THEN
           IF seenDigest[lid] = digest
           THEN UNCHANGED vars
           ELSE
               /\ omsStatus' = "MANUAL_REVIEW"
               /\ semanticConflict' = TRUE
               /\ rankHighWater' = 4
               /\ UNCHANGED <<
                    filled,
                    seenDigest,
                    applyCount,
                    brokerEvidenceSeen,
                    controlPromotions,
                    identityMutations,
                    unknownMutations,
                    terminalConflict
                  >>
       ELSE
           /\ seenDigest' = [seenDigest EXCEPT ![lid] = digest]
           /\ IF ~IsBrokerCandidate(e)
              THEN
                  /\ UNCHANGED <<
                       omsStatus,
                       filled,
                       applyCount,
                       brokerEvidenceSeen,
                       terminalConflict,
                       semanticConflict,
                       rankHighWater
                     >>
                  /\ controlPromotions' = controlPromotions
                  /\ identityMutations' = identityMutations
                  /\ unknownMutations' = unknownMutations
              ELSE
                  LET nextFilled == Max(filled, Qty(e))
                      nextStatus == AdvanceStatus(
                          omsStatus,
                          Target(e),
                          filled,
                          Qty(e)
                      )
                      nextConflict == LifecycleConflict(
                          omsStatus,
                          Target(e),
                          filled,
                          Qty(e)
                      )
                  IN
                  /\ omsStatus' = nextStatus
                  /\ filled' = nextFilled
                  /\ applyCount' = [applyCount EXCEPT ![lid] = @ + 1]
                  /\ brokerEvidenceSeen' = TRUE
                  /\ terminalConflict' = (terminalConflict \/ nextConflict)
                  /\ rankHighWater' = Max(rankHighWater, Rank(nextStatus))
                  /\ UNCHANGED <<
                       controlPromotions,
                       identityMutations,
                       unknownMutations,
                       semanticConflict
                     >>

Stutter == UNCHANGED vars

Next == (\E e \in Events : Ingest(e)) \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ omsStatus \in OmsStatuses
    /\ filled \in 0..ORDER_QTY
    /\ seenDigest \in [LogicalIds -> Digests]
    /\ applyCount \in [LogicalIds -> 0..1]
    /\ brokerEvidenceSeen \in BOOLEAN
    /\ controlPromotions = 0
    /\ identityMutations = 0
    /\ unknownMutations = 0
    /\ terminalConflict \in BOOLEAN
    /\ semanticConflict \in BOOLEAN
    /\ rankHighWater \in 0..4

CommandResultCannotCreateBrokerEvidence ==
    controlPromotions = 0

IdentityMismatchNeverMutatesOms ==
    identityMutations = 0

UnknownRawStatusCannotAdvanceOms ==
    unknownMutations = 0

DuplicateEvidenceAppliedAtMostOnce ==
    \A i \in LogicalIds : applyCount[i] <= 1

NoBrokerEvidenceNoLifecycle ==
    ~brokerEvidenceSeen => omsStatus = "UNKNOWN"

OutOfOrderEvidenceCannotRegressState ==
    Rank(omsStatus) = rankHighWater

PartialFillCannotRegressToAck ==
    filled > 0 => omsStatus # "ACKNOWLEDGED"

FilledIsAbsorbingUnlessTerminalConflict ==
    applyCount["fill"] = 1 =>
        (omsStatus = "FILLED" \/ omsStatus = "MANUAL_REVIEW")

CancelSignalCannotCreateCancelled ==
    /\ controlPromotions = 0
    /\ ~(omsStatus = "CANCELLED" /\ ~brokerEvidenceSeen)

ConflictingTerminalEvidenceFailsClosed ==
    terminalConflict => omsStatus = "MANUAL_REVIEW"

SemanticConflictFailsClosed ==
    semanticConflict => omsStatus = "MANUAL_REVIEW"

RejectedHasNoFill ==
    omsStatus = "REJECTED" => filled = 0

CancelledNeverClaimsFullFill ==
    omsStatus = "CANCELLED" => filled < ORDER_QTY

====
