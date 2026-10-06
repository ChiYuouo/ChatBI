"""
表级召回模块（LangChain + ChromaDB）

使用 LangChain 统一抽象层 + ChromaDB 持久化向量数据库，
实现表级召回的可持久化、可扩展版本。

依赖安装：uv add langchain-openai langchain-chroma chromadb
"""

from langchain_openai import OpenAIEmbeddings
from chatbi.execution.budget import request_timeout
from langchain_chroma import Chroma
from chatbi.core.config import CHROMA_ROOT, LLM_CONFIG


# ==================== 表描述数据 ====================
# 每张表构建一段结构化的"自然语言描述"用于向量化检索
# 仅包含当前已接入的业务表；测试干扰项不进入运行索引
TABLE_METADATA = {
    # ---- 业务相关表 ----
    "dim_customers": {
        "description": (
            "客户维度表：存储客户基本信息，包括客户名称、客户类型"
            "（OEM整车厂、储能集成商、电网集团等）、所属行业（交通、能源、工业）、"
            "所在国家和销售大区（欧洲、北美、亚太等）。"
            "用于按客户维度分析收入、利润和订单分布。"
        ),
        "domain": "维度表",
        "key_fields": "customer_id, customer_name, customer_type, industry, country, region",
    },
    "dim_products": {
        "description": (
            "产品维度表：存储产品主数据，包括产品名称、产品线"
            "（动力电池-乘用车、储能系统-电网级等）、技术路线（三元锂、磷酸铁锂等）、"
            "以及产品成本信息（标准成本、材料成本、人工成本）。"
            "用于按产品维度分析收入、毛利、成本结构。"
        ),
        "domain": "维度表",
        "key_fields": "product_id, product_name, product_line, category, tech_route, standard_cost, material_cost, labor_cost",
    },
    "sales_orders": {
        "description": (
            "销售订单表：记录每笔销售订单的详细信息，包括订单日期、订单状态、"
            "数量、单价、折扣、含税总额（gross_amount）、不含税收入（net_amount）、币种。"
            "通过 customer_id 和 product_id 关联客户表和产品表。"
            "是收入分析、订单统计的核心事实表。"
        ),
        "domain": "事实表",
        "key_fields": "order_id, order_no, customer_id, product_id, region, order_date, order_status, quantity, unit_price, discount_amount, gross_amount, net_amount, currency",
    },
    "exchange_rates": {
        "description": (
            "汇率表：按日期和币种记录兑人民币汇率（rate_to_cny）。"
            "当订单涉及多币种时，需关联此表将金额统一折算为人民币。"
            "用于多币种收入汇总和跨区域财务对比。"
        ),
        "domain": "参考表",
        "key_fields": "rate_date, currency, rate_to_cny",
    },
    "finance_expenses": {
        "description": (
            "费用表：记录企业各部门的期间费用明细，包括研发费用、销售费用、"
            "管理费用、财务费用，以及销售费用的子项（市场费用、物流费用、质保费用）。"
            "用于费用分析、利润计算（利润 = 毛利 - 期间费用）。"
        ),
        "domain": "事实表",
        "key_fields": "expense_id, expense_date, department, rd_expense, selling_expense, admin_expense, finance_expense, marketing_expense, logistics_expense, warranty_expense",
    },
}


# ==================== ChromaDB 持久化目录 ====================
CHROMA_PERSIST_DIR = str(CHROMA_ROOT / "tables")


def _cosine_relevance_score_fn(distance: float) -> float:
    """
    将 ChromaDB 的 cosine 距离转换为余弦相似度。

    ChromaDB 在 hnsw:space=cosine 模式下，distance = 1 - cosine_similarity。
    因此 cosine_similarity = 1 - distance，值域 [-1, 1]，
    与手写实现的余弦相似度一致，方便对比。
    """
    return 1 - distance


def get_embeddings() -> OpenAIEmbeddings:
    """构建 LangChain OpenAI Embeddings 实例（使用项目统一配置）"""
    return OpenAIEmbeddings(
        model=LLM_CONFIG["embedding_model"],
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        check_embedding_ctx_length=False,
        chunk_size=10,
        request_timeout=request_timeout(LLM_CONFIG["timeout_seconds"]),
        max_retries=0,
    )


