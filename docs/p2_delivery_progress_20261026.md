# P2 第五步：候选交付包与证据完整性核对

日期：2026-10-26，Asia/Shanghai。完成本地候选包准备及 B 侧接收烟测，未提交、推送、合并或发送跨组消息。运行实现仍为固定 **0.3.1 / 441077ac5b54d122469845bce41ef62dfd0f24fe**。

后续发布：工具快照已固定并推送，见 [发布说明](p2_publication_progress_20261026.md)。本页保留第五步组装时的原始状态，当前发布事实以新增发布记录为准。

## 实际结果

| 检查 | 本次结果 |
|---|---|
| 定向回归 | **105 通过、0 失败、0 跳过**；原 95 项加 10 项交付工具完整性测试，均用非执行型合成后端 |
| 当前文件与既有证据 | **46 份文件**的字节摘要一致；四步 8/11/25/6 项既有记录与当前对应驱动/测试一致 |
| 候选归档 | **66 个条目**；白名单公开材料、固定 B wheel、16 份固定框架依赖快照及接收说明 |
| 独立目录烟测 | 离线安装固定 B wheel，确认实际从安装目标加载 B、从固定框架快照加载 O 依赖；真实 AST 和规则诊断通过 |
| Git、模型与目标执行 | 接收烟测无需 `.git`，本轮未启动 Docker、模型或目标源码执行；原 Docker 结果保持历史运行日期 |
| 正式状态 | blocked；工具与登记仍未提交，未收到 O 独立接收意见 |

证据：[完整性及打包摘要](verification/p2/delivery_validation.json)、[105 项回归摘要](verification/p2/delivery_tests.json)、[共同登记检查](verification/p2/delivery_common_checks.json)。文件清单见 [p2_delivery_files.json](integration/p2_delivery_files.json)。归档 SHA-256、清单摘要与安装来源检查结果均在打包摘要中。

独立目录使用了已有 `.venv-local-v2` 的依赖；只对固定 B wheel 作离线目标安装。该记录证明移除原源码目录和 Git 检出位置依赖后可加载公开入口，未声称重新安装全部依赖或代表 O 签收。首次 pip 目标安装遇到沙箱临时目录 WinError 5，按相同离线流程在允许的权限下重跑通过；未修改 B 来绕过错误。

## 修改与核对范围

- 新增 `scripts/check_p2_delivery.py`：只读检查 46 份文件、P1 固定源码、四步证据对当前工具的摘要、技术矩阵及四项正式依赖；不改写记录、不重跑历史验证。
- 新增 `scripts/package_p2_delivery.py`：只从明确白名单构造归档，检查既有 wheel 原 SHA 和运行源码；框架依赖从固定 `55e9f3a945d58df60bd59ab8c57f206e3ebb67bd` 的 Git 对象读取，未混入共同元数据草案。路径拒绝穿越、私有目录和凭据路径；归档输出不覆盖同名文件，条目顺序及时间固定以支持一致性核对。
- 新增 `scripts/smoke_p2_consumer.py`：在解压目录通过安装 wheel 的实际路径加载工厂，验证全归档清单和静态/诊断入口，检查未导入旧 FastAPI/A2A/MCP 服务。
- 新增 10 项工具测试，覆盖只读性、文件修改、旧证据与新摘要不一致、技术通过误写正式通过、私有文件混入、越界路径、归档确定性及覆盖保护。
- 补 `.gitattributes`：固定其自身为 LF，P2 机器清单、配置和 JSON 证据保留原始字节，避免 Windows 检出转换破坏摘要。

历史 95 项受保护视图阶段回归仍保留在 `protected_tests.json`。本轮 105 项回归另存新记录；只读检查输出的 `latest_recorded_tests=95` 指其核对的四步历史记录，当前新增回归见 `delivery_tests.json`。未改动 B 核心、共同 Schema、Guard、Mock 或 O 调度。

## 使用与交接

在 B `python_service` 目录运行只读检查：

```powershell
& '.\.venv-local-v2\Scripts\python.exe' -B scripts/check_p2_delivery.py
```

归档保存在私有 `.interop/p2-delivery/` 下的本轮 candidate 目录，未加入 Git；该 ZIP 仅包含上述白名单材料，源目录中的运行日志、隐藏测试原件、`.env`、个人文件和 SQLite 均未打入。归档内 `DELIVERY.json` 校验 65 份载荷，归档自身另有 SHA-256；SHA 用于内容一致性核对，发布身份仍需固定工具提交及实际共享记录。

解压后按 `RECEIVER.txt` 或 [接收核对单](integration/p2_receiver_checklist.md) 执行 Git-free 烟测。四步历史 Docker 驱动的 CLI 版本旁录依赖固定 Git 检出；完整重跑需取得固定 runtime、已评审共享的工具与锁定镜像，在相应检出环境运行。当前压缩包支持无 Git 的完整性检查及静态接入烟测，不把本轮零 Docker 执行写成全矩阵重跑。

本轮依赖/意见核对单仅准备在本地，没有发送给其他人。[P2 交付草案](p2_handoff_20261030.md) 已追加候选包索引。下一阶段是固定并共享本轮工具，再由 O/消费方提供正式锁定材料和实际核验记录；正式 INTB-001 不因本地候选包存在而变为完成。
