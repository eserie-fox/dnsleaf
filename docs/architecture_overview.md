# Architecture Overview

`arbor-ddns` 按三层结构组织，而不是将发现、选择、同步混在一起：

1. `inventory`
   - 提供目标列表
   - 每个条目至少描述 `kind`、`id`、`fqdn`、`provider`、`selection_policy`、`enabled`

2. `discovery`
   - 从 PVE 采集 IPv6 候选地址
   - 当前包含：
     - `pve_lxc.py`: `pct exec <ctid> -- ...`
     - `pve_qga.py`: `qm agent <vmid> network-get-interfaces`
   - 只返回候选地址，不写 DNS，也不在 backend 内拍脑袋决定最终地址

3. `selection`
   - 位于 `discovery/selectors.py`
   - 对候选地址做归一化、过滤、优先级判断与歧义处理
   - 输出 `SelectionResult`

4. `dns`
   - `dns/base.py` 定义 provider 接口
   - `dns/planner.py` 对比 `desired` 与 `current`
   - 输出 `create / update / delete / noop`

5. `sync`
   - `sync/runner.py` 串起：
     - inventory
     - discovery
     - selection
     - current DNS lookup
     - planner
     - apply

主流程：

`inventory -> discovery -> selection -> planner -> apply`

边界约束：

- CLI 只做入口与输出
- runner 负责 orchestration，但保持薄
- discovery 不写 DNS
- DNS provider 不负责地址选择
- selector 不关心 provider 细节

