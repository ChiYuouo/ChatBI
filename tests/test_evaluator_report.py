from chatbi.tools.evaluator import Evaluator


def sample_results():
    return [
        {
            "id": "S01",
            "category": "simple",
            "question": "查询订单数量",
            "expected_sql": "SELECT COUNT(*) FROM sales_orders",
            "generated_sql": "SELECT COUNT(*) FROM sales_orders",
            "exact_match": True,
            "execution_match": True,
            "error": None,
            "detail": {"expected_row_count": 1, "generated_row_count": 1},
        },
        {
            "id": "M01",
            "category": "medium",
            "question": "按区域|统计收入",
            "expected_sql": "SELECT region, SUM(net_amount) FROM sales_orders GROUP BY region",
            "generated_sql": "SELECT region, COUNT(*) FROM sales_orders GROUP BY region",
            "exact_match": False,
            "execution_match": False,
            "error": None,
            "detail": {"expected_row_count": 3, "generated_row_count": 3},
        },
        {
            "id": "C01",
            "category": "complex",
            "question": "查询利润",
            "expected_sql": "SELECT 1",
            "generated_sql": None,
            "exact_match": False,
            "execution_match": False,
            "error": "SQL 生成失败：模型不可用",
            "detail": {},
        },
    ]


def test_terminal_report_contains_summary_and_failed_cases():
    report = Evaluator(db_client=object()).generate_report(sample_results())

    assert "执行正确：1 (33.3%)" in report
    assert "执行失败：1" in report
    assert "结果不匹配：1" in report
    assert "[M01] 结果不匹配" in report
    assert "[C01] 执行失败" in report


def test_markdown_report_contains_tables_conclusion_and_failure_details():
    report = Evaluator(db_client=object()).generate_markdown_report(sample_results())

    assert "# ChatBI Text-to-SQL 评估报告" in report
    assert "| 执行结果正确 | 1 | 33.3% |" in report
    assert "当前最薄弱的难度" in report
    assert "按区域\\|统计收入" in report
    assert "## 失败与不匹配详情" in report
    assert "SQL 生成失败：模型不可用" in report


def test_save_markdown_report_creates_parent_directory(tmp_path):
    output_path = tmp_path / "reports" / "evaluation.md"

    saved_path = Evaluator(db_client=object()).save_markdown_report(
        sample_results(),
        str(output_path),
    )

    assert saved_path == output_path
    assert output_path.exists()
    assert "总体结果" in output_path.read_text(encoding="utf-8")
