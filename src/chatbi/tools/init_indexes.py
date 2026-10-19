"""初始化当前启用功能所需的索引；可重复执行。"""
import argparse
import json

from chatbi.core.config import APP_CONFIG
from chatbi.retrieval.index_manager import ensure_indexes, indexes_status
from chatbi.infrastructure.datasource_store import get_datasource_store
from chatbi.retrieval.schema_index import ensure_schema_index, schema_index_status


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化表、字段和指标索引")
    parser.add_argument("--all", action="store_true", help="初始化全部索引，而非仅启用功能")
    parser.add_argument("--force", action="store_true", help="强制重建，会再次调用 Embedding 服务")
    parser.add_argument("--status", action="store_true", help="只读查看版本和完整性，不调用 Embedding 服务")
    parser.add_argument("--source-id", help="准备指定数据源的真实 Schema 索引；不传时使用默认数据源")
    args = parser.parse_args()
    features = {"schema_linking": True, "indicator_rag": True} if args.all else APP_CONFIG["features"]
    try:
        # 旧的全局表/字段定义不再用于当前数据源索引；指标仍沿用原 JSON 索引。
        indicator_features = {"indicator_rag": features.get("indicator_rag", False)}
        if not args.status:
            ensure_indexes(indicator_features, args.force)
        states = indexes_status(indicator_features)
        if features.get("schema_linking", False) or args.source_id:
            source_id = args.source_id or APP_CONFIG["database"]["default_source"]
            store = get_datasource_store()
            if not args.status:
                from chatbi.bootstrap.runtime_factory import build_database_client
                db = build_database_client(APP_CONFIG, source_id)
                try:
                    tables = db.describe_schema()
                    store.save_schema(source_id, tables)
                    ensure_schema_index(source_id, tables, force=args.force)
                finally:
                    db.close()
            states["schema"] = schema_index_status(source_id, store.tables(source_id))
        print(json.dumps(states, ensure_ascii=False, indent=2))
        return 0 if all(state["status"] == "ready" for state in states.values()) else 1
    except Exception as exc:
        print(f"索引初始化失败（{type(exc).__name__}），请检查 Embedding 配置、网络和目录权限。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
