#!/bin/bash
# 官方 MySQL 镜像首次初始化时加载；已有演示卷也可显式执行此脚本。
set -eu

: "${MYSQL_DATABASE:?MYSQL_DATABASE is required}"
: "${DB_PASSWORD:?DB_PASSWORD is required for the analysis reader}"
reader_name="${DB_USER:-chatbi_reader}"
case "$MYSQL_DATABASE" in ''|*[!a-zA-Z0-9_]*) echo 'Invalid database name' >&2; exit 1;; esac
case "$reader_name" in ''|*[!a-zA-Z0-9_]*) echo 'Invalid reader name' >&2; exit 1;; esac
if [ "$reader_name" = root ]; then echo 'Analysis account cannot be root' >&2; exit 1; fi

# 官方入口已提供 docker_process_sql；手动执行时用容器内 root 环境变量。
if ! declare -F docker_process_sql >/dev/null; then
    : "${MYSQL_ROOT_PASSWORD:?MYSQL_ROOT_PASSWORD is required}"
    docker_process_sql() {
        MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --protocol=socket -uroot --database="$MYSQL_DATABASE" "$@"
    }
fi

# 固定 NO_BACKSLASH_ESCAPES，再双写单引号；密码只进 SQL 标准输入，不打印。
reader_password="${DB_PASSWORD//\'/\'\'}"
docker_process_sql <<SQL
SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES';
CREATE USER IF NOT EXISTS '$reader_name'@'%' IDENTIFIED BY '$reader_password';
ALTER USER '$reader_name'@'%' IDENTIFIED BY '$reader_password';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '$reader_name'@'%';
GRANT SELECT ON \`$MYSQL_DATABASE\`.\`dim_customers\` TO '$reader_name'@'%';
GRANT SELECT ON \`$MYSQL_DATABASE\`.\`dim_products\` TO '$reader_name'@'%';
GRANT SELECT ON \`$MYSQL_DATABASE\`.\`sales_orders\` TO '$reader_name'@'%';
GRANT SELECT ON \`$MYSQL_DATABASE\`.\`exchange_rates\` TO '$reader_name'@'%';
GRANT SELECT ON \`$MYSQL_DATABASE\`.\`finance_expenses\` TO '$reader_name'@'%';
SQL
