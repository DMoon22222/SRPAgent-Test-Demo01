from copy import deepcopy

import pytest

from reliable_codegen.contracts import ContractRegistry
from reliable_codegen.guards import check_public
from reliable_codegen.utils import canonical, digest
from srp_b.module import BModule, DIAGNOSE, EXECUTE
from srp_b.samples import diagnostic, request, sample_request
from srp_b.sandbox import log_stream
from scripts.check_local_v2 import PROTECTED_PATCHES, check_diagnostic_evidence, check_sample
from test_local_v2 import SyntheticRunner


@pytest.fixture
def diagnosis(tmp_path):
    runner = SyntheticRunner()
    runner.overrides.update(stdout=log_stream("AssertionError: assert -1 == 5"), stderr=log_stream())
    module = BModule(state_dir=tmp_path / "state", runner=runner)
    original = request(EXECUTE)
    fact = module.call(EXECUTE, original)["payload"]["data"]
    current = diagnostic(fact, original)
    response = module.call(DIAGNOSE, current)
    return {"sample_id": "execution_diagnosis", "evidence_kind": "synthetic_backend", "operation": DIAGNOSE,
            "request": current, "response": response, "observed_request_sha256": digest(canonical(current)),
            "expected": {"response_kind": "business", "status": "completed", "execution_calls": 0}}


def test_sample_checker_accepts_schema_and_guard_checked_diagnosis(diagnosis):
    check_sample(diagnosis, ContractRegistry())


@pytest.mark.parametrize("pointer", ["/stderr", "/test_case_results/9", "/test_case_results/-1"])
def test_sample_checker_rejects_empty_or_nonexistent_evidence(diagnosis, pointer):
    data = deepcopy(diagnosis["response"]["payload"]["data"])
    ref = data["diagnosis_report"]["evidence_refs"][0]
    ref.update(pointer=pointer, kind="log_span" if pointer == "/stderr" else "test_result")
    with pytest.raises((AssertionError, IndexError)):
        check_diagnostic_evidence(data)


def test_sample_checker_rejects_unrelated_summary(diagnosis):
    data = deepcopy(diagnosis["response"]["payload"]["data"])
    data["diagnosis_report"]["evidence_refs"][0]["summary"] = "invented cause"
    with pytest.raises(AssertionError):
        check_diagnostic_evidence(data)


def test_sample_checker_rejects_identity_mismatch(diagnosis):
    diagnosis["response"]["request_id"] = "unrelated-request"
    with pytest.raises(ValueError):
        check_sample(diagnosis, ContractRegistry())


def test_protected_rejection_recipe_keeps_export_public(diagnosis, tmp_path):
    sample = deepcopy(diagnosis)
    sample.update(sample_id="protected_diagnosis_rejected", evidence_kind="fault_injection", request_patches=PROTECTED_PATCHES)
    original = deepcopy(sample["request"])
    illegal = sample_request(sample)
    sample["observed_request_sha256"] = digest(canonical(illegal))
    module = BModule(state_dir=tmp_path / "rejection", runner=SyntheticRunner())
    from reliable_codegen.transport import TransportError
    with pytest.raises(TransportError) as error:
        module.call(DIAGNOSE, illegal)
    sample.update(response=error.value.response, expected={"response_kind": "transport_error", "error_code": "CONTRACT_INVALID"})
    assert sample["request"] == original
    check_public(sample)
    check_sample(sample, ContractRegistry())
    assert module.runner.calls == 0
