import pymysql
from config import DB_CONFIG

#1.执行sql
class DatabaseClient:
    def __init__(self):
        self.config = DB_CONFIG


    def execute(self,sql):
        conn= pymysql.connect(**self.config)
        try:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                colums = [d[0] for d in cursor.description]
                result = cursor.fetchall()
                return colums,result
        finally:
            conn.close()

        return []

    def validate_connection(self)->bool:
        """验证当前数据库连接是否正常"""
        try:
            conn= pymysql.connect(**self.config)
            conn.close()
            return True
        except:
            return False

if __name__ == "__main__":
    db = DatabaseClient()
    print("数据库连接状态：",db.validate_connection())
    result = db.execute('select * from sales_orders')
    print(result)
