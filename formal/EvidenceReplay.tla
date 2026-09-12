---- MODULE EvidenceReplay ----
EXTENDS FiniteSets, Naturals, TLC

Evidence == {"ACK", "PARTIAL", "FILL"}
Statuses == {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED"}

Requested(e) ==
    IF e = "ACK" THEN "ACKNOWLEDGED"
    ELSE IF e = "PARTIAL" THEN "PARTIALLY_FILLED"
    ELSE "FILLED"

Qty(e) ==
    IF e = "ACK" THEN 0
    ELSE IF e = "PARTIAL" THEN 50
    ELSE 100

Rank(s) ==
    IF s = "ACKNOWLEDGED" THEN 0
    ELSE IF s = "PARTIALLY_FILLED" THEN 1
    ELSE 2

Max(a, b) == IF a >= b THEN a ELSE b

AggregateStatus(current, requested) ==
    IF Rank(requested) > Rank(current) THEN requested ELSE current

VARIABLES status,
          filled,
          seen,
          applyCount

vars == <<status, filled, seen, applyCount>>

Init ==
    /\ status = "ACKNOWLEDGED"
    /\ filled = 0
    /\ seen = {}
    /\ applyCount = [e \in Evidence |-> 0]

Ingest(e) ==
    /\ e \in Evidence
    /\ IF e \in seen
          THEN UNCHANGED vars
          ELSE /\ seen' = seen \cup {e}
               /\ applyCount' = [applyCount EXCEPT ![e] = @ + 1]
               /\ status' = AggregateStatus(status, Requested(e))
               /\ filled' = Max(filled, Qty(e))

Stutter == UNCHANGED vars

Next == (\E e \in Evidence : Ingest(e)) \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ status \in Statuses
    /\ filled \in {0, 50, 100}
    /\ seen \subseteq Evidence
    /\ applyCount \in [Evidence -> 0..1]

EachFingerprintAppliedAtMostOnce ==
    \A e \in Evidence : applyCount[e] <= 1

SeenIffApplied ==
    \A e \in Evidence : (e \in seen) <=> (applyCount[e] = 1)

AggregateNeverContradictsFill ==
    /\ (status = "ACKNOWLEDGED" => filled = 0)
    /\ (status = "PARTIALLY_FILLED" => filled >= 50)
    /\ (status = "FILLED" => filled = 100)

FillEvidenceIsAbsorbing ==
    ("FILL" \in seen) => status = "FILLED"

PartialEvidenceNeverReturnsToAck ==
    ("PARTIAL" \in seen) => status # "ACKNOWLEDGED"

====
