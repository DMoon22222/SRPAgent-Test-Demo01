# P2 第二步执行记录：多轮历史、父子版本与固定测试

日期：2026-10-26，Asia/Shanghai。按用户授权继续执行第二步；本轮新增验证驱动与测试，没有修改 B 0.3.1 运行核心、共同 Schema、Guard、Mock 或 O 调度。所有修改保留本地，未提交、推送或合并。

后续进展：引用生命周期、预算重放与异常交接已完成，见 [第三步执行报告](p2_boundaries_progress_20261026.md)。本页保留第二步当时的范围和结论，最新覆盖以验收矩阵为准。

## 新增内容

- `python_service/scripts/verify_p2_lineage.py`：使用共同原 O 与公开 LocalTransport，验证 11 个历史/谱系场景。显式 A Mock 测试适配器保留 Mock 标记，构造已说明来源的失败/修复候选；真实执行结果全部由 B Docker 后端产生。
- `python_service/tests/test_local_v2_p2_lineage.py`：相同 11 个场景的合成执行后端回归。这里的结果只证明契约和控制流，不作为真实执行事实；实际 Docker 证据单独生成。
- [本次回归摘要](verification/p2/lineage_tests.json)、[真实执行与交接摘要](verification/p2/lineage_validation.json)：保存实际数量、源码/配置摘要、镜像、运行关联、停止原因和未验证范围。

配置源仍为首步的共同交付草案；为单独核对 B 的历史与谱系，本轮显式设置 `routing_mode=no_rag`、修复上限 2，每个场景使用独立 B 状态及 O 输出目录。覆盖字段与原配置摘要分别记录，不将它们冒充未经改变的 adaptive_rag 运行。

## 实际验证结果

| 范围 | 结果 |
|---|---|
| 原有适配/样例/首步 53 项，加本次 11 项 | **64 通过，0 失败，0 跳过** |
| 真实 Docker/O 联合场景 | **11 项通过**，其中 3 条正例 accepted、8 条预期拒绝 human_review |
| 实际目标执行 | 合计 **18 次**；逐场景 O 记账与 B 用量一致，不把环境探针计为目标执行 |
| 诊断调用 | 各场景无新增执行；`execution_calls=0`，只分析提供的原事实 |
| 运行版本 | 固定 B 0.3.1 / 提交 441077a；新测试驱动为未提交工具层 |
| 镜像 | `sha256:f5845583361a42bef20999c1795e8d5bfb9ada8ac9e1f0552889e48e04840c32`；每次执行的实际镜像及容器清理确认均核对 |

### 三条多轮正例

| 场景 | 预设候选过程 | 真实执行次数 | 主要检查 |
|---|---|---:|---|
| two_execution_failures | 执行失败 → 第一修复仍失败 → 第二修复通过 | 4 | 两次诊断、两次修复、三份候选；另含独立最终验收 |
| two_static_failures | 静态失败 → 第一修复仍静态失败 → 第二修复通过 | 2 | 静态阶段没有伪造执行事实；已有静态反馈诊断不运行源码 |
| static_then_execution | 静态失败 → 第一修复产生执行失败 → 第二修复通过 | 3 | static_feedback 切换 feedback_only，前次静态诊断与当前执行诊断正确关联 |

三条正例都核对：第二次 `prior_diagnosis_ref` 指向第一次真实诊断，`prior_diagnosis_id` 一致；HistoryView 保留两轮连续摘要和父尝试；父代码 ID、摘要、当前尝试和新候选对应；公开测试 ID/正文/哈希不变，构建清单继承；本轮 FailureSource 与 B 返回的原事实一致。静态来源 `execution_result_id=null`，执行来源绑定当前候选。历史原件由 O 按不可变引用登记并在本次调用中授权解析，未从其他组私有数据库补上下文。

### 八条负例

| 场景 | 实际拒绝位置/原因 | 实际目标执行次数 |
|---|---|---:|
| wrong_parent_id | O：Patch parent artifact/hash mismatch | 1 |
| wrong_parent_hash | O：Patch parent artifact/hash mismatch | 1 |
| wrong_parent_attempt | O：Patch parent attempt mismatch | 1 |
| reused_target_attempt | O：Patch target attempt mismatch | 1 |
| wrong_preserved_test_hash | O：Patch changed the fixed test hash | 1 |
| unauthorized_build | O：Build manifest replacement is not authorized | 1 |
| stale_failure_source | B：INPUT_INVARIANT_VIOLATION | 2 |
| changed_fixed_tests | B：FIXED_TESTS_CHANGED | 1 |

前六项只执行了最初合法候选的失败测试，非法修复候选没有进入 B 执行。固定测试篡改用例虽有两次执行请求，第二次的真实 `execution_calls=0`，执行器没有运行被修改的测试。旧失败来源注入用例先产生两份真实失败事实，再将前次事实交给当前诊断；B 拒绝错配，没有自动重跑或授权第二次修复。

负例是公开且明确标记的测试适配器注入，A/C 都保持 Mock，不是自然全真实算法链。驱动没有构造假的 ExecutionResult，也没有关闭共同校验。

## 测试过程与复现

第一次合成后端运行是 10 通过、1 失败：复用目标尝试编号的用例预期较后的“必须产生新尝试”错误，而 O 实际先由目标上下文一致性校验拒绝。读取实际 O 停止原因后，将测试预期修正为 `Patch target attempt mismatch`。未修改 Guard、O 或 B，也未取消拒绝断言。该前序结果和原因保留在测试摘要中。

在 B 的 `python_service` 目录，本次实际执行：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B -m pytest tests/test_local_v2.py tests/test_local_v2_samples.py tests/test_local_v2_p2.py tests/test_local_v2_p2_lineage.py -q -p no:cacheprovider --tb=short --basetemp <本次独立短目录> --junitxml .interop/p2-lineage-tests.xml

& '.\.venv-local-v2\Scripts\python.exe' -B scripts/verify_p2_lineage.py --docker --config ../../reliable_codegen_framework/config.b-local.p2.example.json --manifest ../../reliable_codegen_framework/modules/b/p2_handoff_manifest_v0.3.1.json
```

原始输入、适配前/后响应、被注入前/后的请求以及 O 记录只存 `.interop/p2-lineage/`。受保护最终验收原件不进入 Git；公开摘要只保留必要的关联、计数和检查结果。公开记录经过可见性 Guard 检查。首步证据、P1 历史结果均未覆盖或改写。

共同登记草案已追加第二步证据，并通过协作视图生成、元数据校验及文档检查，见 [共同检查记录](verification/p2/lineage_common_checks.json)。这些检查不代表共同远端已更新或 O 已签收。

## 验收边界与下一步

[当前验收矩阵](verification/p2/acceptance_matrix.json) 的多轮历史、父关系与固定测试两项已有本次技术证据。完整 P2 仍未验收：

- 引用的拒绝/越权/失效完整矩阵尚未执行；本轮正常历史引用可解析不等于引用生命周期矩阵全部通过。
- 重放去重结算、未知/迟到/部分完成，以及接收端保护视图的联合矩阵仍待执行；本轮执行计数一致不能替代这些分支。
- TEST-001、实际目标 A 上下文/tokenizer、消费方确认与 O 独立接收仍待提供，不补造元数据。
- 共同登记与 P2 工具仍是本地草案，INTB-001 未据本组自测改为 done。

下一步按计划补引用生命周期和预算/幂等联合验证。本轮没有发现需要修复的 B 运行缺陷，因此实现版本仍为 0.3.1。
