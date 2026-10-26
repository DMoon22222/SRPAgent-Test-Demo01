# P2 接收核对单（待接收方填写）

准备日期：2026-10-26。此表为本地交接准备，未发送消息；接收人、时间和意见待实际提供。B runtime 为 0.3.1，固定提交 `441077ac5b54d122469845bce41ef62dfd0f24fe`。

## 候选内容核对

1. 核对 `docs/integration/p2_delivery_files.json` 的文件摘要，以及 `docs/verification/p2/delivery_validation.json` 的归档 SHA-256。工具仍是未提交快照，实际共享前需记录对应提交或受控制品标识。
2. 核对候选 ZIP 中 `DELIVERY.json` 的 65 份载荷摘要、固定 B wheel SHA 与框架快照提交。保持 A/C 的 Mock 声明和 B 独立沙箱边界。
3. 使用 Python >=3.11，按 `b/python_service/requirements-local-v2.lock` 准备兼容依赖。若复用已有环境，明确记录复用范围。
4. 在解压后的候选目录执行：

```powershell
python -m pip install --no-deps --no-index --no-compile --target installed_b wheels/srp_b_local-0.3.1-py3-none-any.whl
python -I -B b/python_service/scripts/smoke_p2_consumer.py --bundle-root .
```

此烟测核对归档、wheel 加载来源、真实静态检查和规则诊断，目标执行及模型调用均为 0。安装目标须为新的目录。完整 Docker/四步复验按 B 交付文档，从固定 Git 检出及已共享工具运行；分别记录原始事实与复验结果，不改写旧证据日期。

## 正式材料与意见

| 对接组 | 应提供/核对 | 实际材料或意见 |
|---|---|---|
| O / TEST-001 | 固定任务 ID、公开/最终测试 ID/哈希、知识快照、预算与授权政策、受控原件位置 | 待提供 |
| A/O | 实际模型窗口、context_profiles、tokenizer 标识/版本及核对依据 | 待提供 |
| A/C/O | FailureSource、DiagnosisReport、ExecutionContext、历史/引用和保护边界的消费意见 | 待提供 |
| O | 独立安装与运行记录、关联 ID、实际用量/终态、接收人/日期及结论 | 待提供 |

四项仍与 `p2_external_dependencies.json` 一致，provided_ref 保持 null。不得把演示 tokenizer、B 自测、空白模板或待填意见当作已接收材料。真实 A/C 算法链另按 P3/M1 验收。
