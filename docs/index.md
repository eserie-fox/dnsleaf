# arbor-ddns Docs

`arbor-ddns` 是一个中心化 IPv6 发现与 DNS AAAA 同步工具，面向 PVE 宿主环境中的指定 LXC 与 Linux VM。

文档导航：

- [架构总览](architecture_overview.md)
- [开发约束](development_constraints.md)
- [运行期配置](runtime_config.md)
- [地址发现与选择](discovery.md)
- [DNS 同步](dns_sync.md)

项目目标：

- 从 PVE 目标中发现 IPv6 候选地址
- 用明确、可测试的策略选出一个 DNS AAAA 目标地址
- 将目标地址同步到 DNS provider
- 保持 CLI、runner、provider、selector 之间的边界清晰

