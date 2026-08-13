"""
LLM 客户端模块
负责调用大模型 API 生成 SQL。
将 LLM 调用封装为独立模块，便于后续切换不同模型或增加重试逻辑。
"""

import re
from typing import Generator

from openai import OpenAI
from config import LLM_CONFIG


class LLMClient:
    """LLM API 客户端"""

    def __init__(self):
        self.client = OpenAI(
            api_key=LLM_CONFIG["api_key"],
            base_url=LLM_CONFIG["base_url"]
        )

        self.model = LLM_CONFIG["model"]
        self.temperature = LLM_CONFIG["temperature"]
        self.max_tokens = LLM_CONFIG["max_tokens"]
        self.embedding_model = LLM_CONFIG["embedding_model"]

    def generate_sql(self, system_msg: str, prompt: str) -> str:
        """
        调用 LLM 生成 SQL（同步，一次性返回）

        Args:
            system_msg: 系统角色消息
            prompt: 完整的用户 Prompt

        Returns:
            提取后的纯 SQL 字符串
        """
        raw_output = self.generate_text(system_msg=system_msg, prompt=prompt)

        # 提取 SQL：去除 markdown 代码块标记
        sql = re.sub(r'```sql|```', '', raw_output).strip()

        return sql

    def generate_text(self, system_msg: str, prompt: str) -> str:
        """
        调用 LLM 生成普通文本（同步，一次性返回）

        Args:
            system_msg: 系统角色消息
            prompt: 完整的用户 Prompt

        Returns:
            模型返回的原始文本内容
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens
        )
        return response.choices[0].message.content.strip()

    def generate_sql_stream(self, system_msg: str, prompt: str) -> Generator[str,
    None, None]:
        """调用 LLM 流式生成 SQL（逐 chunk 产出）"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt}
            ],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta_content = chunk.choices[0].delta.content
            if delta_content is not None:
                yield delta_content

    def get_embedding(self, text: str) -> list[float]:
        resp = self.client.embeddings.create(
            model=self.embedding_model,
            input=text,
        )
        embedding = resp.data[0].embedding
        return embedding

if __name__ == "__main__":
    llm_client = LLMClient()
    client = LLMClient()
    vec = client.get_embedding("欧洲市场的销售额")
    print(f"向量维度: {len(vec)}")
    print(f"前 5 个值: {vec[:5]}")
