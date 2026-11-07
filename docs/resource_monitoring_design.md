# B Docker 执行资源观测

原 Runner 已有墙钟、超时、输出保护、OOM 状态和容器清理，但 CPU/内存为 null。本轮在 [sandbox.py](../python_service/srp_b/sandbox.py) 接入 [resource_monitor.py](../python_service/srp_b/resource_monitor.py)，继续使用原生 Docker 和现有镜像。公共 ResourceUsage 字段复用，细节写入 `ResourceUsage.extensions.srp_b.resource_monitoring`。

## 数据来源和范围

| 指标 | 口径 |
|---|---|
| wall_time_ms | 宿主 monotonic 包围目标 docker start --attach；包含客户端延迟，排除探针/清理，不称为精确目标 CPU 时间 |
| cpu_time_ms | Engine `cpu_stats.cpu_usage.total_usage` 累计纳秒换算毫秒，取观测窗口最高累计值，可能遗漏最后一次采样后的 CPU 尾部 |
| peak_memory_bytes | 观测到的 `memory_stats.usage` 最大值；有正的内核 max_usage 时合并取大；包含容器内存记账/缓存，不是 RSS 或保证覆盖全生命周期的精确峰值 |
| memory_limit_bytes / cpu_limit | 原 ExecutionPolicy 和未改变的 create 参数；另列 stats 实际返回的 memory limit |
| oom_killed / exit_code | 原 Docker inspect .State；运行中或未观测时 null，OOM 与普通非零退出分开 |
| timeout / output_limit_reached | 原 attach 超时/溢出事实 |
| resource_limit_exceeded | 已观察到 OOM、超时或输出硬限时 true；已退出且均未发生时 false，否则 null。CPU 节流另列 cpu_throttled，不据节流宣称程序被资源终止 |

尚未取得样本时 CPU/内存为 null；观察到真实 0 与未采集不同。只有墙钟可用时总体可为 estimated，具体不可用字段和原因仍保留。`workflow_wall_time_ms` 保存准备至清理的旧工作流时间口径，避免与新的目标时间混淆。

## 采集和回收

请求间隔 200ms，实际时间戳和间隔另存，API 延迟可能让采样更稀疏。仅保留最后 64 个样本，累计最大值覆盖停止前所有成功采样，避免长任务在第 64 个样本后停止观测。sample_count 是总成功采样数，retained_sample_count 是实际保留数。短任务可能在首样本前退出；快速 OOM 也可能在两个样本之间发生，不能用较低的采样峰值否定 inspect 的 OOMKilled。

监控在宿主后台线程发起只读 Engine stats，不向目标注入额外进程。仅支持当前本地 npipe/Unix endpoint；TCP/SSH 端点明确 unavailable，不开放新的网络访问。Windows 管道 I/O 由受信本地 Python stdlib 辅助进程包围，使用 isolated 模式和固定脚本，只传受限容器名；单次查询 1s 超时、响应上限 1MiB，超时 kill/reap。容器先按原机制清理，之后取消当前辅助查询并有界 join，避免监控等待延后容器清理。异常仅成为监控元数据，不覆盖执行结果；有 cleanup_confirmed 字段核实线程退出。

本机 stdio 代理预探测失败，因此实际采用既有本地 Docker Desktop Linux Engine 管道。首次冷启动或短任务可能没有样本，报告会保留真实 null，不补测后冒充原始值。本轮未测远程 daemon，其他平台应复核本地 socket 的权限和可用性。

## 安全与验证

原 validate_policy/create_args/_cleanup、输出上限和有界命令实现保持不变：pull=never、network none、root/workspace read-only、256MiB/1 CPU/16 PID 的测试策略、非 root、drop ALL、no-new-privileges、原超时和输出限制。没有创建特权容器、挂入 Docker socket、扩大写权限或安装新运行依赖。

[新增监控测试](../python_service/tests/test_phase1_resource_monitor.py)覆盖计数换算、缺失/负数/零、采样窗口、保留上限、异常、远程端点拒绝、超时辅助回收和原生 Runner 的监控 start/stop 故障隔离。单元测试使用合成 stats/命令，不是物理 Docker。

[真实驱动](../python_service/scripts/phase1_docker_smoke.py)复用旧 4 场景，增加 2 秒 CPU 循环、24MiB 分配保持及 512MiB 分配触发原 256MiB 限制；均是自编安全代码。最终结果见 [最终记录](verification/phase1_docker_smoke_final.json)：7 次目标执行、8 项含清理检查，另有独立 runtime 探针容器，不把探针计入目标执行。没有拉取新镜像。首轮及中间核验报告单独保留，不能代替最后清理顺序修正后的源码快照。

采样 CPU/内存不是精确 profiling，不支持进程级归因或统计概率。监控本身有少量宿主开销；不能证明对任意大规模并发、任意外部自定义监控器都无性能影响。本轮验证的是内置有界客户端及自编场景。
