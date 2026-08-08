import json
from typing import Optional


class IndicatorKnowledge:
    """指标知识模块：加载指标定义、识别问题中的指标、生成指标知识文本"""

    def __init__(self, config_path: str = "indicators.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.indicators = {ind["name"]: ind for ind in data["indicators"]}

        # 构建别名到标准名称的映射
        self.alias_map = {}

        for ind in data["indicators"]:
            self.alias_map[ind["name"].lower()] = ind["name"]

            for alias in ind.get("aliases", []):
                self.alias_map[alias.lower()] = ind["name"]

    def detect_indicators(self, question: str) -> list[str]:
        """
        从用户问题中识别涉及的指标名称
        策略：遍历别名映射表，检查问题中是否包含某个指标的关键词
        """
        detected = []
        question_lower = question.lower()

        for alias, standard_name in self.alias_map.items():
            if alias in question_lower and standard_name not in detected:
                detected.append(standard_name)

        return detected

    def get_indicator_text(self, indicator_name: str) -> str:
        """
        将单个指标定义格式化为 Prompt 可用的文本
        """
        ind = self.indicators.get(indicator_name)

        if not ind:
            return ""

        lines = [
            f"指标：{ind['name']}",
            f" 定义：{ind['definition']}",
            f" 计算公式：{ind['formula']}",
            f" 数据来源：{ind['data_source']}",
        ]

        if ind.get("depends_on"):
            lines.append(f" 依赖指标：{', '.join(ind['depends_on'])}")

        if ind.get("filters"):
            lines.append(f" 强制过滤：{' AND '.join(ind['filters'])}")

        return "\n".join(lines)

    def build_knowledge_block(self, question: str) -> str:
        """
        根据用户问题构建指标知识文本块
        返回空字符串表示问题未涉及任何已知指标
        """
        detected = self.detect_indicators(question)

        if not detected:
            return ""

        blocks = ["【指标知识】"]

        for name in detected:
            blocks.append(self.get_indicator_text(name))

            # 如果该指标有依赖，一并注入依赖指标的定义
            ind = self.indicators.get(name)

            if ind and ind.get("depends_on"):
                for dep in ind["depends_on"]:
                    if dep not in detected:
                        blocks.append(self.get_indicator_text(dep))

        return "\n\n".join(blocks)