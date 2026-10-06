"""初始化当前启用功能所需的索引；可重复执行。"""
import argparse
import json

from chatbi.core.config import APP_CONFIG
from chatbi.retrieval.index_manager import ensure_indexes, indexes_status


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化表、字段和指标索引")
    parser.add_argument("--all", action="store_true", help="初始化全部索引，而非仅启用功能")
    parser.add_argument("--force", action="store_true", help="强制重建，会再次调用 Embedding 服务")
    parser.add_argument("--status", action="store_true", help="只读查看版本和完整性，不调用 Embedding 服务")
    args = parser.parse_args()
    features = {"schema_linking": True, "indicator_rag": True} if args.all else APP_CONFIG["features"]
    try:
        if not args.status:
            ensure_indexes(features, args.force)
        states = indexes_status(features)
        print(json.dumps(states, ensure_ascii=False, indent=2))
        return 0 if all(state["status"] == "ready" for state in states.values()) else 1
    except Exception as exc:
        print(f"索引初始化失败（{type(exc).__name__}），请检查 Embedding 配置、网络和目录权限。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
