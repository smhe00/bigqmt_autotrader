---- MODULE RiskPrecedence ----
EXTENDS FiniteSets, Naturals

\* Representative ordered rules span all four risk levels. The Python engine has
\* more concrete rules, but uses the same fixed level/rule precedence contract.
Rules == {
    "G_DATABASE",
    "G_LEADER",
    "G_MODE",
    "A_ACCOUNT",
    "A_FRESHNESS",
    "A_EXPOSURE",
    "S_IDENTITY",
    "S_HEARTBEAT",
    "S_BUDGET",
    "O_EXPIRY",
    "O_MARKET_DATA",
    "O_ORDER_LIMIT"
}

Rank(r) ==
    CASE r = "G_DATABASE"   -> 1
      [] r = "G_LEADER"     -> 2
      [] r = "G_MODE"       -> 3
      [] r = "A_ACCOUNT"    -> 4
      [] r = "A_FRESHNESS"  -> 5
      [] r = "A_EXPOSURE"   -> 6
      [] r = "S_IDENTITY"   -> 7
      [] r = "S_HEARTBEAT"  -> 8
      [] r = "S_BUDGET"     -> 9
      [] r = "O_EXPIRY"     -> 10
      [] r = "O_MARKET_DATA"-> 11
      [] r = "O_ORDER_LIMIT"-> 12

Earliest(fs) ==
    CHOOSE r \in fs : \A s \in fs : Rank(r) <= Rank(s)

VARIABLES failures, accepted, primary
vars == <<failures, accepted, primary>>

Init ==
    /\ failures \in SUBSET Rules
    /\ accepted = (failures = {})
    /\ primary = IF failures = {} THEN "RISK_OK" ELSE Earliest(failures)

Next == UNCHANGED vars
Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ failures \subseteq Rules
    /\ accepted \in BOOLEAN
    /\ primary \in Rules \cup {"RISK_OK"}

AcceptedIffNoFailure == accepted <=> failures = {}
AnyFailureFailsClosed == failures # {} => ~accepted
SuccessHasOnlyOkPrimary == accepted => primary = "RISK_OK"
RejectedPrimaryIsFailure == ~accepted => primary \in failures
PrimaryIsEarliestFailure ==
    ~accepted => \A r \in failures : Rank(primary) <= Rank(r)

GlobalBeforeLowerLevels ==
    (failures \cap {"G_DATABASE", "G_LEADER", "G_MODE"} # {}) =>
        Rank(primary) <= 3

AccountBeforeStrategyOrOrder ==
    /\ failures \cap {"G_DATABASE", "G_LEADER", "G_MODE"} = {}
    /\ failures \cap {"A_ACCOUNT", "A_FRESHNESS", "A_EXPOSURE"} # {}
    => Rank(primary) \in 4..6

StrategyBeforeOrder ==
    /\ failures \cap {"G_DATABASE", "G_LEADER", "G_MODE",
                       "A_ACCOUNT", "A_FRESHNESS", "A_EXPOSURE"} = {}
    /\ failures \cap {"S_IDENTITY", "S_HEARTBEAT", "S_BUDGET"} # {}
    => Rank(primary) \in 7..9

====
