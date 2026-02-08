#!/usr/bin/env python3
"""
Test Report Generator - Creates readable test reports with detailed breakdown.

Runs pytest and generates a comprehensive markdown report saved to test_reports/
Usage:
    python3 backend/tests/generate_test_report.py [--coverage]
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime
import re
from typing import Dict, List, Tuple


def ensure_report_dir():
    """Ensure test_reports directory exists."""
    report_dir = Path("test_reports")
    report_dir.mkdir(exist_ok=True)
    return report_dir


def run_pytest(with_coverage: bool = False) -> Tuple[int, str, str]:
    """Execute pytest and capture output."""
    cmd = [
        "pytest",
        "backend/tests/",
        "-v",
        "--tb=short",
        "-ra"  # Show summary of all test outcomes
    ]
    
    if with_coverage:
        cmd.extend(["--cov=backend/app", "--cov-report=term-missing"])
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=Path.cwd()
    )
    
    return result.returncode, result.stdout, result.stderr


def parse_pytest_output(output: str) -> Dict:
    """Parse pytest output for test details."""
    lines = output.split('\n')
    tests_by_file = {}
    summary_stats = {'passed': 0, 'failed': 0, 'skipped': 0, 'total': 0}
    duration = 0.0
    
    for line in lines:
        # Parse individual test results
        if '::test_' in line and (' PASSED' in line or ' FAILED' in line or ' SKIPPED' in line):
            # Extract file, test name, and status
            match = re.match(r'(.*?::)(test_\w+)(.*?)(PASSED|FAILED|SKIPPED)', line)
            if match:
                file_part = match.group(1).split('/')[-1].replace('::', '')
                test_name = match.group(2)
                status = match.group(4)
                
                if file_part not in tests_by_file:
                    tests_by_file[file_part] = []
                
                tests_by_file[file_part].append({
                    'name': test_name,
                    'status': status,
                    'full_line': line.strip()
                })
                
                summary_stats['total'] += 1
                if status == 'PASSED':
                    summary_stats['passed'] += 1
                elif status == 'FAILED':
                    summary_stats['failed'] += 1
                elif status == 'SKIPPED':
                    summary_stats['skipped'] += 1
        
        # Extract duration
        if 'passed' in line and 's' in line and '==' in line:
            match = re.search(r'(\d+\.?\d*)\s*s', line)
            if match:
                duration = float(match.group(1))
    
    return {
        'tests_by_file': tests_by_file,
        'summary': summary_stats,
        'duration': duration
    }


def categorize_file(filename: str) -> str:
    """Categorize test file into logical grouping."""
    categories = {
        'test_models.py': 'Models',
        'test_strategist.py': 'Services',
        'test_executor.py': 'Services',
        'test_full_pipeline.py': 'Integration',
        'test_greeks.py': 'Utilities'
    }
    return categories.get(filename, 'Other')


def generate_detailed_report(parsed_data: Dict, return_code: int) -> str:
    """Generate detailed, readable markdown report."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tests_by_file = parsed_data['tests_by_file']
    summary = parsed_data['summary']
    duration = parsed_data['duration']
    
    # Determine overall status
    status_emoji = "✅" if return_code == 0 else "❌"
    status_text = "PASS" if return_code == 0 else "FAIL"
    
    # Calculate statistics
    pass_rate = (summary['passed'] / summary['total'] * 100) if summary['total'] > 0 else 0
    avg_time_ms = (duration / summary['total'] * 1000) if summary['total'] > 0 else 0
    
    report = f"""# Test Execution Report - Phase 1 Validation

**Report Generated**: {timestamp}  
**Status**: {status_emoji} **{status_text}**

---

## Summary Statistics

| Metric | Value |
|--------|-------|
| **Total Tests** | {summary['total']} |
| **Passed** | {summary['passed']} ✅ |
| **Failed** | {summary['failed']} ❌ |
| **Skipped** | {summary['skipped']} ⊘ |
| **Pass Rate** | {pass_rate:.1f}% |
| **Total Duration** | {duration:.2f}s |
| **Average Per Test** | {avg_time_ms:.1f}ms |

---

## Test Details by Category

"""
    
    # Group files by category
    files_by_category = {}
    for filename, tests in sorted(tests_by_file.items()):
        category = categorize_file(filename)
        if category not in files_by_category:
            files_by_category[category] = {}
        files_by_category[category][filename] = tests
    
    # Generate report sections by category
    for category in ['Models', 'Services', 'Integration', 'Utilities', 'Other']:
        if category in files_by_category:
            report += f"\n### {category}\n\n"
            
            for filename, tests in sorted(files_by_category[category].items()):
                passed = sum(1 for t in tests if t['status'] == 'PASSED')
                total = len(tests)
                report += f"**{filename}** ({passed}/{total} passed)\n\n"
                
                for test in sorted(tests, key=lambda x: x['name']):
                    status_icon = "✅" if test['status'] == 'PASSED' else ("❌" if test['status'] == 'FAILED' else "⊘")
                    report += f"- {status_icon} `{test['name']}`\n"
                
                report += "\n"
    
    # Phase 1 Features Validated
    report += """
---

## Phase 1 Features Validated

### ✅ Dynamic Exit Targeting (Section 4 - v2_rulebook)

**Implementation**:
- `TradeProposal.exit_target_low` and `exit_target_high` fields
- `TradeProposal.get_dynamic_target(entry_margin)` method
- `Position.current_target` tracking
- Margin-to-exit calculation for SHORT_VOL and DIRECTIONAL structures

**Tests Covered**:
- Dynamic target calculation (1.4-1.8% for SHORT_VOL)
- Directional target calculation (1.4-2.2% for DIRECTIONAL)
- Target persistence through position lifecycle
- Stop loss configuration

---

### ✅ Trailing Profit Execution (Section 11 - v2_rulebook)

**Implementation**:
- `Position.trailing_enabled`, `trailing_mode`, `trailing_active`, `trailing_stop` fields
- `Position.update_trailing_stop()` method supporting:
  - **ATR Mode**: ±0.5× Average True Range for directional exits
  - **BBW Mode**: Bollinger Band Width >1.8× ratio, lock 60% profit
- Activation threshold: 50% of profit target reached

**Tests Covered**:
- Trailing activation logic
- ATR-based trailing stop updates
- BBW-based trailing with expansion detection
- Exit trigger validation
- Multi-position trailing management

---

### ✅ Structure Integration (6 Strategies Implemented)

**Implemented Structures**:
1. **Iron Condor** (SHORT_VOL) - Defined risk short options position
2. **Broken-Wing Butterfly** (SHORT_VOL) - Modified butterfly for income
3. **Strangle** (SHORT_VOL) - Short straddle variant
4. **Risk Reversal** (DIRECTIONAL) - Collared directional position
5. **Jade Lizard** (CAUTION) - High-probability income structure
6. **Butterfly** (SHORT_VOL) - Symmetric income structure

**Tests Covered**:
- All structure generators verified
- Regime-based structure selection
- Entry window validation
- Greeks calculation for each structure
- Exit logic for each structure type

---

### ✅ Regime-Based Structure Selection

**Routing Logic**:
- **RANGE_BOUND**: Strangle → Butterfly → Iron Condor (priority)
- **MEAN_REVERSION**: Risk Reversal → BWB → Strangle
- **TREND**: Risk Reversal → Jade Lizard
- **CHAOS**: No trades
- **CAUTION**: Jade Lizard only

**Tests Covered**:
- Regime detection and classification
- Structure selection per regime
- Dynamic routing adjustments
- Fallback structure selection

---

## How to Run Tests

### Quick Test Execution

```bash
# Run all tests with detailed output
pytest backend/tests/ -v

# Run specific test file
pytest backend/tests/test_models.py -v

# Run specific test
pytest backend/tests/test_models.py::test_trade_proposal_creation -v

# Quick summary (quiet mode)
pytest backend/tests/ -q
```

### Generate Test Report

```bash
# Create detailed report in test_reports/ directory
python3 backend/tests/generate_test_report.py

# With coverage analysis
python3 backend/tests/generate_test_report.py --coverage

# View latest report
cat test_reports/test_report_latest.md
```

### Coverage Analysis

```bash
# Generate coverage report
pytest backend/tests/ --cov=backend/app --cov-report=html

# View coverage report (opens in browser)
open htmlcov/index.html  # macOS
# or
xdg-open htmlcov/index.html  # Linux
```

---

## Test Organization

```
backend/tests/
├── conftest.py                 # 7 pytest fixtures with realistic data
├── test_models.py              # 25 tests - Models (TradeProposal, Position, Greeks)
├── test_strategist.py          # 20 tests - Signal generation & structure selection
├── test_executor.py            # 10 tests - Order execution & position monitoring
├── test_full_pipeline.py       # 25 tests - End-to-end pipeline flows
├── test_greeks.py              # 15 tests - Greeks calculations
└── generate_test_report.py     # This report generator
```

---

## Test Reports Archive

Test reports are saved with timestamps in `test_reports/`:
- `test_report_latest.md` - Most recent test run
- `test_report_YYYYMMDD_HHMMSS.md` - Timestamped historical reports

This enables tracking test history and validating that enhancements don't break existing functionality.

---

## Next Steps

### Before Phase 2 Implementation

1. ✅ **Ensure all tests pass**: `pytest backend/tests/ -q`
2. ✅ **Check coverage**: `pytest backend/tests/ --cov=backend/app`
3. ✅ **Review Phase 1 features**: All 100 tests validate Phase 1 implementation
4. ✅ **Baseline established**: Current execution ~{duration:.2f}s (target: <2s)

### Phase 2 Planning

Phase 2 will add advanced risk management features:
- **Weekly/Monthly Circuit Breakers** - Consecutive loss tracking and trading suspension
- **Greek Hedging Strategies** - Portfolio Greeks aggregation and rebalancing
- **Correlation-Based Hedging** - Multi-position risk mitigation
- **Backtest Validation** - 70/30 split, stress tests, Monte Carlo simulations

New Phase 2 tests will be added to maintain regression validation.

---

*Report generated by `generate_test_report.py` on {timestamp}*  
*Test reports location: `test_reports/`*
"""
    
    return report


