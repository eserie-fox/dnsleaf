# Discovery

## Backends

当前 discovery 域包含两个 backend：

- `pve_lxc.py`
  - 通过 `pct exec <ctid> -- sh -lc "ip -6 -o addr show"` 采集地址
  - 解析文本输出为 `AddressCandidate`

- `pve_qga.py`
  - 通过 `qm agent <vmid> network-get-interfaces` 采集地址
  - 解析 JSON 输出为 `AddressCandidate`

backend 责任只有一个：

- 产出候选地址

backend 不负责：

- 选择最终地址
- 写 DNS

## Candidate Model

`AddressCandidate` 至少包含：

- `interface`
- `address`
- `prefix_length`
- `source`
- `scope`
- `flags`

这让 selector 与日志层能保留足够的排障信息。

## Default Selector Rules

默认 selector 位于 `discovery/selectors.py`，规则为：

1. 排除 loopback `::1`
2. 排除 link-local `fe80::/10`
3. 排除 ULA `fc00::/7`
4. 只保留全局 IPv6
5. 多个可用地址同时存在时：
   - 优先 `/128`
   - 若没有 `/128`，优先稳定地址
   - 明显 temporary/privacy 风格地址只做降级，不盲选
   - 仍然无法可靠决策时返回 `ambiguous`

## Failure and Ambiguity Semantics

- backend 调用失败：`DiscoveryResult.error` 非空
- 过滤后无可用地址：`SelectionResult.status = no_candidate`
- 存在多个同优先级候选：`SelectionResult.status = ambiguous`
- 被过滤和未选中的候选都会保留原因，便于日志与排障

