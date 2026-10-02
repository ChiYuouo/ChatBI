# ChatBI Text-to-SQL 评估报告

> 生成时间：2026-10-02 20:44:30

## 总体结果

| 指标 | 数量 | 比例 |
|---|---:|---:|
| 总用例 | 50 | 100.0% |
| 执行结果正确 | 42 | 84.0% |
| SQL 完全一致 | 0 | 0.0% |
| 执行失败 | 0 | 0.0% |
| 执行成功但结果不匹配 | 8 | 16.0% |

## 自动总结

整体已具备基础可用性，但仍需针对薄弱难度继续优化。 当前最薄弱的难度是 **medium**，正确率为 **70.0%**。

## 按难度统计

| 难度 | 正确 | 总数 | 正确率 | 执行失败 |
|---|---:|---:|---:|---:|
| simple | 14 | 15 | 93.3% | 0 |
| medium | 14 | 20 | 70.0% | 0 |
| complex | 14 | 15 | 93.3% | 0 |

## 用例明细

| ID | 难度 | 状态 | 问题 | 预期行数 | 生成行数 |
|---|---|---|---|---:|---:|
| S01 | simple | ✅ 通过 | 查询已完成订单的总数量 | 1 | 1 |
| S02 | simple | ✅ 通过 | 查询有多少种不同的产品线 | 1 | 1 |
| S03 | simple | ✅ 通过 | 查询 2026 年 1 月的总研发费用 | 1 | 1 |
| M01 | medium | ✅ 通过 | 按客户类型统计已完成订单的数量 | 5 | 5 |
| M02 | medium | ⚠️ 结果不匹配 | 按产品线统计总收入 | 3 | 3 |
| M03 | medium | ✅ 通过 | 查询欧洲市场最近三个月的总收入 | 1 | 1 |
| C01 | complex | ✅ 通过 | 按大区统计本季度总收入（人民币口径） | 0 | 0 |
| C02 | complex | ⚠️ 结果不匹配 | 按产品线统计平均客单价和订单数量 | 3 | 3 |
| C03 | complex | ✅ 通过 | 查询上个月的销售额、销售成本及毛利 | 1 | 1 |
| I01 | complex | ✅ 通过 | 查询上个月的毛利 | 1 | 1 |
| I02 | complex | ✅ 通过 | 查询上个月的利润 | 1 | 1 |
| S04 | simple | ✅ 通过 | 查询待处理订单的总数量 | 1 | 1 |
| S05 | simple | ✅ 通过 | 查询 2026 年第二季度取消的订单数量 | 1 | 1 |
| S06 | simple | ✅ 通过 | 查询所有产品的平均标准成本 | 1 | 1 |
| S07 | simple | ✅ 通过 | 查询已完成订单涉及多少种币种 | 1 | 1 |
| S08 | simple | ⚠️ 结果不匹配 | 查询已完成订单中最大的不含税金额 | 1 | 1 |
| S09 | simple | ✅ 通过 | 查询 2026 年 5 月已完成订单的总业务数量 | 1 | 1 |
| S10 | simple | ✅ 通过 | 查询德国客户数量 | 1 | 1 |
| S11 | simple | ✅ 通过 | 查询欧洲大区客户数量 | 1 | 1 |
| S12 | simple | ✅ 通过 | 查询 2026 年第一季度管理费用总额 | 1 | 1 |
| S13 | simple | ✅ 通过 | 查询产品中的最低材料成本 | 1 | 1 |
| S14 | simple | ✅ 通过 | 查询固态电池技术路线的产品数量 | 1 | 1 |
| S15 | simple | ✅ 通过 | 查询 2026 年第二季度已完成订单的折扣总额 | 1 | 1 |
| M04 | medium | ✅ 通过 | 按订单状态统计订单数量 | 1 | 1 |
| M05 | medium | ✅ 通过 | 按大区统计客户数量 | 3 | 3 |
| M06 | medium | ✅ 通过 | 按月统计 2026 年第二季度已完成订单数量 | 0 | 0 |
| M07 | medium | ✅ 通过 | 按产品线统计已完成订单的总业务数量 | 3 | 3 |
| M08 | medium | ⚠️ 结果不匹配 | 按技术路线统计已完成订单的平均单价 | 3 | 3 |
| M09 | medium | ✅ 通过 | 按部门统计 2026 年第一季度期间费用总额 | 1 | 1 |
| M10 | medium | ✅ 通过 | 查询 2026 年第二季度原币收入最高的 5 个客户 | 0 | 0 |
| M11 | medium | ✅ 通过 | 按产品分类统计 2026 年第二季度已完成订单的原币含税总额 | 0 | 0 |
| M12 | medium | ⚠️ 结果不匹配 | 按月统计 2026 年第一季度期间费用 | 3 | 3 |
| M13 | medium | ✅ 通过 | 按国家统计有已完成订单的不同客户数 | 5 | 5 |
| M14 | medium | ⚠️ 结果不匹配 | 按币种统计已完成订单数量 | 2 | 2 |
| M15 | medium | ⚠️ 结果不匹配 | 按产品线统计已完成订单的平均折扣金额 | 3 | 3 |
| M16 | medium | ✅ 通过 | 按客户行业统计已完成订单数量 | 2 | 2 |
| M17 | medium | ✅ 通过 | 按产品线统计已完成订单的平均业务数量 | 3 | 3 |
| M18 | medium | ✅ 通过 | 查询欧洲市场 2026 年第二季度已完成订单的原币平均金额 | 1 | 1 |
| M19 | medium | ⚠️ 结果不匹配 | 查询材料成本最高的 10 个产品 | 5 | 5 |
| M20 | medium | ✅ 通过 | 按部门统计 2026 年第二季度销售费用 | 0 | 0 |
| C04 | complex | ✅ 通过 | 查询 2026 年 5 月人民币口径的毛利 | 1 | 1 |
| C05 | complex | ✅ 通过 | 查询 2026 年 5 月的利润 | 1 | 1 |
| C06 | complex | ✅ 通过 | 按产品线统计 2026 年第二季度人民币口径毛利率 | 0 | 0 |
| C07 | complex | ✅ 通过 | 按月统计 2026 年第二季度人民币收入 | 0 | 0 |
| C08 | complex | ✅ 通过 | 查询从未下过订单的客户 | 0 | 0 |
| C09 | complex | ✅ 通过 | 查询从未产生已完成订单的产品 | 0 | 0 |
| C10 | complex | ✅ 通过 | 按客户类型统计 2026 年第二季度人民币口径毛利 | 0 | 0 |
| C11 | complex | ✅ 通过 | 查询 2026 年第二季度人民币毛利最高的 3 个国家 | 0 | 0 |
| C12 | complex | ✅ 通过 | 统计 2026 年第二季度各大区人民币收入及其占比，并按收入降序排列 | 0 | 0 |
| C13 | complex | ✅ 通过 | 按产品线统计 2026 年第二季度已完成和已取消订单数量 | 0 | 0 |

