# ADR-012：技能市场 + 审批系统 + RBAC

- **日期**: 2026-07-26
- **状态**: 已接受
- **版本关联**: v0.12.0~v0.13.0

## 背景

v0.11.4 对技能的管理仅限于文件系统操作，无市场、无审批、无权限管控。企业级场景需要完整的技能生命周期管理。

## 决策

1. **技能市场**：`skill_market` DB 表 + `SkillMarket` 类 + 5 个 API 端点 + Vue 4-标签页 UI
   - 支持 publish / install / remove / search / prune
   - 自动版本号递增（bump patch）
   - 安装时写入 `installed_skills` 表并复制 YAML 到目标目录

2. **审批流程**：`SkillReviewManager` + `review_comments` + `review_history` 表
   - 5 状态：draft → pending_review → approved / rejected → (reset → draft)
   - Threaded 评论（`parent_id` 支持回复）
   - 审计轨迹（submit/approve/reject/reset 全部记录）
   - 自动 validation（YAML parse + 必填字段 + 安全检测）
   - EventBus 事件：`skill.submitted/approved/rejected/reset`

3. **版本 diff**：字段级对比 + content diff 回退（YAML 无法 parse 时降级）

4. **RBAC**：3 角色（admin/operator/viewer）× 14 权限，通过 FastAPI `Depends` + `X-Role` header 实现

## 后果

- 正面：技能生命周期完整可管控、权限收敛、审计可追溯
- 负面：审批流程增加技能上架周期（draft → submit → approve）
