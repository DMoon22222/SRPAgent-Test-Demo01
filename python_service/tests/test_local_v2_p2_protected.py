"""Control-flow evidence only: scripted non-executing unit backend."""
import pytest

from reliable_codegen.mocks import create_mock_module
from reliable_codegen.transport import LocalTransport
from srp_b.module import BModule
from scripts.verify_p2_boundaries import CountingRunner
from scripts.verify_p2_protected import SCENARIOS, run_scenario
from test_local_v2_p2_lineage import ScriptedRunner


@pytest.mark.parametrize("name", SCENARIOS)
def test_real_b_and_o_protected_receiver_views_with_synthetic_backend(name, tmp_path):
    runner = CountingRunner(ScriptedRunner(["failed", "passed", "failed" if name == "hidden_failure" else "passed"]))
    module = BModule(state_dir=tmp_path / "b", runner=runner)
    transport = LocalTransport({"A": create_mock_module(service="A"), "B": module, "C": create_mock_module(service="C")}, timeout=60)
    result = run_scenario(transport, runner, tmp_path / "scenario", name)
    assert result["result"] == "passed" and result["public_canary_hits"] == 0