## 失败与不匹配详情

### M02 · 按产品线统计总收入

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT p.product_line, SUM(o.net_amount) AS total_revenue FROM sales_orders o JOIN dim_products p ON o.product_id = p.product_id WHERE o.order_status = 'completed' GROUP BY p.product_line
```

生成 SQL：

```sql
SELECT 
    p.product_line,
    SUM(o.net_amount * r.rate_to_cny) AS total_revenue_cny
FROM sales_orders o
JOIN dim_products p ON o.product_id = p.product_id
JOIN exchange_rates r ON o.order_date = r.rate_date AND o.currency = r.currency
WHERE o.order_status = 'completed'
GROUP BY p.product_line
ORDER BY total_revenue_cny DESC;
```

### C02 · 按产品线统计平均客单价和订单数量

- 难度：`complex`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT p.product_line, AVG(o.net_amount) AS avg_order_value, COUNT(*) AS order_count FROM sales_orders o JOIN dim_products p ON o.product_id = p.product_id WHERE o.order_status = 'completed' GROUP BY p.product_line
```

生成 SQL：

```sql
SELECT 
    p.product_line,
    COUNT(*) AS order_count,
    AVG(o.net_amount * r.rate_to_cny) AS avg_order_value_cny
FROM sales_orders o
JOIN dim_products p ON o.product_id = p.product_id
JOIN exchange_rates r ON o.order_date = r.rate_date AND o.currency = r.currency
WHERE o.order_status = 'completed'
GROUP BY p.product_line
ORDER BY p.product_line;
```

