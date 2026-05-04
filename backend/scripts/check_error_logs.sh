#!/bin/bash
# Script to check error logs for a specific product, endpoint, or error ID

ERROR_ID="${1:-}"
PRODUCT_ID="${2:-}"
LOG_FILE="${3:-errors.log}"

echo "=========================================="
echo "Error Log Checker"
echo "=========================================="

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file not found: $LOG_FILE"
    exit 1
fi

# Check if first argument is an error ID (8 chars, alphanumeric)
if [[ "$1" =~ ^[a-f0-9]{8}$ ]]; then
    ERROR_ID="$1"
    echo "Error ID: $ERROR_ID"
    echo "Log File: $LOG_FILE"
    echo ""
    echo "📋 Error details for ID $ERROR_ID:"
    echo "----------------------------------------"
    grep -A 50 "\[$ERROR_ID\]" "$LOG_FILE"
    exit 0
fi

# Otherwise treat as product ID or endpoint
PRODUCT_ID="${1:-}"
if [ -z "$PRODUCT_ID" ]; then
    echo "Usage:"
    echo "  $0 <error_id>              # Search by error ID (8 chars)"
    echo "  $0 <product_id>             # Search by product ID"
    echo "  $0 <product_id> <log_file>  # Search in specific log file"
    echo ""
    echo "📋 Recent errors from errors.log:"
    echo "----------------------------------------"
    tail -20 errors.log 2>/dev/null || echo "No errors.log found"
    echo ""
    echo "📋 Recent errors from api.log:"
    echo "----------------------------------------"
    tail -20 api.log | grep -E "ERROR|Exception|Error ID" | tail -10
    exit 0
fi

echo "Product/Endpoint: $PRODUCT_ID"
echo "Log File: $LOG_FILE"
echo ""

echo "📋 Recent errors for $PRODUCT_ID:"
echo "----------------------------------------"
grep -A 30 "$PRODUCT_ID" "$LOG_FILE" | grep -A 30 -E "(ERROR|Exception|Traceback|500|Error ID)" | tail -50

echo ""
echo "📋 All recent ERROR entries:"
echo "----------------------------------------"
grep -E "ERROR|Exception" "$LOG_FILE" | tail -20

echo ""
echo "📋 Recent 500 errors:"
echo "----------------------------------------"
grep "500\|Internal Server Error" "$LOG_FILE" | tail -10

