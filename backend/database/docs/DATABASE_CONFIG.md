# Database Configuration Guide

The Phoveus supports multiple database engines through a **simple connection string** configuration system. This guide explains how to configure different database types.

## Supported Database Engines

- **SQLite** (Default - No additional setup required)
- **PostgreSQL** 
- **MySQL**
- **MariaDB**
- **Oracle**
- **Microsoft SQL Server**

## Simple Configuration Approach

The system now uses a **single connection string** instead of multiple configuration fields. This follows standard database URL conventions and is much simpler to manage.

### Environment Variable Configuration

Set the `DATABASE_URL` environment variable:

```bash
# SQLite (default)
DATABASE_URL=sqlite:///./database/product_cache.db

# PostgreSQL
DATABASE_URL=postgresql://user:password@localhost:5432/maborak

# MySQL
DATABASE_URL=mysql+pymysql://user:password@localhost:3306/maborak

# MariaDB  
DATABASE_URL=mariadb+pymysql://user:password@localhost:3306/maborak

# Oracle
DATABASE_URL=oracle+cx_oracle://user:password@localhost:1521/maborak

# SQL Server
DATABASE_URL=mssql+pyodbc://user:password@localhost:1433/maborak?driver=ODBC+Driver+17+for+SQL+Server
```

### Optional Settings

Additional database settings via environment variables:

```bash
# Debug settings
DB_ECHO=false              # Set to true for SQL query logging
DB_ECHO_POOL=false         # Set to true for connection pool logging

# Connection pool settings (for non-SQLite databases)
DB_POOL_SIZE=5             # Number of connections to maintain
DB_MAX_OVERFLOW=10         # Additional connections when pool is full
DB_POOL_TIMEOUT=30         # Seconds to wait for connection
DB_POOL_RECYCLE=3600       # Seconds before recreating connections
```

## Database-Specific Setup

### SQLite (Default)

No additional setup required. The database file will be created automatically.

```bash
DATABASE_URL=sqlite:///./database/product_cache.db
```

### PostgreSQL

1. Install required driver:
```bash
pip install psycopg2-binary
```

2. Create database and user:
```sql
CREATE DATABASE maborak;
CREATE USER your_username WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE maborak TO your_username;
```

3. Configure connection string:
```bash
DATABASE_URL=postgresql://your_username:your_password@localhost:5432/maborak
```

4. SSL Configuration (optional):
```bash
DATABASE_URL=postgresql://user:pass@host:5432/db?sslmode=require&sslcert=/path/to/client-cert.pem&sslkey=/path/to/client-key.pem&sslrootcert=/path/to/ca-cert.pem
```

### MySQL

1. Install required driver:
```bash
pip install PyMySQL
```

2. Create database and user:
```sql
CREATE DATABASE maborak CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'your_username'@'localhost' IDENTIFIED BY 'your_password';
GRANT ALL PRIVILEGES ON maborak.* TO 'your_username'@'localhost';
FLUSH PRIVILEGES;
```

3. Configure connection string:
```bash
DATABASE_URL=mysql+pymysql://your_username:your_password@localhost:3306/maborak
```

4. SSL Configuration (optional):
```bash
DATABASE_URL=mysql+pymysql://user:pass@host:3306/db?ssl_ca=/path/to/ca-cert.pem&ssl_cert=/path/to/client-cert.pem&ssl_key=/path/to/client-key.pem
```

### MariaDB

1. Install required driver:
```bash
pip install PyMySQL
```

2. Setup is similar to MySQL:
```bash
DATABASE_URL=mariadb+pymysql://your_username:your_password@localhost:3306/maborak
```

### Oracle

1. Install required driver:
```bash
pip install cx_Oracle
```

2. Configure connection string:
```bash
DATABASE_URL=oracle+cx_oracle://your_username:your_password@localhost:1521/maborak
```

### Microsoft SQL Server

1. Install required drivers:
```bash
pip install pyodbc
# Also install ODBC Driver 17 for SQL Server on your system
```

2. Configure connection string:
```bash
DATABASE_URL=mssql+pyodbc://your_username:your_password@localhost:1433/maborak?driver=ODBC+Driver+17+for+SQL+Server&Encrypt=yes
```

