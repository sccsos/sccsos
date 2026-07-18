"""示例测试：Agent 定义文件有效性验证"""
import yaml
from pathlib import Path

AGENTS_DIRS = [
    Path(__file__).parent.parent / "agents",
    Path(__file__).parent.parent / "sccsos" / "agents",
]


def get_all_agent_files():
    """扫描所有 Agent 定义 YAML 文件"""
    files = []
    for d in AGENTS_DIRS:
        if d.exists():
            files.extend(d.glob("*.yaml"))
    return files


def validate_agent_yaml(path: Path) -> list[str]:
    """验证单个 Agent 定义的完整性"""
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
    if "profile" not in data:
        errors.append("缺少 'profile' 字段")
    if "lifecycle" in data:
        lc = data["lifecycle"]
        if "max_turns" not in lc:
            errors.append("lifecycle 缺少 'max_turns' 字段")
        if "timeout" not in lc:
            errors.append("lifecycle 缺少 'timeout' 字段")

    return errors


def test_all_agents_valid():
    """全部 Agent 定义应通过验证"""
    for ag_path in get_all_agent_files():
        errors = validate_agent_yaml(ag_path)
        assert not errors, f"{ag_path.name}: {'; '.join(errors)}"
        print(f"✅ {ag_path.name}: 通过验证")


if __name__ == "__main__":
    test_all_agents_valid()
