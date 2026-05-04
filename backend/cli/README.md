# Phoveus CLI

Internal command-line interface for administrative tasks using hexagonal architecture.

## 🏗️ Architecture

The CLI follows the same **hexagonal architecture** principles as the API:

```
┌─────────────────────────────────────────────────────────────────┐
│                           CLI Layer                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │   Main CLI      │ │   Commands      │ │   Click UI      │   │
│  │   (Entry)       │ │   (monitor)     │ │   (Interface)   │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘   │
└─────────────────────────┬───────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────────┐
│                   SAME SERVICES AS API                         │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐   │
│  │ProductMonitoring│ │   Database      │ │  Web Scraping   │   │
│  │    Service      │ │   Adapter       │ │    Adapter      │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Key Benefits:**
- **Consistency**: Uses the same business logic as the API
- **Maintainability**: Changes to core logic apply to both CLI and API
- **Testing**: Can test business logic once for both interfaces
- **Dependency Injection**: Clean separation of concerns

## 🚀 Installation

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Make CLI Executable** (optional):
   ```bash
   chmod +x cli.py
   ```

## 📖 Usage

### Basic Commands

```bash
# Show CLI help
python cli.py --help

# Show monitor commands help
python cli.py monitor --help

# Show specific command help
python cli.py monitor check --help
```

### Monitor Commands

#### Check All Products
```bash
# Check all products in database
python cli.py monitor check

# Check with verbose output
python cli.py --verbose monitor check

# Dry run (see what would be checked)
python cli.py monitor check --dry-run
```

#### Check with Limits
```bash
# Check only first 5 products
python cli.py monitor check --limit 5

# Check with custom delay between requests
python cli.py monitor check --delay 3.0
```

#### Force Fresh Checks
```bash
# Force fresh scraping (bypass cache)
python cli.py monitor check --force

# Force check with limits
python cli.py monitor check --force --limit 3
```

#### Filter by State
```bash
# Check only available products
python cli.py monitor check --state-filter available

# Check only unavailable products  
python cli.py monitor check --state-filter unavailable

# Check pending products
python cli.py monitor check --state-filter pending
```

### Advanced Usage

```bash
# Comprehensive check with all options
python cli.py --verbose monitor check \
  --force \
  --limit 10 \
  --delay 2.5 \
  --state-filter available

# Quick dry run to see current database state
python cli.py monitor check --dry-run --limit 20
```

## 📊 Command Output

### Example Output
```
🔍 Phoveus - CLI
==================================================
📋 Getting all products from database...
📊 Found 15 products to check

🚀 Starting product checks...

🔍 [1/15] Checking B0DS2X13PH...
   ✅ AVAILABLE - $39.48

🔍 [2/15] Checking B0DS2WQZ2M...
   ❌ NOT AVAILABLE

🔍 [3/15] Checking B0CHN643V2...
   ✅ AVAILABLE - $25.99

==================================================
📊 FINAL SUMMARY
==================================================
✅ Available products:     2
❌ Unavailable products:   13
⚠️  Errors:                0
📈 Total processed:        15
⏱️  Total time:             31.2 seconds
📊 Average time per check: 2.1 seconds

🚨 2 PRODUCT(S) ARE AVAILABLE!

📝 Available Products:
  • B0DS2X13PH: Example Product 1... - $39.48
  • B0CHN643V2: Example Product 2... - $25.99

📊 Database Stats:
  • Total products in DB: 15
  • Available in DB: 2
  • Recent checks (24h): 15
```

## 🔧 Configuration

The CLI uses the same configuration as the API:

- **Database**: SQLite database with product cache
- **HTML Cleaning**: Configured via `config.py`
- **Rate Limiting**: Built-in delays between requests
- **Error Handling**: Comprehensive error catching and reporting

## 🧪 Dry Run Mode

Use dry run mode to preview operations without making changes:

```bash
python cli.py monitor check --dry-run
```

**Dry run shows:**
- Which products would be checked
- Current product states
- Estimated execution time
- No actual web scraping performed

## ⚡ Performance Tips

1. **Use Limits for Testing**:
   ```bash
   python cli.py monitor check --limit 5
   ```

2. **Adjust Delays**:
   ```bash
   # Faster (but more aggressive)
   python cli.py monitor check --delay 1.0
   
   # Slower (more respectful)
   python cli.py monitor check --delay 5.0
   ```

3. **Use Cache Efficiently**:
   ```bash
   # Use cache for recent data
   python cli.py monitor check
   
   # Force fresh data when needed
   python cli.py monitor check --force
   ```

4. **Filter by State**:
   ```bash
   # Only check products that can change
   python cli.py monitor check --state-filter unavailable
   ```

## 🔒 Security & Rate Limiting

- **Built-in Delays**: Automatic delays between requests
- **User Agent Rotation**: Different user agents for each request
- **Error Handling**: Graceful handling of rate limits and blocks
- **Respectful Scraping**: Follows web scraping best practices

## 🚀 Adding New Commands

The CLI is designed to be extensible. To add new commands:

1. **Create Command Module**:
   ```python
   # cli/commands/database.py
   @click.group()
   def database():
       """Database management commands"""
       pass
   
   @database.command()
   def stats():
       """Show database statistics"""
       # Implementation here
   ```

2. **Register in Main CLI**:
   ```python
   # cli/main.py
   from cli.commands import database
   cli.add_command(database.database)
   ```

3. **Use Hexagonal Architecture**:
   ```python
   # Access services via dependency injection
   services = ctx.obj['services']
   data_adapter = services.data_persistence_adapter
   ```

## 🐛 Troubleshooting

### Common Issues

1. **No Products Found**:
   ```
   ❌ No products found in database
   💡 Add products by checking them via the API first
   ```
   **Solution**: Use the API to check some products first.

2. **Import Errors**:
   ```
   ModuleNotFoundError: No module named 'click'
   ```
   **Solution**: Install dependencies with `pip install -r requirements.txt`

3. **Database Errors**:
   ```
   ❌ Error getting products from database
   ```
   **Solution**: Initialize the database with `python api_main.py --init-db`

### Debug Mode

Use verbose mode for detailed output:
```bash
python cli.py --verbose monitor check
```

## 📋 Future Commands

Planned commands for future releases:

- `cli.py database stats` - Database statistics
- `cli.py database clean` - Clean old data
- `cli.py export csv` - Export data to CSV
- `cli.py import urls` - Import URLs from file
- `cli.py monitor schedule` - Schedule monitoring tasks

## 🤝 Contributing

When adding new CLI commands:

1. Follow hexagonal architecture principles
2. Use dependency injection from `CLIServices`
3. Add comprehensive help text and examples
4. Include dry-run modes where applicable
5. Update this README with new commands 