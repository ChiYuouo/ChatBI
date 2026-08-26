"""
评估模块
负责运行测试用例集，对比生成 SQL 与预期 SQL 的执行结果，
计算 Execution Accuracy 并输出评估报告。

评估判定标准：

- Execution Accuracy：生成 SQL 的执行结果与预期 SQL 的执行结果在数据层面
  等价
- Exact Match Accuracy：生成 SQL 的字符串与预期 SQL 完全一致（仅供参考，
  非主要指标）
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from chatbi.infrastructure.database import DatabaseClient


class Evaluator:
    """SQL 生成评估器"""

    def __init__(self, db_client: Optional[DatabaseClient] = None):
        """
        Args:
            db_client: 数据库客户端实例，如未传入则自动创建
        """
        self.db = db_client or DatabaseClient()

    def load_test_cases(self, path: str = "test_cases.json") -> list[dict]:
        """从 JSON 文件加载测试用例"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate_one(
        self,
        case: dict,
        sql_generator: Callable[[str], str]
    ) -> dict:
        """
        评估单个测试用例

        Args:
            case: 测试用例字典，包含 question、expected_sql 等字段
            sql_generator: 接收问题字符串、返回生成 SQL 的可调用对象

        Returns:
            包含评估结果的字典
        """

        question = case["question"]
        expected_sql = case["expected_sql"]

        result = {
            "id": case.get("id", "unknown"),
            "category": case.get("category", "unknown"),
            "question": question,
            "expected_sql": expected_sql,
            "generated_sql": None,
            "exact_match": False,
            "execution_match": False,
            "error": None,
            "detail": {}
        }

        # 1. 生成 SQL
        try:
            generated_sql = sql_generator(question)
            result["generated_sql"] = generated_sql
            result["exact_match"] = (
                self._normalize_sql(generated_sql)
                == self._normalize_sql(expected_sql)
            )
        except Exception as e:
            result["error"] = f"SQL 生成失败：{e}"
            return result

        # 2. 执行预期 SQL 获取基准结果
        try:
            exp_columns, exp_results = self.db.execute(expected_sql)
        except Exception as e:
            result["error"] = f"预期 SQL 执行失败：{e}"
            return result

        # 3. 执行生成 SQL 获取结果
        try:
            gen_columns, gen_results = self.db.execute(generated_sql)
        except Exception as e:
            result["error"] = f"生成 SQL 执行失败：{e}"
            result["detail"] = {
                "expected_columns": exp_columns,
                "expected_row_count": len(exp_results)
            }
            return result

        # 4. 对比执行结果
        result["execution_match"] = self._results_equivalent(
            gen_columns,
            gen_results,
            generated_sql,
            exp_columns,
            exp_results,
            expected_sql
        )

        result["detail"] = {
            "expected_columns": exp_columns,
            "expected_row_count": len(exp_results),
            "generated_columns": gen_columns,
            "generated_row_count": len(gen_results)
        }

        return result

    def evaluate_all(
        self,
        cases: list[dict],
        sql_generator: Callable[[str], str]
    ) -> list[dict]:
        """批量评估所有测试用例"""

        return [
            self.evaluate_one(case, sql_generator)
            for case in cases
        ]

    def generate_report(self, results: list[dict]) -> str:
        """生成适合终端快速阅读的文本摘要。"""
        summary = self._summarize_results(results)
        lines = [
            "=" * 64,
            "ChatBI Text2SQL 评估摘要",
            "=" * 64,
            f"总用例：{summary['total']}",
            f"执行正确：{summary['execution_correct']} "
            f"({summary['execution_accuracy']:.1f}%)",
            f"SQL 完全一致：{summary['exact_correct']} "
            f"({summary['exact_accuracy']:.1f}%)",
            f"执行失败：{summary['error_count']}",
            f"结果不匹配：{summary['mismatch_count']}",
            "",
            "按难度统计：",
        ]

        for category in ["simple", "medium", "complex"]:
            if category not in summary["categories"]:
                continue
            stat = summary["categories"][category]
            lines.append(
                f"  {category:8s} {stat['correct']:>2}/{stat['total']:<2} "
                f"正确率 {stat['accuracy']:>5.1f}% | "
                f"执行失败 {stat['error']}"
            )

        failed_results = [result for result in results if not result["execution_match"]]
        if failed_results:
            lines.extend(["", "需要关注的用例："])
            for result in failed_results:
                status = "执行失败" if result["error"] else "结果不匹配"
                lines.append(f"  [{result['id']}] {status} | {result['question']}")
                if result["error"]:
                    lines.append(f"      {result['error']}")
        else:
            lines.extend(["", "所有用例均通过。"])

        return "\n".join(lines)

    def generate_markdown_report(self, results: list[dict]) -> str:
        """生成可在 IDE 或 GitHub 中直接查看的 Markdown 报告。"""
        summary = self._summarize_results(results)
        lines = [
            "# ChatBI Text-to-SQL 评估报告",
            "",
            f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 总体结果",
            "",
            "| 指标 | 数量 | 比例 |",
            "|---|---:|---:|",
            f"| 总用例 | {summary['total']} | 100.0% |",
            f"| 执行结果正确 | {summary['execution_correct']} | {summary['execution_accuracy']:.1f}% |",
            f"| SQL 完全一致 | {summary['exact_correct']} | {summary['exact_accuracy']:.1f}% |",
            f"| 执行失败 | {summary['error_count']} | {summary['error_rate']:.1f}% |",
            f"| 执行成功但结果不匹配 | {summary['mismatch_count']} | {summary['mismatch_rate']:.1f}% |",
            "",
            "## 自动总结",
            "",
            self._build_conclusion(summary),
            "",
            "## 按难度统计",
            "",
            "| 难度 | 正确 | 总数 | 正确率 | 执行失败 |",
            "|---|---:|---:|---:|---:|",
        ]

        for category in ["simple", "medium", "complex"]:
            if category not in summary["categories"]:
                continue
            stat = summary["categories"][category]
            lines.append(
                f"| {category} | {stat['correct']} | {stat['total']} | "
                f"{stat['accuracy']:.1f}% | {stat['error']} |"
            )

        lines.extend([
            "",
            "## 用例明细",
            "",
            "| ID | 难度 | 状态 | 问题 | 预期行数 | 生成行数 |",
            "|---|---|---|---|---:|---:|",
        ])

        for result in results:
            status = self._result_status(result)
            detail = result.get("detail", {})
            lines.append(
                f"| {result['id']} | {result['category']} | {status} | "
                f"{self._escape_markdown(result['question'])} | "
                f"{detail.get('expected_row_count', 'N/A')} | "
                f"{detail.get('generated_row_count', 'N/A')} |"
            )

        failed_results = [result for result in results if not result["execution_match"]]
        if failed_results:
            lines.extend(["", "## 失败与不匹配详情", ""])
            for result in failed_results:
                lines.extend([
                    f"### {result['id']} · {self._escape_markdown(result['question'])}",
                    "",
                    f"- 难度：`{result['category']}`",
                    f"- 状态：{self._result_status(result)}",
                ])
                if result["error"]:
                    lines.append(f"- 错误：{self._escape_markdown(result['error'])}")
                lines.extend([
                    "",
                    "预期 SQL：",
                    "",
                    "```sql",
                    result.get("expected_sql") or "",
                    "```",
                    "",
                    "生成 SQL：",
                    "",
                    "```sql",
                    result.get("generated_sql") or "未生成",
                    "```",
                    "",
                ])

        return "\n".join(lines)

    def save_markdown_report(self, results: list[dict], output_path: str) -> Path:
        """保存 Markdown 报告，并自动创建父目录。"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.generate_markdown_report(results), encoding="utf-8")
        return path

    def _summarize_results(self, results: list[dict]) -> dict:
        total = len(results)
        execution_correct = sum(1 for result in results if result["execution_match"])
        exact_correct = sum(1 for result in results if result["exact_match"])
        error_count = sum(1 for result in results if result["error"] is not None)
        mismatch_count = total - execution_correct - error_count
        categories = {}

        for result in results:
            category = result["category"]
            stat = categories.setdefault(category, {"total": 0, "correct": 0, "error": 0})
            stat["total"] += 1
            stat["correct"] += int(result["execution_match"])
            stat["error"] += int(result["error"] is not None)

        for stat in categories.values():
            stat["accuracy"] = self._percentage(stat["correct"], stat["total"])

        return {
            "total": total,
            "execution_correct": execution_correct,
            "execution_accuracy": self._percentage(execution_correct, total),
            "exact_correct": exact_correct,
            "exact_accuracy": self._percentage(exact_correct, total),
            "error_count": error_count,
            "error_rate": self._percentage(error_count, total),
            "mismatch_count": mismatch_count,
            "mismatch_rate": self._percentage(mismatch_count, total),
            "categories": categories,
        }

    @staticmethod
    def _percentage(value: int, total: int) -> float:
        return value / total * 100 if total else 0.0

    @staticmethod
    def _result_status(result: dict) -> str:
        if result["execution_match"]:
            return "✅ 通过"
        if result["error"]:
            return "❌ 执行失败"
        return "⚠️ 结果不匹配"

    @staticmethod
    def _escape_markdown(value: str) -> str:
        return str(value).replace("|", "\\|").replace("\n", "<br>")

    @staticmethod
    def _build_conclusion(summary: dict) -> str:
        accuracy = summary["execution_accuracy"]
        if accuracy >= 90:
            conclusion = "整体执行准确率较高，可以重点检查少量失败用例。"
        elif accuracy >= 70:
            conclusion = "整体已具备基础可用性，但仍需针对薄弱难度继续优化。"
        else:
            conclusion = "当前准确率仍有明显提升空间，建议优先处理执行失败和复杂查询。"

        if summary["categories"]:
            weakest = min(
                summary["categories"].items(),
                key=lambda item: item[1]["accuracy"],
            )
            conclusion += (
                f" 当前最薄弱的难度是 **{weakest[0]}**，"
                f"正确率为 **{weakest[1]['accuracy']:.1f}%**。"
            )
        return conclusion

    def _normalize_sql(self, sql: str) -> str:
        """标准化 SQL 字符串，用于 Exact Match 比较"""

        return " ".join(sql.lower().split())

    def _results_equivalent(
        self,
        gen_columns: list,
        gen_results: list,
        gen_sql: str,
        exp_columns: list,
        exp_results: list,
        exp_sql: str
    ) -> bool:
        """
        判定两组执行结果是否等价

        比较策略：

        1. 列数必须相同
        2. 行数必须相同
        3. 根据查询类型决定是否检查列名：

        - 纯聚合查询（SELECT 中只有聚合函数/常量）：只比较值，忽略列名
        - 其他查询：比较列名+值

        4. 对结果排序后逐行比对（忽略行顺序）
        """

        if len(gen_columns) != len(exp_columns):
            return False

        if len(gen_results) != len(exp_results):
            return False

        check_columns = (
            self._should_check_column_names(exp_sql)
            or self._should_check_column_names(gen_sql)
        )

        def normalize_rows(
            columns,
            rows,
            use_column_names: bool = True
        ):
            if use_column_names:
                # 按列名排序后重组每行数据
                indexed = [
                    {
                        col: str(val)
                        for col, val in zip(columns, row)
                    }
                    for row in rows
                ]

                return sorted([
                    tuple(sorted(d.items()))
                    for d in indexed
                ])

            else:
                # 忽略列名，只比较值的顺序
                return sorted([
                    tuple(str(val) for val in row)
                    for row in rows
                ])

        gen_normalized = normalize_rows(
            gen_columns,
            gen_results,
            check_columns
        )

        exp_normalized = normalize_rows(
            exp_columns,
            exp_results,
            check_columns
        )

        return gen_normalized == exp_normalized

    def _should_check_column_names(self, sql: str) -> bool:
        """
        根据查询类型决定是否检查列名。

        纯聚合查询（SELECT 中只有聚合函数调用或常量）的列名通常是工具性的
        自动生成别名，语义等价时无需强制匹配列名。
        """

        if not sql:
            return True

        sql_upper = sql.upper()

        # 提取 SELECT 子句（到第一个 FROM 为止）
        match = re.search(
            r'SELECT\s+(.*?)(?:\s+FROM\s+)',
            sql_upper,
            re.DOTALL
        )

        if not match:
            return True

        select_clause = match.group(1).strip()

        # 按逗号分割 SELECT 项，考虑嵌套括号
        items = []
        depth = 0
        current = []

        for char in select_clause:
            if char == '(':
                depth += 1
                current.append(char)

            elif char == ')':
                depth -= 1
                current.append(char)

            elif char == ',' and depth == 0:
                items.append(
                    ''.join(current).strip()
                )
                current = []

            else:
                current.append(char)

        if current:
            items.append(
                ''.join(current).strip()
            )

        # 检查每一项是否都是聚合函数调用或常量
        for item in items:

            # 去除 AS 别名
            item_clean = re.split(
                r'\s+AS\s+',
                item,
                maxsplit=1,
                flags=re.IGNORECASE
            )[0].strip()

            # 聚合函数调用
            if re.match(
                r'^\s*(?:COUNT|SUM|AVG|MAX|MIN)\s*\(',
                item_clean,
                re.IGNORECASE
            ):
                continue

            # 纯数字常量
            if re.match(
                r'^[\d+-]?[\d]*\.?[\d]*$',
                item_clean
            ):
                continue

            # 字符串常量
            if (
                re.match(r"^'[^']*'$", item_clean)
                or re.match(r'^"[^"]*"$', item_clean)
            ):
                continue

            # 包含原始列引用或其他表达式，需要检查列名
            return True

        # 所有项都是聚合函数或常量，不检查列名
        return False


def run_evaluation(
    sql_generator: Callable[[str], str],
    test_cases_path: str = "data/test_cases.json",
    report_path: str | None = "reports/evaluation_report.md",
) -> list[dict]:
    """
    运行完整评估流程并打印报告

    Args:
        sql_generator: SQL 生成函数
        test_cases_path: 测试用例文件路径
        report_path: Markdown 报告路径；传入 None 时不保存
    """

    evaluator = Evaluator()

    cases = evaluator.load_test_cases(
        test_cases_path
    )

    # cases = cases[-2:]

    results = evaluator.evaluate_all(
        cases,
        sql_generator
    )

    print(evaluator.generate_report(results))

    if report_path:
        saved_path = evaluator.save_markdown_report(results, report_path)
        print(f"\nMarkdown 报告：{saved_path.resolve()}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="运行 ChatBI Text-to-SQL 评估")
    parser.add_argument(
        "test_cases",
        nargs="?",
        default="data/test_cases.json",
        help="测试用例 JSON 路径",
    )
    parser.add_argument(
        "--report",
        default="reports/evaluation_report.md",
        help="Markdown 报告输出路径",
    )
    args = parser.parse_args()

    from chatbi.infrastructure.llm_client import LLMClient
    from chatbi.text2sql.prompt_builder import build_prompt

    llm = LLMClient()

    def generate_sql(question: str) -> str:
        system_msg, prompt = build_prompt(
            question,
            use_rules=True,
            use_guards=True
        )

        return llm.generate_sql(
            system_msg,
            prompt
        )

    run_evaluation(
        generate_sql,
        args.test_cases,
        report_path=args.report,
    )
