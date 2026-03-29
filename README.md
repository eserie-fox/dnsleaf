# arbor-ddns

`arbor-ddns` 是一个轻量、独立、可测试的 Python 工具，用于在 PVE 宿主上发现
指定 LXC / Linux VM 的 IPv6 候选地址，按明确策略选出一个适合 AAAA 记录的目标地址，
然后规划并执行 DNS 同步。

项目当前第一阶段已实现：

- PVE LXC discovery backend
- PVE QGA discovery backend
- 可独立测试的 IPv6 selector
- DNS planner 与 provider 抽象
- 串行 sync runner
- Typer CLI
- 配置、文档与测试骨架

## 安装

```bash
uv sync --extra dev
```

## 运行

```bash
uv run arbor-ddns --help
uv run arbor-ddns discover lxc 101
uv run arbor-ddns discover vm 201
uv run arbor-ddns plan
uv run arbor-ddns sync-once --dry-run
```

## 测试

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

更多说明见 [docs/index.md](docs/index.md)。
