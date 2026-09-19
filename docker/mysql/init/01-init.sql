-- ChatBI MVP schema and seed data
-- Generated from the running mysql8.4 container (database: chatbi_mvp).
-- Used to bootstrap the compose-managed MySQL on first start.

-- MySQL dump 10.13  Distrib 8.4.10, for Linux (x86_64)
--
-- Host: localhost    Database: chatbi_mvp
-- ------------------------------------------------------
-- Server version	8.4.10

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `dim_customers`
--

DROP TABLE IF EXISTS `dim_customers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dim_customers` (
  `customer_id` int NOT NULL,
  `customer_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `customer_type` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `industry` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `country` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `region` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`customer_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `dim_customers`
--

/*!40000 ALTER TABLE `dim_customers` DISABLE KEYS */;
INSERT INTO `dim_customers` VALUES (1,'某欧洲车企集团','OEM整车厂','交通','Germany','欧洲'),(2,'某北美储能集成商','储能集成商','能源','USA','北美'),(3,'某西班牙经销商','经销商','交通','Spain','欧洲'),(4,'某英国电网集团','电网集团','能源','UK','欧洲'),(5,'某日本换电运营商','换电运营商','交通','Japan','亚太');
/*!40000 ALTER TABLE `dim_customers` ENABLE KEYS */;

--
-- Table structure for table `dim_products`
--

DROP TABLE IF EXISTS `dim_products`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dim_products` (
  `product_id` int NOT NULL,
  `product_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `product_line` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `category` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `tech_route` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `standard_cost` decimal(10,2) DEFAULT NULL,
  `material_cost` decimal(10,2) DEFAULT NULL,
  `labor_cost` decimal(10,2) DEFAULT NULL,
  PRIMARY KEY (`product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `dim_products`
--

/*!40000 ALTER TABLE `dim_products` DISABLE KEYS */;
INSERT INTO `dim_products` VALUES (1,'高能量密度型电芯 280Ah','动力电池-乘用车','高能量密度型','三元锂',850.00,550.00,80.00),(2,'超快充型电池包','动力电池-乘用车','超快充型','磷酸铁锂',620.00,380.00,60.00),(3,'电网级储能集装箱 5MWh','储能系统-电网级','电网级储能型','磷酸铁锂',450000.00,280000.00,45000.00),(4,'低温适配型电芯','动力电池-乘用车','低温适配型','钠离子',720.00,480.00,70.00),(5,'商用车标准型电池包','动力电池-商用车','商用车标准型','磷酸铁锂',580.00,350.00,55.00);
/*!40000 ALTER TABLE `dim_products` ENABLE KEYS */;

--
-- Table structure for table `exchange_rates`
--

DROP TABLE IF EXISTS `exchange_rates`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `exchange_rates` (
  `rate_date` date NOT NULL,
  `currency` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `rate_to_cny` decimal(10,4) DEFAULT NULL,
  PRIMARY KEY (`rate_date`,`currency`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exchange_rates`
--

/*!40000 ALTER TABLE `exchange_rates` DISABLE KEYS */;
INSERT INTO `exchange_rates` VALUES ('2026-01-15','EUR',7.8500),('2026-01-15','JPY',0.0485),('2026-01-15','USD',7.2500),('2026-02-15','EUR',7.8200),('2026-02-15','USD',7.2800),('2026-03-15','EUR',7.8800),('2026-03-15','USD',7.2200);
/*!40000 ALTER TABLE `exchange_rates` ENABLE KEYS */;

--
-- Table structure for table `finance_expenses`
--

DROP TABLE IF EXISTS `finance_expenses`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `finance_expenses` (
  `expense_id` bigint NOT NULL,
  `expense_date` date DEFAULT NULL,
  `department` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `rd_expense` decimal(12,2) DEFAULT NULL,
  `selling_expense` decimal(12,2) DEFAULT NULL,
  `admin_expense` decimal(12,2) DEFAULT NULL,
  `finance_expense` decimal(12,2) DEFAULT NULL,
  `marketing_expense` decimal(12,2) DEFAULT NULL,
  `logistics_expense` decimal(12,2) DEFAULT NULL,
  `warranty_expense` decimal(12,2) DEFAULT NULL,
  PRIMARY KEY (`expense_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `finance_expenses`
--

/*!40000 ALTER TABLE `finance_expenses` DISABLE KEYS */;
INSERT INTO `finance_expenses` VALUES (1,'2026-01-31','销售部',800000.00,400000.00,250000.00,80000.00,150000.00,80000.00,50000.00),(2,'2026-02-28','销售部',850000.00,420000.00,255000.00,78000.00,160000.00,85000.00,55000.00),(3,'2026-03-31','销售部',900000.00,450000.00,260000.00,75000.00,170000.00,90000.00,60000.00);
/*!40000 ALTER TABLE `finance_expenses` ENABLE KEYS */;

--
-- Table structure for table `sales_orders`
--

DROP TABLE IF EXISTS `sales_orders`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sales_orders` (
  `order_id` bigint NOT NULL,
  `order_no` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `customer_id` int DEFAULT NULL,
  `product_id` int DEFAULT NULL,
  `region` varchar(50) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `order_date` date DEFAULT NULL,
  `order_status` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `quantity` decimal(10,2) DEFAULT NULL,
  `unit_price` decimal(10,2) DEFAULT NULL,
  `discount_amount` decimal(10,2) DEFAULT NULL,
  `gross_amount` decimal(12,2) DEFAULT NULL,
  `net_amount` decimal(12,2) DEFAULT NULL,
  `currency` varchar(10) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`order_id`),
  UNIQUE KEY `order_no` (`order_no`),
  KEY `customer_id` (`customer_id`),
  KEY `product_id` (`product_id`),
  CONSTRAINT `sales_orders_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `dim_customers` (`customer_id`),
  CONSTRAINT `sales_orders_ibfk_2` FOREIGN KEY (`product_id`) REFERENCES `dim_products` (`product_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `sales_orders`
--

/*!40000 ALTER TABLE `sales_orders` DISABLE KEYS */;
INSERT INTO `sales_orders` VALUES (1,'SO202601001',1,1,'欧洲','2026-01-15','completed',500.00,1200.00,50000.00,678000.00,600000.00,'EUR'),(2,'SO202601002',2,3,'北美','2026-01-15','completed',2.00,550000.00,50000.00,1210000.00,1070796.46,'USD'),(3,'SO202602001',3,2,'欧洲','2026-02-15','completed',300.00,1500.00,30000.00,508500.00,450000.00,'EUR'),(4,'SO202602002',4,4,'欧洲','2026-02-15','completed',200.00,1300.00,20000.00,293800.00,260000.00,'EUR'),(5,'SO202603001',5,5,'亚太','2026-03-15','completed',150.00,1100.00,15000.00,186450.00,165000.00,'USD');
/*!40000 ALTER TABLE `sales_orders` ENABLE KEYS */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-09-19  6:11:38
