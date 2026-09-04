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
    "HumanEval/4": "    return 0.0\n",
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

COMPLEX_LOGIC_BUGS_BY_TASK = {
    "HumanEval/0": {
        "suffix": "logic_missing_abs",
        "completion": COMPLEX_LOGIC_COMPLETION_BY_TASK["HumanEval/0"],
        "expected_root_cause_keywords": ["abs", "absolute", "distance", "距离", "绝对值"],
        "expected_repair_keywords": ["abs", "absolute", "绝对值"],
        "logic_bug_description": "距离判断时没有取绝对值，只判断了单方向差值。",
    },
    "HumanEval/1": {
        "suffix": "logic_bad_split",
        "completion": "    return [group.replace(' ', '') for group in paren_string.split() if group.strip()]\n",
        "expected_root_cause_keywords": ["split", "space", "spaces", "balanced", "group", "空格", "分组", "括号"],
        "expected_repair_keywords": ["depth", "balance", "忽略空格", "嵌套", "逐字符"],
        "logic_bug_description": "错误地用空格 split 分组，无法处理无空格连接或组内空格的括号串。",
    },
    "HumanEval/2": {
        "suffix": "logic_wrong_round",
        "completion": "    return number - round(number)\n",
        "expected_root_cause_keywords": ["round", "integer", "floor", "decimal", "小数", "整数"],
        "expected_repair_keywords": ["int", "floor", "number - int", "整数部分", "小数部分"],
        "logic_bug_description": "使用 round 而不是向下取整/整数部分，导致小数部分计算错误。",
    },
    "HumanEval/3": {
        "suffix": "logic_final_balance_only",
        "completion": "    balance = sum(operations)\n    return balance < 0\n",
        "expected_root_cause_keywords": ["running", "cumulative", "any point", "intermediate", "balance", "过程", "任意时刻"],
        "expected_repair_keywords": ["iterate", "running", "cumulative", "每一步", "余额", "循环"],
        "logic_bug_description": "只检查最终余额是否为负，没有检查过程中任意时刻是否跌破 0。",
    },
    "HumanEval/4": {
        "suffix": "logic_missing_abs_deviation",
        "completion": (
            "    mean = sum(numbers) / len(numbers)\n"
            "    return sum(x - mean for x in numbers) / len(numbers)\n"
        ),
        "expected_root_cause_keywords": ["abs", "absolute", "deviation", "mean", "平均", "绝对"],
        "expected_repair_keywords": ["abs", "absolute", "绝对值", "abs(x - mean)"],
        "logic_bug_description": "计算平均绝对偏差时漏掉 abs，正负偏差相互抵消。",
    },
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


def build_buggy_samples(task_ids: list[str] | None = None, problems: dict | None = None) -> list[dict]:
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
                    "manualReview": "",
                }
            )
            samples.append(sample)
    samples.extend(build_complex_logic_bug_samples(problems or {}, selected_task_ids))
    return samples


def build_complex_logic_bug_samples(problems: dict, task_ids: list[str] | None = None) -> list[dict]:
    selected_task_ids = task_ids or DEFAULT_TASK_IDS
    samples: list[dict] = []
    for task_id in selected_task_ids:
        task_slug = task_id.replace("/", "_")
        spec = COMPLEX_LOGIC_BUGS_BY_TASK.get(task_id)
        if spec is None:
            samples.append(_skipped_complex_sample(task_slug, task_id, "No complex logic bug template for this task."))
            continue

        problem = problems.get(task_id) if problems else None
        if problem and problem.get("entry_point") not in problem.get("prompt", ""):
            samples.append(_skipped_complex_sample(task_slug, task_id, "Prompt/entry_point mismatch for complex logic bug."))
            continue

        sample = {
            "sample_id": f"{task_slug}_{spec['suffix']}",
            "task_id": task_id,
            "bug_kind": "LOGIC_BUG_COMPLEX",
            "completion": spec["completion"],
            "expected_errorType": "WRONG_ANSWER",
            "expected_failedStage": "TEST",
            "expected_errorSubtype": "ALGORITHM_ERROR",
            "expected_needRetrieval": False,
            "expected_root_cause_keywords": spec["expected_root_cause_keywords"],
            "expected_repair_keywords": spec["expected_repair_keywords"],
            "logic_bug_description": spec["logic_bug_description"],
            "description": spec["logic_bug_description"],
            "manualReview": "",
        }
        samples.append(sample)
    return samples


def _skipped_complex_sample(task_slug: str, task_id: str, reason: str) -> dict:
    return {
        "sample_id": f"{task_slug}_logic_complex_skipped",
        "task_id": task_id,
        "bug_kind": "LOGIC_BUG_COMPLEX",
        "completion": "",
        "expected_errorType": "WRONG_ANSWER",
        "expected_failedStage": "TEST",
        "expected_errorSubtype": "ALGORITHM_ERROR",
        "expected_needRetrieval": False,
        "expected_root_cause_keywords": [],
        "expected_repair_keywords": [],
        "logic_bug_description": "",
        "manualReview": "",
        "skip_reason": reason,
    }