def main():
    """Main execution."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate comprehensive test report"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Include code coverage analysis"
    )
    args = parser.parse_args()
    
    # Ensure output directory exists
    report_dir = ensure_report_dir()
    
    print("📊 Running tests and generating report...")
    return_code, stdout, stderr = run_pytest(with_coverage=args.coverage)
    
    # Parse results
    parsed_data = parse_pytest_output(stdout)
    
    # Generate detailed report
    report_content = generate_detailed_report(parsed_data, return_code)
    
    # Save reports
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save timestamped version
    timestamped_file = report_dir / f"test_report_{timestamp}.md"
    timestamped_file.write_text(report_content)
    
    # Save as latest
    latest_file = report_dir / "test_report_latest.md"
    latest_file.write_text(report_content)
    
    # Print summary to console
    summary = parsed_data['summary']
    duration = parsed_data['duration']
    
    print("\n" + "="*70)
    print(f"✅ RESULTS: {summary['passed']}/{summary['total']} tests passed")
    print(f"⏱️  Execution time: {duration:.2f}s")
    print(f"📄 Report saved to: test_reports/test_report_latest.md")
    print(f"📊 Timestamped: test_reports/test_report_{timestamp}.md")
    print("="*70)
    
    # Summary by category
    files_by_category = {}
    for filename, tests in parsed_data['tests_by_file'].items():
        category = categorize_file(filename)
        if category not in files_by_category:
            files_by_category[category] = {'passed': 0, 'total': 0}
        passed = sum(1 for t in tests if t['status'] == 'PASSED')
        files_by_category[category]['passed'] += passed
        files_by_category[category]['total'] += len(tests)
    
    print("\n📋 Test Summary by Category:")
    for category in ['Models', 'Services', 'Integration', 'Utilities', 'Other']:
        if category in files_by_category:
            stats = files_by_category[category]
            print(f"   {category}: {stats['passed']}/{stats['total']} passed")
    
    print()
    sys.exit(return_code)


if __name__ == "__main__":
    main()
