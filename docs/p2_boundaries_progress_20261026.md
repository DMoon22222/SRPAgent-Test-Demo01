# P2 第三步：引用生命周期、预算重放及异常交接

日期：2026-10-26，Asia/Shanghai。本轮完成 B 侧技术验证；没有提交、推送、合并或联系其他组。B 运行实现仍为固定 **0.3.1 / 441077ac5b54d122469845bce41ef62dfd0f24fe**，未修改公共 Schema、Guard、Mock 内核或 O 编排。

## 结果与变更

| 验证 | 本次实际结果 |
|---|---|
| 本地适配与 P2 定向回归 | **89 通过，0 失败，0 跳过**；包括已有 64 项与新增 25 项，单测执行后端明确为合成实现 |
| 本轮边界场景 | **25 项通过**：13 项引用、9 项预算/重放、3 项完整 O 异常运行；预期拒绝也计为符合预期 |
| 真实目标执行 | **6 次**，原 DockerRunner 执行自编固定任务；环境探针不计入目标执行 |
| 真实环境 | 镜像 `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`；各次实测 Python 3.11.5，均确认清理，未新增遗留验证容器 |
| B 运行源码 | 本轮无需修复；既有 15 份 P1 登记源码摘要、11 个公开样例和 17 项历史记录的一致性检查通过；历史运行结果未当作本轮重跑 |
| 模型/检索 | 本轮均为 0；A/C 保留 Mock，真实算法与 O 正式接收仍待验收 |

新增 [边界验证驱动](../python_service/scripts/verify_p2_boundaries.py) 和 [参数化测试](../python_service/tests/test_local_v2_p2_boundaries.py)，记录驱动、测试、配置、清单摘要及覆盖字段。运行源码、旧 P1 和前两步证据保持原样。公开结果见 [边界摘要](verification/p2/boundaries_validation.json)、[回归摘要](verification/p2/boundaries_tests.json) 和 [共同资料检查](verification/p2/boundaries_common_checks.json)。

## 引用与生命周期：13 项

通过原 LocalTransport、CallArtifactResolver、ArtifactStore 和真实 B 入口验证：正常历史与 prior 诊断消费；调用中未列出的引用拒绝；错误引用摘要、缺失记录、错任务、错 HistoryView.run_id；公开保护引用；解析器返回正文摘要或身份错误；模块异常；日志引用正常、摘要错误和缺失分支。

正常返回、业务拒绝及模块异常之后，保存的旧解析器均无法读取，绑定被清除。后续调用未恢复旧权限；修改返回记录不改变再次读取的记录，未向 B 交付 O 存储句柄。错 run 用例检查 HistoryView 与当前信封身份不一致；显式授权的同任务历史引用不被一概判为非法。

历史引用正文/身份异常返回 `blocked/AUTHORIZED_CONTEXT_UNAVAILABLE`；日志摘要错误、缺失及错 run 返回 `error/INPUT_INVARIANT_VIOLATION`，均是明确拒绝。公开保护引用由原传输边界拒绝，公开错误未包含注入的私有异常文本。

日志引用是**明确标记的 fixture**：保留真实 Docker 原观察，再以独立 fixture execution_id 和 O 登记的引用日志编码验证诊断；改写后的表示不冒充原始 Docker ExecutionResult。缺陷解析器也是 B 所有的显式注入，共同解析器未改。

## 预算、授权与持久重放：9 项

验证无执行授权、授权超出预算、预算修订错配、信封/授权/预算各自最早截止、wall_time 耗尽，以及 O 账本无执行额度。上述分支均未进入执行器；截止分支同时检查原 LocalTransport 和 B 自身入口。

重放场景只进行 **1 次真实执行**。四次返回分别覆盖同传输实例、同 B 状态目录的新模块/新传输、模拟截止后的传输缓存，以及模拟截止后的 B 持久记录。每次与原响应完全相同，保留同一 `usage_id` 和 `execution_calls=1`。O BudgetLedger 去重后只结算 1 次。过期检查用明确的未来时钟 fixture，原请求未改；新传输从未接收过的过期调用仍受启动守卫约束。

另验证同键异文在传输及 B 两层拒绝、另一 message_id 重用 call_id 被 B 拒绝、同 usage_id 改写内容被 O 账本拒绝，均未增加执行。重放用量未改为 0。

## 未知、迟到及部分失败：3 条完整 O 运行

| 场景 | O 实际终态与原因 | 执行与结算 |
|---|---|---|
| pending_outcome | human_review / USAGE_RECONCILIATION_REQUIRED | 0 次执行，用量 unknown，保留 1 次预约；同实例/跨实例重放不重做 |
| late_result | human_review / LATE_RESULT_NOT_APPLIED | 实际执行 1 次，保留合法原返回事实和已知 Usage，结算 1 次；重放继续返回迟到错误 |
| partial_diagnosis | human_review / DIAGNOSIS_FAILED | 执行 1 次；诊断用量 0，partial_result_ref 在 O 存储中解析为原事实 |

三个场景均通过原 Orchestrator 运行，A 未收到修复调用、C 未收到检索调用，未自动重试。pending 是 B 自有持久状态的崩溃 fixture；迟到由 B 返回后显式缩短传输超时触发原分支，不暂停线程或篡改事实；诊断故障只注入规则入口异常。这些是可复现技术注入，未宣称生产自然故障。

## 复现

取得本轮尚未提交的工具，在 B 的 `python_service` 目录运行：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py tests/test_local_v2_p2.py tests/test_local_v2_p2_lineage.py tests/test_local_v2_p2_boundaries.py -q -p no:cacheprovider --tb=short --basetemp <本次新建短临时目录> --junitxml .interop/p2-boundaries-tests.xml

& '.\.venv-local-v2\Scripts\python.exe' -B scripts/verify_p2_boundaries.py --docker --config ../../reliable_codegen_framework/config.b-local.p2.example.json --manifest ../../reliable_codegen_framework/modules/b/p2_handoff_manifest_v0.3.1.json
```

配置和清单可以从 O 的其他目录传入。启动前核对固定 runtime、契约/config 和镜像。临时目录使用短路径，避免 Windows 文件名长度限制。原始信封、日志、O 记录及注入前后事实保存在私有 `.interop/p2-boundaries/`，JUnit 原件不提交；Git 中仅保留脱敏摘要。重放用例共享自身 B 目录，其余场景状态独立。

后续进展：保护接收视图已按 [第四步报告](p2_protected_progress_20261026.md) 完成技术验证；以下保留第三步结束时的待办状态，最新覆盖见验收矩阵。

## 剩余工作

[验收矩阵](verification/p2/acceptance_matrix.json) 已将引用生命周期、预算重放及未知/迟到/部分失败三项标为技术通过。**完整 P2 仍未验收**：下一步补受保护最终验收在 O/A/C/B 接收视图的隔离、失败后停止修复及保护错误脱敏。

TEST-001 正式任务/测试/预算锁定、实际目标 A 模型窗口/tokenizer、消费方字段确认与 O 独立接收仍待提供。共同登记为本地未提交草案，INTB-001、TEST-001 不凭 B 自测改成完成。公共实现和固定源码未变，不因新增测试升版本。
