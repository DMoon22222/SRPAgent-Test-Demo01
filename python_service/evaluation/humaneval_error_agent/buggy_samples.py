from __future__ import annotations

DEFAULT_TASK_IDS = [
    "HumanEval/0",
    "HumanEval/1",
    "HumanEval/2",
    "HumanEval/3",
    "HumanEval/4",
]

BUG_TEMPLATES = [
    {
        "suffix": "compile_error",
        "bug_kind": "COMPILE_ERROR",
        "completion": "    return None\n    if\n",
        "expected_errorType": "COMPILE_ERROR",
        "expected_failedStage": "COMPILE",
        "expected_errorSubtype": "SYNTAX_ERROR",
        "expected_needRetrieval": False,
        "description": "人为构造 Python 语法错误，期望在编译/语法检查阶段失败。",
    },
    {
        "suffix": "divide_by_zero",
        "bug_kind": "RUNTIME_ERROR",
        "completion": "    return 1 / 0\n",
        "expected_errorType": "RUNTIME_ERROR",
        "expected_failedStage": "RUNTIME",
        "expected_errorSubtype": "DIVIDE_BY_ZERO",
        "expected_needRetrieval": False,
        "description": "函数运行时触发除零异常。",
    },
    {
        "suffix": "wrong_answer",
        "bug_kind": "WRONG_ANSWER",
        "completion": "    return None\n",
        "expected_errorType": "WRONG_ANSWER",
        "expected_failedStage": "TEST",
        "expected_errorSubtype": "ALGORITHM_ERROR",
        "expected_needRetrieval": False,
        "description": "函数能运行，但返回结果明显不符合 HumanEval 测试要求。",
    },
    {
        "suffix": "timeout",
        "bug_kind": "TIME_LIMIT_EXCEEDED",
        "completion": "    while True:\n        pass\n",
        "expected_errorType": "TIME_LIMIT_EXCEEDED",
        "expected_failedStage": "RUNTIME",
        "expected_errorSubtype": "INFINITE_LOOP",
        "expected_needRetrieval": False,
        "description": "函数进入无限循环，期望触发执行超时。",
    },
    {
        "suffix": "dependency_missing",
        "bug_kind": "API_MISUSE",
        "completion": "    import non_existing_library_xyz\n    return None\n",
        "expected_errorType": "API_MISUSE",
        "expected_failedStage": "RUNTIME",
        "expected_errorSubtype": "DEPENDENCY_MISSING",
        "expected_needRetrieval": True,
        "description": "人为补充依赖缺失样本，用于测试 needRetrieval 决策。",
    },
]


def build_buggy_samples(task_ids: list[str] | None = None) -> list[dict]:
    selected_task_ids = task_ids or DEFAULT_TASK_IDS
    samples: list[dict] = []
    for task_id in selected_task_ids:
        task_slug = task_id.replace("/", "_")
        for template in BUG_TEMPLATES:
            sample = dict(template)
            sample.update(
                {
                    "sample_id": f"{task_slug}_{template['suffix']}",
                    "task_id": task_id,
                }
            )
            samples.append(sample)
    return samples
