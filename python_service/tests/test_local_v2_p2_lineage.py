import pytest

from reliable_codegen.mocks import create_mock_module
from reliable_codegen.transport import LocalTransport
from srp_b.module import BModule
from scripts.verify_p2_lineage import SCENARIOS, run_scenario
from test_local_v2 import SyntheticRunner


class ScriptedRunner(SyntheticRunner):
    """Unit-test outcomes only; never executes or interprets candidate source."""
    def __init__(self, outcomes):
        super().__init__()
        self.outcomes = iter(outcomes)

    def execute(self, payload, **kwargs):
        value = super().execute(payload, **kwargs)
        if next(self.outcomes) == "passed":
            value.update(test_outcome="passed", exit_code=0, tests_passed=1, failure_stage="none")
            case = value["test_case_results"][0]
            case.update(status="passed", message=None, error_type=None)
        return value


@pytest.mark.parametrize("name", SCENARIOS)
def test_o_and_real_b_contract_history_lineage_with_synthetic_runner(name, tmp_path):
    if name == "two_static_failures":
        outcomes = ["passed", "passed"]
    elif name == "static_then_execution":
        outcomes = ["failed", "passed", "passed"]
    elif name == "two_execution_failures":
        outcomes = ["failed", "failed", "passed", "passed"]
    elif name == "stale_failure_source":
        outcomes = ["failed", "failed"]
    else:
        outcomes = ["failed"]
    runner = ScriptedRunner(outcomes)
    transport = LocalTransport({"A": create_mock_module(service="A"), "B": BModule(state_dir=tmp_path / "b", runner=runner),
                                "C": create_mock_module(service="C")}, timeout=15)
    result = run_scenario(transport, tmp_path / "run", name)
    assert result["evidence_kind"] == "synthetic_unit_backend"
    assert result["physical_execution_calls"] == runner.calls == SCENARIOS[name]["executions"]
