from __future__ import annotations

DEFAULT_TASK_IDS = [
    "HumanEval/0",
    "HumanEval/1",
    "HumanEval/2",
    "HumanEval/3",
    "HumanEval/4",
]

WRONG_ANSWER_COMPLETION_BY_TASK = {
    "HumanEval/0": "    return False\n",
    "HumanEval/1": "    return []\n",
    "HumanEval/2": "    return 0\n",
    "HumanEval/3": "    return ''\n",
    "HumanEval/4": "    return []\n",
}

COMPLEX_LOGIC_COMPLETION_BY_TASK = {
    "HumanEval/0": (
        "    for idx, elem in enumerate(numbers):\n"
        "        for idx2, elem2 in enumerate(numbers):\n"
        "            if idx != idx2:\n"
        "                if elem - elem2 < threshold:\n"
        "                    return True\n"
        "    return False\n"
    ),
}

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
        "completion": "",
        "completion_by_task": WRONG_ANSWER_COMPLETION_BY_TASK,
        "expected_errorType": "WRONG_ANSWER",
        "expected_failedStage": "TEST",
        "expected_errorSubtype": "ALGORITHM_ERROR",
        "expected_needRetrieval": False,
        "description": "函数能运行，但返回结果明显不符合 HumanEval 测试要求。",
    },
    {
        "suffix": "logic_no_abs",
        "bug_kind": "WRONG_ANSWER",
        "completion": "",
        "completion_by_task": COMPLEX_LOGIC_COMPLETION_BY_TASK,
        "expected_errorType": "WRONG_ANSWER",
        "expected_failedStage": "TEST",
        "expected_errorSubtype": "ALGORITHM_ERROR",
        "expected_needRetrieval": False,
        "description": "复杂逻辑错误：距离判断没有使用 abs，规则层只能识别 AssertionError，Agent 应解释算法根因。",
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
            completion_by_task = sample.pop("completion_by_task", None)
            if completion_by_task is not None:
                sample["completion"] = completion_by_task.get(task_id, "")
                if not sample["completion"]:
                    sample["skip_reason"] = "No type-safe wrong-answer completion for this task."
            sample.update(
                {
                    "sample_id": f"{task_slug}_{template['suffix']}",
                    "task_id": task_id,
                }
            )
            samples.append(sample)
    return samples
