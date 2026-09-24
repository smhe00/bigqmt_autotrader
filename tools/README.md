# Tools

Operational, generation and offline verification utilities. Tools must not bypass OMS/Risk
authority or write broker state.

- `verify_workflow_contract.py`: validate the active workflow handoff.
- `verify_core_dependency_boundary.py`: reject Core imports of adapters/extensions.
- `verify_core_v1_release.py`: verify the frozen Core v1 inventory/API/schema/formal contract.
- `verify_*_exhaustive.py`: independent finite implementation conformance.
- `verify_*_contract.py`: Bridge/BrokerEvidence schema and semantic drift checks.
- `audit_side_effect_calls.py`: enforce the reviewed QMT mutation call surfaces.
- `build_qmt_deployments.py`: generate/check standalone QMT deployment files.
- `scaffold_workflow_handoff.py`, `agent_workflow_handoff.py`,
  `architect_workflow_verdict.py`: deterministic workflow transitions.

Use the interpreter from the active repository environment. A fresh setup should not depend
on another checkout's virtual environment; see `docs/DEVELOPMENT_ENVIRONMENT_MIGRATION_ZH.md`.