def get_vectorstore() -> Chroma:
    """
    获取或创建 ChromaDB 向量存储实例。

    关键配置：
    - collection_metadata={"hnsw:space": "cosine"}：使用 cosine 距离而非默认的 L2 距离
    - relevance_score_fn：将 cosine 距离转换回余弦相似度（与手写实现一致）

    如果不指定 cosine 空间，ChromaDB 默认使用 L2 距离，
    LangChain 的默认分数转换 (1 - distance/2) 在 L2 距离超过 2 时会产生负值。
    """
    return Chroma(
        collection_name="table_descriptions",
        embedding_function=get_embeddings(),
        persist_directory=CHROMA_PERSIST_DIR,
        collection_metadata={"hnsw:space": "cosine"},
        relevance_score_fn=_cosine_relevance_score_fn,
    )


# ==================== 索引构建 ====================
def build_index(force_rebuild: bool = False) -> Chroma:
    """通过统一入口识别版本并按需构建索引。"""
    from chatbi.retrieval.index_manager import ensure_index
    return ensure_index("tables", force_rebuild)


# ==================== 表召回检索 ====================
def retrieve_tables(
    query: str,
    top_k: int = 3,
    score_threshold: float = 0.2,
    domain_filter: str | None = None,
) -> list[dict]:
    """
    根据用户问题检索最相关的表。

    Args:
        query: 用户的自然语言问题
        top_k: 返回前 K 张最相关的表
        score_threshold: 相似度阈值，低于此值的结果会被过滤
        domain_filter: 可选的领域过滤（如 "维度表"、"事实表"）

    Returns:
        [{"table_name": str, "score": float, "description": str, "domain": str, "key_fields": str}]
    """
    vectorstore = get_vectorstore()

    # 构建过滤条件
    search_kwargs = {"k": top_k}
    if domain_filter:
        search_kwargs["filter"] = {"domain": domain_filter}

    # 执行相似度检索（带分数）
    # 分数为余弦相似度（由 _cosine_relevance_score_fn 转换），值域 [-1, 1]
    results_with_scores = vectorstore.similarity_search_with_relevance_scores(
        query, **search_kwargs
    )

    # 过滤低分结果并格式化输出
    output = []
    for doc, score in results_with_scores:
        if score >= score_threshold:
            output.append({
                "table_name": doc.metadata["table_name"],
                "score": round(score, 4),
                "description": doc.page_content,
                "domain": doc.metadata["domain"],
                "key_fields": doc.metadata["key_fields"],
            })

    return output


# ==================== 主程序：演示 ====================
if __name__ == "__main__":
    # 第一步：构建索引（首次运行会调 Embedding API，后续直接加载本地数据）
    print("=" * 60)
    print("LangChain + ChromaDB 表级召回演示")
    print("=" * 60)
    print()

    vectorstore = build_index(force_rebuild=True)

    # 第二步：测试检索
    test_questions = [
        "欧洲市场最近三个月的销售额是多少？",
        "各产品线的毛利率",
        "上个月的研发费用和销售费用对比",
        "查询已完成订单的总数量",
        "按客户类型统计收入，需要换算成人民币",
    ]

    print()
    for question in test_questions:
        print(f"\n问题：{question}")
        results = retrieve_tables(question, top_k=5)
        print("召回结果：")
        for r in results:
            # 相似度 > 0.4 标记为强相关，0.3~0.4 为弱相关，其余不标记
            marker = "✓" if r["score"] > 0.4 else "·"
            print(f"  {marker} {r['table_name']:30s} 相似度: {r['score']:.4f}  [{r['domain']}]")
        if not results:
            print("  （无满足阈值的结果）")

    # 第三步：演示元数据过滤
    print("\n\n--- 元数据过滤演示：仅检索事实表 ---")
    results = retrieve_tables("上个月的收入和利润", top_k=3, domain_filter="事实表")
    print("问题：上个月的收入和利润（仅事实表）")
    for r in results:
        print(f"  ✓ {r['table_name']:30s} 相似度: {r['score']:.4f}  [{r['domain']}]")
