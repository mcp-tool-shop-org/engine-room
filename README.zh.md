<p align="center">
  <a href="README.ja.md">日本語</a> | <a href="README.md">English</a> | <a href="README.es.md">Español</a> | <a href="README.fr.md">Français</a> | <a href="README.hi.md">हिन्दी</a> | <a href="README.it.md">Italiano</a> | <a href="README.pt-BR.md">Português (BR)</a>
</p>

<p align="center">
  <img src="app/logo.png" width="400" alt="engine-room">
</p>

<p align="center">
  <a href="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml"><img src="https://github.com/mcp-tool-shop-org/engine-room/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="License: MIT"></a>
  <a href="https://mcp-tool-shop-org.github.io/engine-room/"><img src="https://img.shields.io/badge/landing%20page-engine--room-0a7ea4" alt="Landing page"></a>
</p>

一个用于本地 AI 引擎的**基于配方驱动的配置工具**。浏览一份经过验证和测量的“引擎配方”目录，选择一个，并在您自己的 GPU 设备上进行部署——**配置 → 启动 → 测量**——即时、可重复地进行操作，并根据实际性能基准进行验证。

## 为什么？

本地 AI 引擎的部署方式多种多样——一种是从源代码构建 CUDA，另一种是容器，还有一种是可移植包，最后是一种写入文件并退出的量化器。知道使用哪个引擎是一个问题（知识库可以解决）；实际上*正确地、可重复地部署它，并测量其工作状态*是另一个问题。
engine-room 解决了后半部分的问题。

## 架构——两个工件，一个接口

engine-room 是一个有意的拆分中的**操作**部分：

- **知识**——经过验证、来源明确的抽象*配方*（要构建的内容、固定的工具链、测量的基准目标、声明的回滚步骤）。当上游引擎发生更改时，它会发生变化。存储在知识库中。
- **操作**——这个仓库：将配方与实时设备进行匹配，将其具体化，启动/测量它，并安全地回滚。当*设备*发生更改时，它会发生变化。

## 获取配方层

engine-room 是**操作**部分；它不包含配方。**知识**部分是一个单独提供的、经过验证的工件——**tensor-engine-knowledge** 配方数据库 (`engines.db`)，您需要将其指向 `er`。仅克隆此仓库只会为您提供执行器，而不是目录。

- **在完全没有配方数据库的情况下检测您的设备**：`er rig` 仅读取实时硬件（`nvidia-smi` + 环境变量），因此它可以开箱即用。
- **指向配方数据库以进行所有其他操作** (`list` / `show` / `preflight` / `provision`)，有两种方式：
- 将 `ER_RECIPES_DB` 设置为数据库路径，或者
- 在任何命令中使用 `--db <path>`。
- 如果两者都没有设置，`er` 会查找相对于仓库的 `../../readouts/tensor-engine-knowledge/engines.db`。当缺少数据库时，您会收到明确的错误消息（“找不到配方数据库：… — 设置 $ER_RECIPES_DB 或传递 --db”），而不是堆栈跟踪。

配方层是受信任的知识输入（请参阅[安全/威胁模型](#security--threat-model)）。从 tensor-engine-knowledge 分发版中获取 `engines.db`；engine-room 以**只读**方式读取它，并且不会写入。

配方是**多态的**——四种类型，每种类型都有不同的形状：

| 类型 | 它的作用 | 由什么衡量 |
|------|--------------|-------------|
| `launchable-server` | 在端口上启动一个长期运行的服务器 | 吞吐量（令牌/秒，迭代/秒） |
| `batch-producer` | 运行、写入工件并退出 | 输出质量 + 实际时间 |
| `modifier` | 一个可插入的叠加层，可以加速另一个配方 | 测量的差异 |
| `router-fleet` | 一个将流量路由到其他配方的前端 | 每个上游组件的运行状况 |

## 通过设计实现可重复性和验证

- **固定和供应商提供的工件**（当索引停止提供该通道时，仅使用哈希值与精选索引进行比较是不够的——固定必须是内容寻址副本）。
- **测量的基准**是基于模型的，并带有兼容性范围，因此常规驱动程序更新不会使它们失效。
- **在任何性能声明之前，都会运行一个正确性门控**，并且可以针对每个输出模式进行插拔。
- **每个不可逆步骤都有一个命名的撤销操作**，并具有诚实的发布后状态；机器全局的步骤需要明确的人工批准。

## 状态

执行器已实现。`er` CLI 读取配方层并将配方与实时设备进行匹配（`rig` / `list` / `show` / `preflight`，所有操作均无副作用），并且配置工具运行协调循环——**默认情况下为“试运行”模式**，并使用一个固定的 `--execute` 路径，该路径会具体化固定工件、启动本地服务器，并根据配方的基准对其进行测量（`provision` / `teardown` / `status`）。请参阅 [`executor/README.md`](executor/README.md)。

可重复性在今天是部分实现的：固定项会针对索引进行解析，并且未固定的工件会被接受——将它们放入内容寻址存储中，以便“可重复”成为*必须努力实现的目标*。

操作员 UI 以自包含原型形式提供（模拟数据 + 定时器模拟的副作用，忠实于真实的 JSON/WS API）：

- [`app/`](app/)——控制面板：浏览配方并运行它们，具有实时遥测、ANDON 停止和回滚功能。设计灵感来自
[`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md)（完整的事件处理程序映射和可用性要求）。

## 安全/威胁模型

**配方层** (`tensor-engine-knowledge/engines.db`) 是受信任的知识输入：经过验证、来源明确的配方，说明要构建的内容以及要达到的目标。engine-room 将其视为事实依据。

`er provision --execute` 是唯一会触及设备的命令。它**需要显式 `--execute` 和 `--model` 才能执行**——所有其他命令，以及不带 `--execute` 的 `provision` 命令，都是只读/试运行模式。当您执行时：

- **下载配方中的固定工件，并在配方携带 SHA 时对其进行 sha256 验证**——当前接受未固定的/占位符 SHA（上述“目标 1”供应商提供的差距；将配方数据库及其工件 URL 视为受信任的，直到实现该功能）。
- **将存档提取到每个实例的目录中（绝不在全局 PATH 中）**。
- **启动本地服务器（`127.0.0.1`），并可以停止它**——拆卸操作经过身份验证（它只会终止其可执行文件位于我们的实例目录下的 PID，因此它永远不会终止不相关的进程）。

每个不可逆步骤都会在执行*之前*记录在一份账本中，并且有一个带有名称的、按最新时间排序的补偿器。如需报告漏洞，请参阅[`SECURITY.md`](SECURITY.md)。

## 支持

`engine-room` 正在**积极维护**。安全补丁会发布到**最新的次版本**（1.0.x 版本）；有关受支持的版本和私有漏洞报告途径，请参阅[`SECURITY.md`](SECURITY.md)。请将错误和功能请求作为 GitHub 问题提交。

## 许可

MIT — 请参阅[LICENSE](LICENSE)。

---

<p align="center">Built by <a href="https://mcp-tool-shop.github.io/">MCP Tool Shop</a>.</p>
