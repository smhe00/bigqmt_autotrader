---- MODULE BridgeCommandProtocol ----
EXTENDS Naturals, FiniteSets

States == {"ABSENT", "INBOX", "CLAIMED", "PROCESSED", "REJECTED", "UNKNOWN"}
TerminalStates == {"PROCESSED", "REJECTED", "UNKNOWN"}
Modes == {"SHADOW", "SIMULATION"}
Results == {
    "NONE",
    "SHADOW_ACCEPTED",
    "SIMULATION_CALL_RETURNED",
    "REJECTED",
    "UNKNOWN_ORPHANED"
}

VARIABLES state,
          mode,
          expired,
          accountOK,
          sessionOK,
          sideEffectCalls,
          brokerAck,
          result,
          canonicalWrites,
          sameRepublishes,
          conflictSeen,
          claimedCrash,
          restartSeen,
          blindReplay

vars == <<state, mode, expired, accountOK, sessionOK,
          sideEffectCalls, brokerAck, result, canonicalWrites,
          sameRepublishes, conflictSeen, claimedCrash,
          restartSeen, blindReplay>>

Init ==
    /\ state = "ABSENT"
    /\ mode \in Modes
    /\ expired \in BOOLEAN
    /\ accountOK \in BOOLEAN
    /\ sessionOK \in BOOLEAN
    /\ sideEffectCalls = 0
    /\ brokerAck = FALSE
    /\ result = "NONE"
    /\ canonicalWrites = 0
    /\ sameRepublishes = 0
    /\ conflictSeen = FALSE
    /\ claimedCrash = FALSE
    /\ restartSeen = FALSE
    /\ blindReplay = FALSE

PublishNew ==
    /\ state = "ABSENT"
    /\ state' = "INBOX"
    /\ canonicalWrites' = 1
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, result,
                   sameRepublishes, conflictSeen, claimedCrash,
                   restartSeen, blindReplay>>

RepublishSame ==
    /\ canonicalWrites = 1
    /\ state # "ABSENT"
    /\ sameRepublishes = 0
    /\ sameRepublishes' = 1
    /\ UNCHANGED <<state, mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, result, canonicalWrites,
                   conflictSeen, claimedCrash, restartSeen, blindReplay>>

RepublishConflict ==
    /\ canonicalWrites = 1
    /\ state # "ABSENT"
    /\ ~conflictSeen
    /\ conflictSeen' = TRUE
    /\ UNCHANGED <<state, mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, result, canonicalWrites,
                   sameRepublishes, claimedCrash, restartSeen, blindReplay>>

Claim ==
    /\ state = "INBOX"
    /\ state' = "CLAIMED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, result, canonicalWrites,
                   sameRepublishes, conflictSeen, claimedCrash,
                   restartSeen, blindReplay>>

RejectInvalid ==
    /\ state = "CLAIMED"
    /\ (expired \/ ~accountOK \/ (mode = "SIMULATION" /\ ~sessionOK))
    /\ state' = "REJECTED"
    /\ result' = "REJECTED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, canonicalWrites,
                   sameRepublishes, conflictSeen, claimedCrash,
                   restartSeen, blindReplay>>

ProcessShadow ==
    /\ state = "CLAIMED"
    /\ mode = "SHADOW"
    /\ ~expired
    /\ accountOK
    /\ state' = "PROCESSED"
    /\ result' = "SHADOW_ACCEPTED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, canonicalWrites,
                   sameRepublishes, conflictSeen, claimedCrash,
                   restartSeen, blindReplay>>

ProcessSimulation ==
    /\ state = "CLAIMED"
    /\ mode = "SIMULATION"
    /\ ~expired
    /\ accountOK
    /\ sessionOK
    /\ sideEffectCalls = 0
    /\ state' = "PROCESSED"
    /\ sideEffectCalls' = 1
    /\ result' = "SIMULATION_CALL_RETURNED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   brokerAck, canonicalWrites, sameRepublishes,
                   conflictSeen, claimedCrash, restartSeen, blindReplay>>

SimulationCallBeforePersist ==
    /\ state = "CLAIMED"
    /\ mode = "SIMULATION"
    /\ ~expired
    /\ accountOK
    /\ sessionOK
    /\ sideEffectCalls = 0
    /\ sideEffectCalls' = 1
    /\ UNCHANGED <<state, mode, expired, accountOK, sessionOK,
                   brokerAck, result, canonicalWrites, sameRepublishes,
                   conflictSeen, claimedCrash, restartSeen, blindReplay>>

PersistSimulationResult ==
    /\ state = "CLAIMED"
    /\ mode = "SIMULATION"
    /\ sideEffectCalls = 1
    /\ state' = "PROCESSED"
    /\ result' = "SIMULATION_CALL_RETURNED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, canonicalWrites,
                   sameRepublishes, conflictSeen, claimedCrash,
                   restartSeen, blindReplay>>

CrashClaimed ==
    /\ state = "CLAIMED"
    /\ state' = "UNKNOWN"
    /\ claimedCrash' = TRUE
    /\ result' = "UNKNOWN_ORPHANED"
    /\ UNCHANGED <<mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, canonicalWrites,
                   sameRepublishes, conflictSeen, restartSeen, blindReplay>>

RestartOrphan ==
    /\ state = "UNKNOWN"
    /\ claimedCrash
    /\ ~restartSeen
    /\ restartSeen' = TRUE
    /\ UNCHANGED <<state, mode, expired, accountOK, sessionOK,
                   sideEffectCalls, brokerAck, result, canonicalWrites,
                   sameRepublishes, conflictSeen, claimedCrash, blindReplay>>

Stutter == UNCHANGED vars

Next ==
    PublishNew \/ RepublishSame \/ RepublishConflict \/ Claim \/
    RejectInvalid \/ ProcessShadow \/ ProcessSimulation \/
    SimulationCallBeforePersist \/ PersistSimulationResult \/
    CrashClaimed \/ RestartOrphan \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ state \in States
    /\ mode \in Modes
    /\ expired \in BOOLEAN
    /\ accountOK \in BOOLEAN
    /\ sessionOK \in BOOLEAN
    /\ sideEffectCalls \in 0..1
    /\ brokerAck \in BOOLEAN
    /\ result \in Results
    /\ canonicalWrites \in 0..1
    /\ sameRepublishes \in 0..1
    /\ conflictSeen \in BOOLEAN
    /\ claimedCrash \in BOOLEAN
    /\ restartSeen \in BOOLEAN
    /\ blindReplay \in BOOLEAN

ExpiredNeverMutatesBroker ==
    expired => sideEffectCalls = 0

WrongAccountNeverMutatesBroker ==
    ~accountOK => sideEffectCalls = 0

WrongSessionNeverMutatesBroker ==
    (mode = "SIMULATION" /\ ~sessionOK) => sideEffectCalls = 0

ShadowNeverMutatesBroker ==
    mode = "SHADOW" => sideEffectCalls = 0

SideEffectAtMostOnce ==
    sideEffectCalls <= 1

ClaimedCrashNeverBlindReplays ==
    claimedCrash => (state = "UNKNOWN" /\ ~blindReplay)

SameCommandIdSamePayloadIsIdempotent ==
    sameRepublishes > 0 => canonicalWrites = 1

SameCommandIdDifferentPayloadIsConflict ==
    conflictSeen => canonicalWrites = 1

TerminalCommandStateIsExclusive ==
    state \in TerminalStates =>
        Cardinality({s \in TerminalStates : state = s}) = 1

CommandResultCannotCreateBrokerAck ==
    ~brokerAck

====
