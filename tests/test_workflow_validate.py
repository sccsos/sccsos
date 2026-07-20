"""示例测试：工作流定义有效性验证"""
import yaml
from pathlib import Path

WORKFLOWS_DIR = Path(__file__).parent.parent / "workflows"


def get_all_workflows():
    """扫描所有 workflow YAML 文件"""
    return list(WORKFLOWS_DIR.glob("*.yaml"))


def validate_workflow_yaml(path: Path) -> list[str]:
    """验证单个 workflow 定义的完整性"""
    errors = []
    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            return [f"YAML 解析错误: {e}"]

    if not data:
        return ["空文件"]

    if "name" not in data:
        errors.append("缺少 'name' 字段")
    if "steps" not in data or not isinstance(data["steps"], list):
        errors.append("缺少或无效的 'steps' 字段")

    if "steps" in data and isinstance(data["steps"], list):
        step_ids = []
        for i, step in enumerate(data["steps"]):
            if "id" not in step:
                errors.append(f"步骤 {i}: 缺少 'id' 字段")
            else:
                step_ids.append(step["id"])
            if "prompt" not in step:
                errors.append(f"步骤 {i} ({step.get('id', '?')}): 缺少 'prompt' 字段")

        # 检查循环依赖
        step_deps = {}
        for step in data["steps"]:
            sid = step["id"]
            deps = step.get("depends_on", [])
            step_deps[sid] = deps if isinstance(deps, list) else [deps]

        # 检查缺失依赖
        all_ids = set(step_ids)
        for sid, deps in step_deps.items():
            for d in deps:
                if d not in all_ids:
                    errors.append(f"步骤 '{sid}': 依赖 '{d}' 不存在")

    return errors


def test_all_workflows_valid():
    """全部 workflow 应通过验证"""
    for wf_path in get_all_workflows():
        errors = validate_workflow_yaml(wf_path)
        assert not errors, f"{wf_path.name}: {'; '.join(errors)}"
        print(f"✅ {wf_path.name}: 通过验证")


def test_all_workflows_to_mermaid():
    """全部 workflow 应能正确生成 Mermaid 流程图"""
    from sccsos.core.workflow import WorkflowDef
    for wf_path in get_all_workflows():
        wf = WorkflowDef.from_yaml(str(wf_path))
        mermaid = wf.to_mermaid()
        assert "```mermaid" in mermaid
        assert "flowchart TD" in mermaid
        for step in wf.steps:
            # Each step should appear as a node
            assert step.id in mermaid, f"{wf_path.name}: missing node {step.id}"
            # Dependencies should appear as edges
            for dep in step.depends_on:
                assert f"{dep} --> {step.id}" in mermaid, \
                    f"{wf_path.name}: missing edge {dep} -> {step.id}"
        print(f"✅ {wf_path.name}: Mermaid 生成成功 ({len(wf.steps)} steps)")
        print(f"   {len([s for s in wf.steps if s.depends_on])} edges")


def test_sccsos_help_shows_visualize():
    """CLI --help 应包含 visualize 命令"""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "sccsos", "workflow", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "visualize" in result.stdout
    print(f"✅ CLI workflow --help 包含 visualize")


if __name__ == "__main__":
    test_all_workflows_valid()
