#!/bin/bash
# 
# Comprehensive test runner for FAB project
# Runs all tests and generates reports
#

set -e

echo "🧪 FAB Project Test Runner"
echo "=========================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${2}${1}${NC}"
}

# Change to project directory
cd "$(dirname "$0")"

print_status "📁 Project directory: $(pwd)" $BLUE

# Check Python version
print_status "🐍 Python version:" $BLUE
python3 --version

# Run syntax check on all Python files
print_status "1. 🔍 Running syntax validation..." $YELLOW
echo "Checking all Python files for syntax errors..."
find . -name "*.py" -not -path "./venv/*" -not -path "./.git/*" -exec python3 -m py_compile {} \; 2>&1 | tee syntax_errors.log

if [ $? -eq 0 ]; then
    print_status "✅ Syntax check PASSED" $GREEN
else
    print_status "❌ Syntax check FAILED - see syntax_errors.log" $RED
fi

# Run import tests
print_status "2. 📦 Testing imports..." $YELLOW
python3 -c "
try:
    import sys
    sys.path.append('.')
    
    modules = [
        'fab.config',
        'fab.db.database', 
        'fab.db.models',
        'fab.db.manager',
        'fab.utils.i18n',
        'fab.utils.rabbitmq'
    ]
    
    for module in modules:
        try:
            __import__(module)
            print(f'✅ {module}')
        except Exception as e:
            print(f'❌ {module}: {e}')
            
except Exception as e:
    print(f'Import test failed: {e}')
"

# Run comprehensive test suite
print_status "3. 🧪 Running comprehensive test suite..." $YELLOW
python3 test_suite.py 2>&1 | tee test_results.log

# Check for common issues
print_status "4. 🔧 Checking for common issues..." $YELLOW

echo "Checking for hardcoded values..."
grep -r "localhost" . --include="*.py" --exclude-dir=venv --exclude-dir=.git | head -5
grep -r "127.0.0.1" . --include="*.py" --exclude-dir=venv --exclude-dir=.git | head -5

echo "Checking for TODO/FIXME comments..."
grep -r -i "TODO\|FIXME\|XXX\|HACK" . --include="*.py" --exclude-dir=venv --exclude-dir=.git | head -10

echo "Checking for print() statements (should use logger)..."
grep -r "print(" . --include="*.py" --exclude-dir=venv --exclude-dir=.git --exclude="test_suite.py" --exclude="run_tests.sh" | head -5

# Check configuration files
print_status "5. 📋 Validating configuration files..." $YELLOW
echo "Checking JSON files..."
find . -name "*.json" -not -path "./venv/*" -not -path "./.git/*" -exec python3 -m json.tool {} \; > /dev/null 2>&1

if [ $? -eq 0 ]; then
    print_status "✅ JSON files are valid" $GREEN
else
    print_status "❌ JSON validation failed" $RED
fi

# Check Docker setup
print_status "6. 🐳 Checking Docker setup..." $YELLOW
if [ -f "Dockerfile" ]; then
    echo "✅ Dockerfile exists"
    echo "Checking Dockerfile syntax..."
    docker build --dry-run . > /dev/null 2>&1 && echo "✅ Dockerfile syntax OK" || echo "❌ Dockerfile has issues"
else
    echo "❌ Dockerfile not found"
fi

# Check Makefile
print_status "7. 🔨 Checking Makefile..." $YELLOW
if [ -f "Makefile" ]; then
    echo "✅ Makefile exists"
    make help > /dev/null 2>&1 && echo "✅ Makefile syntax OK" || echo "⚠️ Make help not available"
else
    echo "❌ Makefile not found"
fi

# Security check
print_status "8. 🔒 Basic security checks..." $YELLOW
echo "Checking for potential security issues..."

# Check for hardcoded secrets (basic)
grep -r -i "password\s*=\s*['\"]" . --include="*.py" --exclude-dir=venv --exclude-dir=.git | head -3
grep -r -i "token\s*=\s*['\"]" . --include="*.py" --exclude-dir=venv --exclude-dir=.git | head -3

# Summary
print_status "📊 Test Summary:" $BLUE
echo "==================="
echo "- Syntax validation: Check syntax_errors.log"
echo "- Import tests: See output above" 
echo "- Comprehensive tests: Check test_results.log"
echo "- Configuration: JSON files validated"
echo "- Docker: Basic Dockerfile check"
echo "- Security: Basic credential scan"

print_status "🏁 Test run completed!" $GREEN
print_status "📄 Check test_results.log and syntax_errors.log for details" $BLUE

# Return appropriate exit code based on Success Rate ≥ 99.5%
SUCCESS_RATE=$(grep -E "Success Rate: [0-9]+\.[0-9]+%" test_results.log | tail -n1 | awk '{print $4}' | tr -d '%')

if [ -z "$SUCCESS_RATE" ]; then
  # Fallback: if explicit ALL TESTS PASSED present
  if grep -q "ALL TESTS PASSED" test_results.log 2>/dev/null; then
    exit 0
  else
    exit 1
  fi
fi

awk -v rate="$SUCCESS_RATE" 'BEGIN { if (rate+0 >= 99.5) exit 0; else exit 1 }'
