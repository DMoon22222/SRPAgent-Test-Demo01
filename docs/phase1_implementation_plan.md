# B 第一阶段实施计划与兼容性审查

起点：2026-11-07，分支 `b/local-v2-adapter`，HEAD `b4a1684`。上一轮加固已发布；本轮结束保持未提交、未推送、未合并。起始工作区清单与旧文件摘要见 [保护快照](verification/phase1_workspace_inventory.json)。

## 顺序

1. 固定 40 条诊断候选和初标规范，保存基线。仅使用公开反馈，不读取或利用隐藏最终验收材料；所有 Codex 初标为 pending_review。
2. 新增有界 Python Traceback 解析器和证据关联，集成至 B 自身诊断及已有执行 traceback 字段。
3. 新增分类/根因分离的启发式置信度规则，保留传统 RuleDecision 及旧服务行为，使用 DiagnosisReport.extensions.srp_b 记录依据。
4. 为原生 Docker Runner 增加只读旁路资源监控，使用现有引擎、现有镜像和原安全参数。采集口径与不可用状态必须明确。
5. 运行原 103 项及新增测试、旧 16 条开发集、新候选集、Hypothesis、Ruff 和自编真实 Docker 场景，保留失败与范围限制。
6. 完善设计、基线/最终报告及机器汇总，核对旧报告、用户文件和共同规范未被改写。

## 计划变更位置

- 新增：srp_b 下的内部解析、置信度及资源监控模块；对应 phase1 测试和有界属性；独立候选集、标注规范和评分驱动；独立 Docker 验证驱动；本轮设计及验证文档。
- 集成：`srp_b/diagnosis.py`、`srp_b/sandbox.py`，必要时修正 `srp_b/claude.py` 中模型解释的置信度旁录；不增加公开工厂参数或业务操作。
- 不修改：旧数据集和测试基线、历史评测/验证记录、共同规范、公共 Schema、A/C/O 业务代码、Docker 安全参数、运行时依赖锁。

## 兼容性重点

- Schema 已有 `DiagnosisReport.extensions`、`ExecutionResult.extensions`、`ResourceUsage.extensions` 和 `ExecutionResult.traceback`。新增内部信息使用这些位置，沿用 StackFrame/SourceLocation 形状。
- 旧 `confidence` 保持 number/null，解释为根因启发式评分；分类置信度另存扩展。数值降低是本轮受控的语义增强，旧分类和下一动作的非预期变化需要回归检查。
- 原始 FailureSource 保持不变；解析结果明确标为派生事实，有摘要和原始引用，不能替代执行观察。
- 多种不相关异常或状态冲突允许 unknown/信息收集；真实异常链以终端异常及链关系表达，不简单对全文关键词排序。
- Docker 短任务可能在首次采样前退出。CPU 累计计数及内存采样只报告实际观察的范围，不把未观测阶段补零，也不把采样最大值称为完整生命周期精确峰值。
- Windows Docker stdio 桥探测返回空的 HTTP 500；现有本地命名管道的只读 API 探测成功。资源通道需要使用有超时、可回收的受信辅助进程，不添加容器权限。
- 0.3.1 精确快照检查只适用于其固定历史版本；不能修改旧清单使它在当前 0.4.0 工作区“通过”。
