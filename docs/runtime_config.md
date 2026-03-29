# Runtime Config

`arbor-ddns` 使用轻量的 formal runtime config 模式，但不依赖 pylon。

## Defaults

默认配置文件位于包资源中：

- `src/arbor_ddns/config_defaults/app.json`

这保证默认配置跟随包一起分发，而不是依赖宿主机目录结构。

## 加载 API

`AppConfig` 提供三个固定入口：

- `from_defaults()`
- `from_file(path)`
- `from_mapping(data)`

## 固定流程

配置加载流程严格固定为：

1. 读取 package defaults
2. 读取 override
3. deep merge
4. `model_validate`

deep merge 规则：

- `mapping + mapping`: 递归合并
- 其他类型：override 完全替换 base
- 不做列表拼接
- 不做隐式魔法

## Raw Config 与 Runtime Resolve 分离

配置加载阶段只处理：

- defaults 读取
- override 读取
- merge
- validate

不在这个阶段做：

- 路径展开
- 环境变量替换
- 运行期依赖解析

运行期解析必须通过显式方法完成，而不是在加载时偷偷发生。

