# ADR-015：Hermes 多安装模式 + 角色包系统

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.14.2
- **前置 ADR**: ADR-011（HermesAdapter），ADR-014（v0.9→v0.14 全景）

---

## 一、背景

Hermes Agent 作为 SCCS OS 的底层运行时底座，支持 7 种安装方式（git-installer / pip / Docker / Homebrew / Nix / Desktop / Source）。v0.14.0 之前，所有 Hermes 调用代码硬编码 `hermes` binary 路径，在 Docker 环境或自定义安装路径下无法正常工作。

同时，新用户从零搭建 SCCS OS 需要手动创建 Personalities、Agent YAML、配置 Hermes Profile，过程繁琐。

## 二、决策

### 2.1 HermesManager — 安装发现门面

```python
manager = HermesManager()
inst = manager.discover()
# → HermesInstallation(mode=GIT_INSTALLER, binary_path="...", home="...", ...)
issues = manager.validate(inst)      # 完整性检查
adapter = manager.get_adapter("auto")  # 自动选择最佳适配器
```

**安装模式分类链**：PATH 探测 → sccsos.yaml → 环境变量 → Docker ps，按兼容性降序。

### 2.2 配置抽象（HermesConfig）

`sccsos.yaml` 新增 `hermes` 一级配置节：

```yaml
hermes:
  profile: sccsos
  binary: hermes        # 可自定义
  home: ""              # HERMES_HOME 覆盖
  code_path: ""          # HERMES_CODE_PATH 覆盖
  adapter: auto          # subprocess / docker-exec / mock / auto
  docker:               # Docker 环境配置
    container: hermes-agent
    network: host
```

**三源优先级**：环境变量 > sccsos.yaml > 系统默认。

### 2.3 RolePackage — 角色包一步安装

4 个内置角色：

| 角色 | 技能 | Personalities | Workflows |
|------|------|---------------|-----------|
| architect | 架构审计 + 模式库 | agent-architect | 架构评审 |
| code-reviewer | 代码审计 | code-reviewer | 代码审查 |
| doc-writer | 文档生产 | doc-writer | 文档生成 |
| strategist | 战略规划 | strategist | 每日巡检 |

**安装机制**：`sccsos init --role architect` → 验证 Hermes 技能存在 → 写入 YAML 模板 → 配置 Hermes Profile。

### 2.4 create_adapter("auto") 工厂扩展

| 模式 | 检测条件 | 适配器 |
|------|---------|--------|
| auto | Docker 容器内 | DockerHermesAdapter |
| auto | 本地 CLI | HermesSubprocessAdapter |
| docker-exec | 强制 Docker | Docker exec 命令 |
| mock | 测试模式 | MockHermesAdapter |

## 三、权衡

| 选项 | 优势 | 劣势 |
|------|------|------|
| **HermesManager 门面**（采纳） | 统一入口，解耦探测/验证/适配 | 首次探测有 ~200ms 延迟 |
| 直接读 config/hardcode（否决） | 简单 | 多环境不可用 |
| **RolePackage 注册表**（采纳） | 零代码添加新角色 | 需维护 YAML 注册表 |

## 四、后果

- CLI helpers 必须从 `_resolve_hermes_binary()` 读取 binary，禁止硬编码
- Docker 环境自动使用 `docker exec` 通信
- 角色包遵循「不覆盖用户修改」原则
- `sccsos doctor` 显示安装模式和版本
