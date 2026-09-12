---- MODULE LeaderLease ----
EXTENDS FiniteSets, Naturals

Sessions == {"A", "B"}
NoOwner == "NONE"
MaxEpoch == 3

VARIABLES owner,
          epoch,
          leaseValid,
          tokenA,
          tokenB,
          executedA,
          executedB

vars == <<owner, epoch, leaseValid, tokenA, tokenB, executedA, executedB>>

Token(s) == IF s = "A" THEN tokenA ELSE tokenB

CanExecute(s) ==
    /\ leaseValid
    /\ owner = s
    /\ Token(s) = epoch

ValidExecutors == {s \in Sessions : CanExecute(s)}

Init ==
    /\ owner = NoOwner
    /\ epoch = 0
    /\ leaseValid = FALSE
    /\ tokenA = 0
    /\ tokenB = 0
    /\ executedA = FALSE
    /\ executedB = FALSE

AcquireA ==
    /\ owner = NoOwner
    /\ ~leaseValid
    /\ epoch < MaxEpoch
    /\ owner' = "A"
    /\ epoch' = epoch + 1
    /\ leaseValid' = TRUE
    /\ tokenA' = epoch + 1
    /\ UNCHANGED <<tokenB, executedA, executedB>>

AcquireB ==
    /\ owner = NoOwner
    /\ ~leaseValid
    /\ epoch < MaxEpoch
    /\ owner' = "B"
    /\ epoch' = epoch + 1
    /\ leaseValid' = TRUE
    /\ tokenB' = epoch + 1
    /\ UNCHANGED <<tokenA, executedA, executedB>>

HeartbeatA ==
    /\ CanExecute("A")
    /\ UNCHANGED vars

HeartbeatB ==
    /\ CanExecute("B")
    /\ UNCHANGED vars

Expire ==
    /\ leaseValid
    /\ owner \in Sessions
    /\ owner' = NoOwner
    /\ leaseValid' = FALSE
    /\ UNCHANGED <<epoch, tokenA, tokenB, executedA, executedB>>

ReleaseA ==
    /\ CanExecute("A")
    /\ owner' = NoOwner
    /\ leaseValid' = FALSE
    /\ UNCHANGED <<epoch, tokenA, tokenB, executedA, executedB>>

ReleaseB ==
    /\ CanExecute("B")
    /\ owner' = NoOwner
    /\ leaseValid' = FALSE
    /\ UNCHANGED <<epoch, tokenA, tokenB, executedA, executedB>>

ExecuteA ==
    /\ CanExecute("A")
    /\ ~executedA
    /\ executedA' = TRUE
    /\ UNCHANGED <<owner, epoch, leaseValid, tokenA, tokenB, executedB>>

ExecuteB ==
    /\ CanExecute("B")
    /\ ~executedB
    /\ executedB' = TRUE
    /\ UNCHANGED <<owner, epoch, leaseValid, tokenA, tokenB, executedA>>

Stutter == UNCHANGED vars

Next ==
    AcquireA \/ AcquireB \/ HeartbeatA \/ HeartbeatB \/ Expire \/
    ReleaseA \/ ReleaseB \/ ExecuteA \/ ExecuteB \/ Stutter

Spec == Init /\ [][Next]_vars

TypeOK ==
    /\ owner \in Sessions \cup {NoOwner}
    /\ epoch \in 0..MaxEpoch
    /\ leaseValid \in BOOLEAN
    /\ tokenA \in 0..MaxEpoch
    /\ tokenB \in 0..MaxEpoch
    /\ executedA \in BOOLEAN
    /\ executedB \in BOOLEAN

AtMostOneValidExecutor == Cardinality(ValidExecutors) <= 1

NoExecutionWithoutLiveOwner ==
    (owner = NoOwner \/ ~leaseValid) => Cardinality(ValidExecutors) = 0

CurrentOwnerHasCurrentFence ==
    owner = NoOwner \/ Token(owner) = epoch

OtherSessionIsFenced ==
    /\ (owner = "A" => tokenB # epoch)
    /\ (owner = "B" => tokenA # epoch)

ExpiredLeaseCannotAuthorize ==
    ~leaseValid => ~CanExecute("A") /\ ~CanExecute("B")

====
