"""为本次请求绑定模型预算，不修改共享模型客户端。"""
from chatbi.execution.budget import ExecutionBudget
from chatbi.infrastructure.llm_client import LLMClient


class BudgetedLLM:
    def __init__(self, provider, budget: ExecutionBudget):
        self.provider = provider.provider if isinstance(provider, BudgetedLLM) else provider
        self.budget = budget

    def __getattr__(self, name):
        if name == "client" and isinstance(self.provider, LLMClient):
            return self.provider.request_client(self.budget)
        return getattr(self.provider, name)

    def _call(self, name, *args, **kwargs):
        self.budget.remaining()
        if isinstance(self.provider, LLMClient):
            kwargs["budget"] = self.budget
        value = getattr(self.provider, name)(*args, **kwargs)
        self.budget.remaining()
        return value

    def generate_text(self, *args, **kwargs):
        return self._call("generate_text", *args, **kwargs)

    def generate_sql(self, *args, **kwargs):
        return self._call("generate_sql", *args, **kwargs)

    def generate_sql_stream(self, *args, **kwargs):
        self.budget.remaining()
        if isinstance(self.provider, LLMClient):
            kwargs["budget"] = self.budget
        stream = self.provider.generate_sql_stream(*args, **kwargs)
        try:
            for chunk in stream:
                self.budget.remaining()
                yield chunk
            self.budget.remaining()
        finally:
            if hasattr(stream, "close"):
                stream.close()
