"""Real B/O contracts with explicitly synthetic, non-executing unit backend."""
import pytest

from srp_b.module import BModule
from scripts.verify_p2_boundaries import (REFERENCE_CASES, BUDGET_CASES, O_CASES,
                                         CountingRunner, reference_case, budget_case, o_case)
from test_local_v2 import SyntheticRunner


@pytest.mark.parametrize("group,name", [(group, name) for group, names in
                         (("reference", REFERENCE_CASES), ("budget", BUDGET_CASES), ("o", O_CASES)) for name in names])
def test_b_o_reference_accounting_and_failure_boundary(group, name, tmp_path):
    def make_module(directory):
        runner = CountingRunner(SyntheticRunner())
        return BModule(state_dir=directory, runner=runner), runner
    function = {"reference": reference_case, "budget": budget_case, "o": o_case}[group]
    result = function(make_module, tmp_path / name, name)
    assert result["result"] == "passed"