### S08 · 查询已完成订单中最大的不含税金额

- 难度：`simple`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT MAX(net_amount) AS max_net_amount FROM sales_orders WHERE order_status = 'completed'
```

生成 SQL：

```sql
SELECT MAX(o.net_amount * r.rate_to_cny) AS max_revenue_cny
FROM sales_orders o
JOIN exchange_rates r
  ON o.order_date = r.rate_date
 AND o.currency = r.currency
WHERE o.order_status = 'completed';
```

### M08 · 按技术路线统计已完成订单的平均单价

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT p.tech_route, AVG(o.unit_price) AS avg_unit_price FROM sales_orders o JOIN dim_products p ON o.product_id = p.product_id WHERE o.order_status = 'completed' GROUP BY p.tech_route
```

生成 SQL：

```sql
SELECT 
    p.tech_route,
    AVG(o.unit_price * r.rate_to_cny) AS avg_unit_price_cny
FROM sales_orders o
JOIN dim_products p ON o.product_id = p.product_id
JOIN exchange_rates r ON o.order_date = r.rate_date AND o.currency = r.currency
WHERE o.order_status = 'completed'
GROUP BY p.tech_route
ORDER BY p.tech_route;
```

### M12 · 按月统计 2026 年第一季度期间费用

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT DATE_FORMAT(expense_date, '%Y-%m') AS month, SUM(rd_expense + selling_expense + admin_expense + finance_expense) AS total_expense FROM finance_expenses WHERE expense_date >= '2026-01-01' AND expense_date < '2026-04-01' GROUP BY DATE_FORMAT(expense_date, '%Y-%m')
```

生成 SQL：

```sql
SELECT
    DATE_FORMAT(expense_date, '%Y-%m-01') AS month,
    SUM(rd_expense + selling_expense + admin_expense + finance_expense) AS total_expense
FROM finance_expenses
WHERE expense_date >= '2026-01-01'
  AND expense_date < '2026-04-01'
GROUP BY DATE_FORMAT(expense_date, '%Y-%m-01')
ORDER BY month;
```

### M14 · 按币种统计已完成订单数量

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT currency, COUNT(*) AS order_count FROM sales_orders WHERE order_status = 'completed' GROUP BY currency
```

生成 SQL：

```sql
SELECT 
    o.currency,
    COUNT(*) AS completed_order_count
FROM sales_orders o
WHERE o.order_status = 'completed'
GROUP BY o.currency
ORDER BY o.currency;
```

### M15 · 按产品线统计已完成订单的平均折扣金额

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT p.product_line, AVG(o.discount_amount) AS avg_discount FROM sales_orders o JOIN dim_products p ON o.product_id = p.product_id WHERE o.order_status = 'completed' GROUP BY p.product_line
```

生成 SQL：

```sql
SELECT 
    p.product_line,
    AVG(o.discount_amount) AS avg_discount_amount
FROM sales_orders o
JOIN dim_products p ON o.product_id = p.product_id
WHERE o.order_status = 'completed'
GROUP BY p.product_line
ORDER BY p.product_line;
```

### M19 · 查询材料成本最高的 10 个产品

- 难度：`medium`
- 状态：⚠️ 结果不匹配

预期 SQL：

```sql
SELECT product_name, material_cost FROM dim_products ORDER BY material_cost DESC LIMIT 10
```

生成 SQL：

```sql
SELECT 
    product_id,
    product_name,
    material_cost
FROM dim_products
ORDER BY material_cost DESC
LIMIT 10;
```
