# P2 第四步：受保护最终验收与各接收视图

日期：2026-10-26，Asia/Shanghai。本轮完成 B 侧技术验证，运行实现保持 **0.3.1 / 441077ac5b54d122469845bce41ef62dfd0f24fe**。新工具、证据和共同登记均为本地未提交草案；未推送、合并或给其他组发送消息。

## 本次结果与修改

| 项目 | 实际结果 |
|---|---|
| 本地适配与 P2 回归 | **95 通过，0 失败，0 跳过**；原 89 项加新增 6 项，单测使用非执行型合成后端 |
| 真实 B / 原 O 联合运行 | **6 条流程全部符合预期**，包含最终通过、最终失败及四种显式故障注入 |
| 真实目标执行 | **18 次**；每条含初始公开失败、修复后的公开通过、封版后的最终验收各一次 |
| 接收视图 | A 生成/修复、C 决策、B 公开诊断及 O 公开事件、摘要和可达制品均检查；保护标记命中 **0** |
| 容器 | 所有执行均确认清理，本轮未新增遗留验证容器 |
| 实现与契约 | B 核心、共同 Schema、Guard、Mock 内核和 O 编排均未改；P1 登记的 15 份源码摘要一致性检查通过 |

新增 [保护视图验证驱动](../python_service/scripts/verify_p2_protected.py) 和 [六项参数化回归](../python_service/tests/test_local_v2_p2_protected.py)。记录源码、测试、所复用驱动、配置及清单摘要；旧 P1 和前三步证据保持原样。详见 [真实执行摘要](verification/p2/protected_validation.json)、[回归摘要](verification/p2/protected_tests.json) 和 [共同资料检查](verification/p2/protected_common_checks.json)。

## 六条完整流程

| 场景 | O 终态 | 停止原因 | O 已结算执行 / 保留预约 |
|---|---|---|---|
| hidden_pass | accepted | 无 | 3 / 0 |
| hidden_failure | stopped | FINAL_ACCEPTANCE_FAILED | 3 / 0 |
| protected_business_error | human_review | PROTECTED_OPERATION_FAILED | 3 / 0 |
| protected_transport_error | human_review | MODULE_OPERATION_REJECTED | 3 / 0 |
| protected_module_exception | human_review | OUTCOME_UNKNOWN | 2 / 1 |
| protected_late_result | human_review | LATE_RESULT_NOT_APPLIED | 3 / 0 |

六条均经原 Orchestrator 和 LocalTransport 执行。A/C 保留 Mock 标记，C 在公开失败后的决策阶段确实收到调用；每条只进行一次公开修复。最终 B 请求位于 `sealed → final_evaluating` 之后，与上一公开执行使用相同代码、构建与政策，固定 final_hidden 正文和摘要未改，原 B 事实保留 restricted/final_acceptance 和逐测试 oracle。最终 B 调用之后没有任何模块续调，因此失败不会回流到诊断、检索或修复。

业务和传输错误是明确标记的 O 侧 fixture：先保留真实最终执行，再返回带私有错误码、正文、details、partial/cause 引用的合法错误。原错误可在 O 受控记录中核对，partial_ref 解析为原执行事实；公开 `module_errors` 只保留 `PROTECTED_OPERATION_FAILED` 和 `final_acceptance` 阶段。

模块异常 fixture 在 B 返回后抛出异常，原传输只能确认结果未知。虽然 B 所有的执行观察器知道已运行三次，O 只结算有合法 Usage 的前两次，并保留最后一次预约；没有把未知按零结算或主动重跑。迟到 fixture 在真实 B 返回后触发原传输超时分类，合法事实和 Usage 私存，停止后续模块调用。

## 实际核对的可见性边界

运行时生成合成最终测试和临时唯一标记，只用于当前私有 fixture，不使用或补造 TEST-001 的真实隐藏任务。检查同时采用结构 Guard 与标记检索，覆盖正文、测试名称、保护制品/执行 ID、私有错误及部分事实引用。具体标记、测试正文、日志和逐测试结果不写入公开 JSON 或 Git。

- **A/C 实际接收端**：在原传输校验之后观察模块入口，核对完整公开请求及 A/C 响应，未携带保护内容。
- **B 公开诊断**：只收到公开失败事实；最终失败后无诊断。额外向 B 直接入口和 LocalTransport 各尝试一次公开诊断隐藏事实，均明确拒绝。
- **O 公开视图**：从公开 events 及 EvaluationReport 出发，经已验证存储 API 遍历可达制品；逐个检查可见性及标记。此范围不等于枚举全部私有磁盘文件，也不是对恶意同进程代码的内存隔离证明。
- **保护存储及拒绝错误**：默认存储读取隐藏测试和 partial/cause 引用被拒；显式受控读取可核对原件。另测试向 A 公开生成输入塞入隐藏测试、向 C 公开历史塞入保护引用；连同两项 B 拒绝，共四项负例均未进入接收模块或新增执行，返回错误无保护标记。

本次实际镜像为 `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`。驱动核对每次事实的镜像及清理确认，并核对真实逐测试记录中的临时测试名称，证明执行了本次固定合成最终测试。

## 复现与证据

取得本轮工具和固定配置，在 B `python_service` 目录执行：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py tests/test_local_v2_p2.py tests/test_local_v2_p2_lineage.py tests/test_local_v2_p2_boundaries.py tests/test_local_v2_p2_protected.py -q -p no:cacheprovider --tb=short --basetemp <本次新建短目录> --junitxml .interop/p2-protected-tests.xml

& '.\.venv-local-v2\Scripts\python.exe' -B scripts/verify_p2_protected.py --docker --config ../../reliable_codegen_framework/config.b-local.p2.example.json --manifest ../../reliable_codegen_framework/modules/b/p2_handoff_manifest_v0.3.1.json
```

配置和清单可从 O 的其他目录传入。真实与注入前后的信封、接收端记录及 O 原件留在 `.interop/p2-protected/`，JUnit 也私存。报告中的摘要来自本轮原件；合成后端单测不代替真实执行。启动前核对既定 runtime、契约/config 和镜像；覆盖的超时、路由、状态目录和合成测试分别记录。

## 当前状态

[验收矩阵](verification/p2/acceptance_matrix.json) 中 B 可自行完成的 P2 技术项均已有证据，交付汇总见 [10 月 30 日 P2 草案](p2_handoff_20261030.md)。正式 P2 仍为 **blocked**：TEST-001 正式材料、实际 A 上下文/tokenizer、消费方字段确认和 O 独立接收均待提供。INTB-001、TEST-001 保持实际登记状态，未凭 B 自测改为完成。
