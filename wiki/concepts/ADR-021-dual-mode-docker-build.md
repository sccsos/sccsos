# ADR-021：双模式 Docker 镜像构建 — All-in-One + Slim

- **日期**: 2026-07-27
- **状态**: 已接受
- **版本关联**: v0.16.5
- **前置 ADR**: ADR-015（多安装模式），ADR-020（Redis + RemoteHermesAdapter）

---

## 一、背景

SCCS OS 的 Docker 镜像自 v0.9.0 以来一直采用 **all-in-one 模式**：在同一个容器中同时安装 SCCS OS 运行时和 Hermes Agent CLI。这种方式对开发调试和单机体验友好，但在以下场景暴露出问题：

1. **镜像体积膨胀**：Hermes Agent 及其依赖（git、curl、xz-utils、Node.js 等间接依赖）增加了 ~40-50% 的镜像体积，对 CI/CD 流水线的拉取和存储成本有影响。
2. **扩缩容耦合**：在 K8s 环境中，SCCS OS（无状态 API 层）和 Hermes Agent（计算密集型推理节点）的扩缩容策略不同。绑定在同一 Pod 内意味着两者必须同步扩缩，无法独立 HPA。
3. **版本管理耦合**：SCCS OS 和 Hermes Agent 的版本升级必须同步，无法独立演进。
4. **安全攻击面**：Hermes CLI 的 sandbox 和命令白名单在容器内有效，但 Hermes Agent 本身的依赖链增加了镜像的潜在漏洞面。

与此同时，v0.14.0 引入的适配器体系（HermesManager + DockerHermesAdapter + RemoteHermesAdapter）已经为**运行时解耦**做好了准备——关键在于**构建时**也需要解耦。

### 当前适配器体系回顾

```
HermesManager.discover()
    → Hermes CLI 在 PATH 中          → HermesSubprocessAdapter (子进程)
    → Docker 中有 hermes-agent 容器    → DockerHermesAdapter (docker exec)
    → 配置了 hermes.remote.url        → RemoteHermesAdapter (HTTP)
    → 都不能用                        → 清晰错误诊断
```

`sccsos.yaml` 中的 `hermes.adapter: auto` 已在运行时动态选择最优适配器。

## 二、决策

### 2.1 双 Dockerfile 方案

维护两套 Dockerfile，分别应对两种部署模式：

| 特性 | `Dockerfile`（全合一） | `Dockerfile.slim`（精简） |
|------|----------------------|------------------------|
| **Hermes Agent** | 内嵌 `pip install hermes-agent` | 不安装 |
| **Hermes 通信** | subprocess（本容器 CLI） | docker-exec / remote |
| **系统依赖** | git + curl + xz-utils | curl 仅 |
| **镜像大小** | ~600MB | ~350MB（估） |
| **扩缩容策略** | SCCS + Hermes 同步 | 可独立 HPA |
| **Docker Compose** | `docker compose up -d` | `docker compose --profile slim up -d` |
| **K8s 部署** | 单容器 Pod | sidecar 模式（sccsos + hermes） |
| **适用场景** | 开发、单机、快速体验 | 生产、CI/CD、微服务架构 |

### 2.2 Docker Compose 双模式编排

`docker-compose.yaml` 使用 Docker Compose Profiles 提供两种启动方式：

**Mode 1（默认）**——向后兼容：

```bash
docker compose up -d
# 启动 sccsos 服务（Dockerfile 全合一）
```

**Mode 2（slim）**——双容器解耦：

```bash
docker compose --profile slim up -d
# 启动 sccsos-slim（Dockerfile.slim）+ hermes-agent（独立容器）
```

Mode 2 下，sccsos-slim 容器通过 `docker exec hermes-agent hermes ...` 与 hermes-agent 容器通信，需要 Docker socket 挂载。

### 2.3 HermesManager 的自动适配行为

在 slim 镜像中，`HermesManager.discover()` 的探测链将表现为：

```
1. PATH 探测 hermes binary    → 未找到（跳过 subprocess）
2. sccsos.yaml 配置          → 无 binary 覆盖
3. 环境变量 HERMES_ADAPTER   → 设为 docker-exec 或 remote
4. Docker ps 容器探测        → 发现 hermes-agent 容器 → 模式 DOCKER
5. 返回 DockerHermesAdapter
```

如果既没有 Docker 容器也没有 remote 配置，`doctor_report()` 将给出清晰的配置指引。

### 2.4 健康检查差异

| 指标 | 全合一 | Slim |
|------|--------|------|
| 检查命令 | `python3 -m sccsos health` | `curl -sf http://localhost:8765/health` |
| Hermes 可用性 | 包含 Hermes CLI 检测 | 不包含（外部管理） |

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **双 Dockerfile**（采纳） | 构建时完全分离，用户按需选择 | 需维护两套 Dockerfile |
| 单一 Dockerfile + build arg（否决） | 维护一个文件 | build arg 条件逻辑复杂，层缓存失效 |
| **Docker Compose Profiles**（采纳） | 原生支持，无需额外工具 | 需用户了解 profiles 概念 |
| Makefile 包装（否决） | 简化用户操作 | 增加了 Makefile 依赖 |
| **Docker socket 挂载**（采纳） | 成熟的容器间通信模式 | 安全考量：sccsos 容器获得 Docker 守护进程访问权 |

## 四、后果

### 积极后果

- ✅ 镜像体积缩减 ~40-50%，CI/CD 更快
- ✅ K8s 部署可独立扩缩 SCCS OS 和 Hermes
- ✅ 版本解耦：SCCS OS 和 Hermes 可独立升级
- ✅ 减少镜像攻击面（少了 Hermes 依赖链）
- ✅ 现有 `HermesManager` + 适配器体系无需修改——所有适配逻辑在运行时已有

### 消极后果

- ⚠️ slim 模式需要 Docker socket 挂载（安全敏感——需限制访问）
- ⚠️ slim 模式下 `docker compose --profile slim up -d` 比原来多一条命令
- ⚠️ 额外的测试覆盖（两种构建模式的 CI 门禁）

### 后续待办（已实施）

- [x] 创建专用的 `Dockerfile.hermes`（比全量 sccsos 镜像更小的 hermes-only 镜像）
- [x] `docker-compose.yaml` 中的 hermes-agent 服务使用 `Dockerfile.hermes`
- [x] 更新 K8s Helm chart 支持 slim + sidecar 模式
- [x] 创建 `deploy/k8s/slim-sidecar/` 裸 K8s 部署清单
- [x] 更新部署决策树 SVG 图（添加双镜像模式分支）
- [x] 更新企业部署架构 SVG 图（添加 slim+sidecar 标注）
