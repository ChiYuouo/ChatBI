from openai import OpenAI
import os
from  dotenv import load_dotenv
import re
load_dotenv()

SCHEMA = """
表：dim_customers（客户维度表）
- customer_id INT 主键
- customer_name VARCHAR(100) 客户名称
- customer_type VARCHAR(50) 客户类型：OEM 整车厂 / 储能集成商 / 电网集团 /
工商业用户 / 换电运营商 / 经销商
- industry VARCHAR(50) 客户行业：交通 / 能源 / 工业 / 特种交通
- country VARCHAR(50) 具体国家，如 Germany
- region VARCHAR(50) 大区，如 欧洲、北美
表：dim_products（产品维度表）
- product_id INT 主键
- product_name VARCHAR(100) 产品名称
- product_line VARCHAR(50) 产品线：动力电池-乘用车 / 动力电池-商用车 / 储能
系统-电网级 / 储能系统-工商业 / 电池材料与回收
- category VARCHAR(50) 产品分类：高能量密度型 / 超快充型 / 混动专用型 / 低温
适配型 / 商用车标准型 / 电网级储能型 / 工商业储能型
- tech_route VARCHAR(50) 技术路线：三元锂 / 磷酸铁锂 / 钠离子 / 固态电池
- standard_cost DECIMAL(10,2) 标准成本
- material_cost DECIMAL(10,2) 材料成本
- labor_cost DECIMAL(10,2) 人工成本
表：sales_orders（销售订单表）
- order_id BIGINT 主键
- order_no VARCHAR(50) 订单编号
- customer_id INT 外键 → dim_customers.customer_id
- product_id INT 外键 → dim_products.product_id
- region VARCHAR(50) 销售区域
- order_date DATE 订单日期
- order_status VARCHAR(20) 订单状态
- quantity DECIMAL(10,2) 数量（MWh 或套数）
- unit_price DECIMAL(10,2) 单价（每 MWh 或每套价格，不含税）
- discount_amount DECIMAL(10,2) 折扣金额
- gross_amount DECIMAL(12,2) 含税总额
- net_amount DECIMAL(12,2) 不含税收入（财务口径的销售额）
- currency VARCHAR(10) 币种
表：exchange_rates（汇率表）
- rate_date DATE 日期
- currency VARCHAR(10) 币种
- rate_to_cny DECIMAL(10,4) 兑人民币汇率
表：finance_expenses（费用表）
- expense_id BIGINT 主键
- expense_date DATE 费用日期
- department VARCHAR(50) 部门
- rd_expense DECIMAL(12,2) 研发费用（新能源企业研发投入大）
- selling_expense DECIMAL(12,2) 销售费用
- admin_expense DECIMAL(12,2) 管理费用
- finance_expense DECIMAL(12,2) 财务费用
- marketing_expense DECIMAL(12,2) 市场费用（属于销售费用子项）
- logistics_expense DECIMAL(12,2) 物流费用
- warranty_expense DECIMAL(12,2) 质保费用
"""

def build_prompt(query:str)->str:
    prompt=(f"""请根据用户输入的查询语句生成对应的SQL查询语句，不要任何解释。
【数据库结构】
{SCHEMA}
【用户输入】
{query}
""")
    return prompt

client=OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
)

def generate_sql(query:str)->str:
    prompt=build_prompt(query)
    response=client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        messages=[
            {"role":"user","content":prompt},
        ],
        temperature=0.2
    )
    content=response.choices[0].message.content.strip()
    sql=re.sub(r'```sql|```','',content)
    return sql

if __name__=="__main__":
    query="上个月销售额多少"
    sql=generate_sql(query)
    print(sql)