---- MODULE BridgeEventProtocol ----
EXTENDS Naturals

Sessions == {1, 2}
Sequences == 1..3

VARIABLES session,
          lastSequence,
          needsResync,
          duplicateSeen,
          rejectedIdentitySeen,
          rejectedIdentityApplied,
          duplicateApplied,
          gapUnresolved,
          sessionUnresolved,
          regressionApplied,
          clearWithoutCleanSnapshot

vars == <<session, lastSequence, needsResync, duplicateSeen,
          rejectedIdentitySeen, rejectedIdentityApplied, duplicateApplied,
          gapUnresolved, sessionUnresolved, regressionApplied,
          clearWithoutCleanSnapshot>>

Init ==
    /\ session = 0
    /\ lastSequence = 0
    /\ needsResync = TRUE
    /\ duplicateSeen = FALSE
    /\ rejectedIdentitySeen = FALSE
    /\ rejectedIdentityApplied = FALSE
    /\ duplicateApplied = FALSE
    /\ gapUnresolved = FALSE
    /\ sessionUnresolved = FALSE
    /\ regressionApplied = FALSE
    /\ clearWithoutCleanSnapshot = FALSE

RejectIdentity(instanceOK, accountOK) ==
    /\ ~(instanceOK /\ accountOK)
    /\ rejectedIdentitySeen' = TRUE
    /\ UNCHANGED <<session, lastSequence, needsResync, duplicateSeen,
                   rejectedIdentityApplied, duplicateApplied, gapUnresolved,
                   sessionUnresolved, regressionApplied,
                   clearWithoutCleanSnapshot>>

NewSession(s, q, cleanSnapshot) ==
    /\ s \in Sessions
    /\ q \in Sequences
    /\ s > session
    /\ session' = s
    /\ lastSequence' = q
    /\ needsResync' = ~cleanSnapshot
    /\ gapUnresolved' = FALSE
    /\ sessionUnresolved' = ~cleanSnapshot
    /\ UNCHANGED <<duplicateSeen, rejectedIdentitySeen,
                   rejectedIdentityApplied, duplicateApplied,
                   regressionApplied, clearWithoutCleanSnapshot>>

Duplicate(s, q) ==
    /\ s = session
    /\ q <= lastSequence
    /\ duplicateSeen' = TRUE
    /\ UNCHANGED <<session, lastSequence, needsResync,
                   rejectedIdentitySeen, rejectedIdentityApplied,
                   duplicateApplied, gapUnresolved, sessionUnresolved,
                   regressionApplied, clearWithoutCleanSnapshot>>

NextSequence(s, q, cleanSnapshot) ==
    /\ s = session
    /\ q = lastSequence + 1
    /\ lastSequence' = q
    /\ needsResync' = IF cleanSnapshot THEN FALSE ELSE needsResync
    /\ gapUnresolved' = IF cleanSnapshot THEN FALSE ELSE gapUnresolved
    /\ sessionUnresolved' = IF cleanSnapshot THEN FALSE ELSE sessionUnresolved
    /\ UNCHANGED <<session, duplicateSeen, rejectedIdentitySeen,
                   rejectedIdentityApplied, duplicateApplied,
                   regressionApplied, clearWithoutCleanSnapshot>>

Gap(s, q, cleanSnapshot) ==
    /\ s = session
    /\ q > lastSequence + 1
    /\ lastSequence' = q
    /\ needsResync' = IF cleanSnapshot THEN FALSE ELSE TRUE
    /\ gapUnresolved' = ~cleanSnapshot
    /\ sessionUnresolved' = IF cleanSnapshot THEN FALSE ELSE sessionUnresolved
    /\ UNCHANGED <<session, duplicateSeen, rejectedIdentitySeen,
                   rejectedIdentityApplied, duplicateApplied,
                   regressionApplied, clearWithoutCleanSnapshot>>

Stutter == UNCHANGED vars

Next ==
    (\E instanceOK \in BOOLEAN, accountOK \in BOOLEAN :
        RejectIdentity(instanceOK, accountOK))
    \/ (\E s \in Sessions, q \in Sequences, cleanSnapshot \in BOOLEAN :
        NewSession(s, q, cleanSnapshot)
        \/ Duplicate(s, q)
        \/ NextSequence(s, q, cleanSnapshot)
        \/ Gap(s, q, cleanSnapshot))
    \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ session \in {0, 1, 2}
    /\ lastSequence \in 0..3
    /\ needsResync \in BOOLEAN
    /\ duplicateSeen \in BOOLEAN
    /\ rejectedIdentitySeen \in BOOLEAN
    /\ rejectedIdentityApplied \in BOOLEAN
    /\ duplicateApplied \in BOOLEAN
    /\ gapUnresolved \in BOOLEAN
    /\ sessionUnresolved \in BOOLEAN
    /\ regressionApplied \in BOOLEAN
    /\ clearWithoutCleanSnapshot \in BOOLEAN

DuplicateDoesNotApply ==
    ~duplicateApplied

WrongIdentityDoesNotApply ==
    ~rejectedIdentityApplied

GapRequiresResyncUntilCleanSnapshot ==
    gapUnresolved => needsResync

SessionChangeRequiresResyncUntilCleanSnapshot ==
    sessionUnresolved => needsResync

OnlyCleanSnapshotClearsResync ==
    ~clearWithoutCleanSnapshot

AcceptedSequenceNeverRegresses ==
    ~regressionApplied

====
