# ADR-013：技能评分 + 故障自愈测试 + 文档社区基建

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.14.2

## 背景

v0.14.1 后需要补齐三个关键短板：技能运营缺乏用户反馈机制、生产环境故障恢复无验证、开发者社区基建空白。

## 决策

### 1. 技能评分系统
- `skill_ratings` 表（INSERT OR REPLACE upsert）
- 1-5 星评分 + 可选评论
- 聚合统计：平均分 + 分布（5 段）
- 排名查询：top-rated / most-installed / popular（加权）
- 分类系统：`category` 字段 + 按分类筛选
- EventBus `skill.rated` 事件 → WebSocket 广播
- Vue 🔥 热门标签页（双栏：评分最高 + 安装最多）

### 2. 故障自愈测试
- 26 场景覆盖 4 层：DB 并发/Supervisor 崩溃/EventBus 降级/线程泄漏
- `@pytest.mark.slow` 标记，CI 默认跳过，单独运行

### 3. 文档与社区基建
- CONTRIBUTING.md（12 章开发者指南）
- GitHub Issues 模板 x3（Bug/Feature/Question）
- App.vue 响应式侧边栏

## 后果

- 正面：技能可评分排名、生产稳定性可验证、社区贡献门槛降低
- 负面：评分系统增加 ~112 行 Python + DB 迁移 v7/v8；故障测试含线程同步延迟