## Testing Configuration

Test your database configuration:

```bash
# Test database connectivity
python database/test_config.py --test

# Show current configuration
python database/test_config.py --config

# Show example connection strings
python database/test_config.py --examples

# Show all information and test
python database/test_config.py --all

# Using the main API
python api_main.py --test-db
python api_main.py --show-db-config
```

## Docker Compose Examples

### PostgreSQL:
```yaml
version: '3.8'
services:
  app:
    build: .
    environment:
      DATABASE_URL: postgresql://amazon:amazon@postgres:5432/maborak
    depends_on:
      - postgres
      
  postgres:
    image: postgres:13
    environment:
      POSTGRES_DB: maborak
      POSTGRES_USER: amazon
      POSTGRES_PASSWORD: amazon
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### MySQL:
```yaml
version: '3.8'
services:
  app:
    build: .
    environment:
      DATABASE_URL: mysql+pymysql://amazon:amazon@mysql:3306/maborak
    depends_on:
      - mysql
      
  mysql:
    image: mysql:8.0
    environment:
      MYSQL_DATABASE: maborak
      MYSQL_USER: amazon
      MYSQL_PASSWORD: amazon
      MYSQL_ROOT_PASSWORD: root_password
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql

volumes:
  mysql_data:
```

## Connection String Format

### General Format
```
scheme://[user[:password]@]host[:port]/database[?param1=value1&param2=value2]
```

### Scheme Examples
- `sqlite://` - SQLite database
- `postgresql://` - PostgreSQL  
- `mysql+pymysql://` - MySQL with PyMySQL driver
- `mariadb+pymysql://` - MariaDB with PyMySQL driver
- `oracle+cx_oracle://` - Oracle with cx_Oracle driver
- `mssql+pyodbc://` - SQL Server with pyodbc driver

### Query Parameters
Common parameters that can be added to connection strings:

**PostgreSQL:**
- `sslmode=require` - Require SSL
- `sslcert=/path/to/cert.pem` - Client certificate
- `sslkey=/path/to/key.pem` - Client key
- `sslrootcert=/path/to/ca.pem` - CA certificate

**MySQL/MariaDB:**
- `ssl_ca=/path/to/ca.pem` - CA certificate
- `ssl_cert=/path/to/cert.pem` - Client certificate
- `ssl_key=/path/to/key.pem` - Client key

**SQL Server:**
- `driver=ODBC+Driver+17+for+SQL+Server` - ODBC driver
- `Encrypt=yes` - Enable encryption
- `TrustServerCertificate=no` - Verify certificate

## Migration from Old Configuration

If you're upgrading from the previous complex configuration system:

1. **Identify your current settings** from the old configuration
2. **Construct the connection string** using the format above
3. **Set the `DATABASE_URL` environment variable**
4. **Remove old environment variables** (DB_ENGINE, DB_HOST, etc.)
5. **Test the new configuration** using the test utilities

### Example Migration

**Old Configuration:**
```bash
DB_ENGINE=mysql
DB_HOST=192.168.0.27
DB_PORT=3307
DB_NAME=amazon
DB_USER=amazon
DB_PASSWORD=amazon
```

**New Configuration:**
```bash
DATABASE_URL=mysql+pymysql://amazon:amazon@192.168.0.27:3307/amazon
```

## Troubleshooting

### Common Issues:

1. **Connection Refused**: Check if database server is running and accessible
2. **Authentication Failed**: Verify username and password in connection string
3. **Database Not Found**: Ensure database exists and user has access
4. **Driver Errors**: Install required database drivers
5. **SSL Errors**: Check SSL configuration and certificate paths

### Debug Mode:
Enable SQL query logging:
```bash
DB_ECHO=true
DB_ECHO_POOL=true
```

### Getting Help:
```bash
# Show driver requirements
python database/test_config.py --requirements

# Show example connection strings
python database/test_config.py --examples

# Test current configuration
python api_main.py --test-db
```

For additional assistance, check the logs or enable debug mode to see detailed SQL queries and connection information. 