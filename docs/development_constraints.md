# Development Constraints

本项目第一阶段遵守以下约束：

- CLI 只做命令聚合与参数入口，不承载业务逻辑
- 包根 `__init__.py` 保持很薄
- `discovery/` 只负责候选地址采集
- `discovery/selectors.py` 负责地址筛选与决策
- `dns/` 只负责 provider 抽象与 DNS 计划，不做地址选择
- `sync/runner.py` 负责 orchestration，但保持薄
- 共享领域模型集中在 `models.py`、`discovery/models.py`、`dns/models.py`
- 外部命令调用集中在 `util/process.py`
- IP 地址归一化与基础判定集中在 `util/ip.py`
- 配置采用 formal runtime config 模式
- 第一阶段只做串行流程，不做并发
- provider 网络集成先保留结构与接口，真实 API 调用后续补全

当前实现边界：

- 已实现 planner、selector、PVE 解析、runner 与 CLI
- AliDNS / Cloudflare provider 仍是结构完整的 phase-1 stub
- 当 provider 未实现时，runner 会安全地返回 skipped，而不是盲目写入

