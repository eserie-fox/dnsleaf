# DNS Sync

## Provider Abstraction

`dns/base.py` 定义统一 provider 接口：

- `list_records(fqdn, record_type)`
- `apply_change(change)`
- `apply_plan(plan)`

当前 phase 1 已创建：

- `dns/alidns.py`
- `dns/cloudflare.py`

两者目前是结构完整的 stub，接口签名已定，但真实网络调用尚未实现。

## Planner

`dns/planner.py` 接收：

- 当前记录集合 `current_records`
- 期望记录 `desired_record`

输出 `SyncPlan`，其中包含一组 `PlannedChange`：

- `create`
- `update`
- `delete`
- `noop`

planner 只处理 DNS 状态差异，不负责猜测哪个 IPv6 更适合写入。

## Dry Run / Apply

- `plan` 命令：只规划，不执行
- `sync-once --dry-run`：规划并打印
- `sync-once --apply`：调用 provider 执行计划

当前 provider stub 未实现时，runner 会返回 `skipped`，避免做不透明的假同步。

## Extension Points

后续扩展 provider 时，建议只在 `dns/` 域内新增：

- provider config 字段
- provider HTTP 实现
- record 查询与变更映射

不要将 provider 细节泄漏到 discovery 或 selector。

