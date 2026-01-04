# Alpha Tech Tracker Modernization Plan

**Project:** alpha_tech_tracker
**Created:** 2026-01-03
**Owner:** Victor
**Status:** Ready for Execution

---

## Overview

Refactor ad-hoc trading system for maintainability, update dependencies, add critical-path test coverage, and simplify Strategy configuration complexity.

**Key Drivers:**
- System was built ad-hoc; time to make it maintainable
- Increase test coverage for long-term sustainability
- Clean up technical debt
- Improve Strategy configuration clarity

**Constraints:**
- Keep codebase simple and readable
- Avoid over-engineering
- No production system risk (not live yet)

---

## Phase 1: Foundation & Assessment (1-2 days)

### 1.1 Dependency Audit
- Review `requirements.txt` for outdated packages
- Identify security vulnerabilities or deprecated APIs
- Prioritize updates: critical (security/breaks) → nice-to-have
- Create updated `requirements.txt` with version ranges

### 1.2 Critical Path Mapping
- Document the core trading flow:
  ```
  Market Data → Technical Analysis → Signal Generation →
  Order Placement → Position Management → Portfolio Tracking
  ```
- Identify which modules are on critical path (money-touching code)

---

## Phase 2: Strategy Refactoring (2-3 days)

### 2.1 Simplify Strategy Configuration
- Extract all configuration parameters from `SimpleStrategy.__init__` into a dataclass/config object
- Group related configs:
  - `BuyTriggerConfig` - Entry conditions
  - `SellTriggerConfig` - Exit conditions
  - `OptionConfig` - Option selection parameters
  - `RiskConfig` - Stop loss and position sizing
- Add docstrings explaining what each parameter does and typical ranges
- Consider creating preset configs for common strategies (e.g., `conservative_config`, `aggressive_config`)

### 2.2 Strategy Documentation
- Add class-level docstring explaining the strategy logic flow
- Document the trigger conditions in plain English
- Create a simple diagram showing decision flow (buy/sell conditions)

---

## Phase 3: Test Coverage - Critical Paths Only (3-4 days)

### 3.1 Order Engine Tests
- Order placement validation
- Order status tracking
- Order cancellation

### 3.2 Portfolio Management Tests
- Position opening/closing
- P&L calculation accuracy
- Position tracking across multiple trades

### 3.3 API Client Integration Tests
- Mock-based tests for ETrade/Alpaca clients
- Quote retrieval
- Order submission response handling
- Error handling (network failures, API errors)

### 3.4 Signal Generation Tests
- Wave analysis logic
- Buy/sell trigger conditions
- Edge cases (insufficient data, market gaps)

---

## Phase 4: Technical Debt Cleanup (1-2 days)

### 4.1 Code Cleanup
- Run `autoflake` on all files to remove unused imports
- Consolidate duplicate logic (e.g., `alpaca_engine` vs `alpaca_py_engine`)
- Remove commented-out code
- Consistent naming conventions

### 4.2 Documentation
- Update CLAUDE.md if architecture changes
- Add inline comments only for complex logic
- Ensure test classes clearly group related tests

---

## Phase 5: Validation (1 day)

### 5.1 Backtest Validation
- Run existing backtest scenarios to ensure no regressions
- Compare P&L results before/after refactoring

### 5.2 Dependency Validation
- Test with updated libraries
- Verify API clients still work with new packages

---

## Execution Checklist

### Phase 1: Foundation
- [ ] Audit and update requirements.txt
- [ ] Map critical paths in trading flow
- [ ] Document money-touching modules

### Phase 2: Strategy Refactoring ✅ **COMPLETE**
- [x] Create Strategy config dataclasses (BuyTriggerConfig, SellTriggerConfig, OptionConfig, RiskConfig) ✅ **53 tests passing**
- [x] Refactor SimpleStrategy to use config objects ✅ **22 tests passing, backward compatible**
- [x] Add comprehensive docstrings to Strategy classes ✅ **230+ lines of documentation**
- [x] Document trigger conditions in plain English ✅ **Entry/exit logic fully explained**

### Phase 3: Test Coverage
- [ ] Write tests: OrderEngine critical paths
- [ ] Write tests: Portfolio P&L calculations
- [ ] Write tests: API client mocking (ETrade & Alpaca)
- [ ] Write tests: Signal generation logic
- [ ] Write tests: Wave analysis edge cases

### Phase 4: Technical Debt
- [ ] Run autoflake on all Python files
- [ ] Remove unused imports
- [ ] Consolidate alpaca engine implementations
- [ ] Remove commented-out code
- [ ] Standardize naming conventions
- [ ] Add inline comments for complex logic only

### Phase 5: Validation
- [ ] Run full backtest suite for validation
- [ ] Compare P&L results (before/after)
- [ ] Test with updated dependencies
- [ ] Verify API clients functionality
- [ ] Update CLAUDE.md with any architecture changes

---

## Success Criteria

✅ All critical paths have test coverage
✅ Strategy configuration is self-documenting
✅ Dependencies updated without breaking changes
✅ Backtests produce same results (within margin)
✅ Code is cleaner and more maintainable

---

## Notes

- **Testing Philosophy**: Focus on critical paths only (order execution, P&L, position management)
- **Test Location**: Unit tests in `tests/unit/`, integration tests can use real services
- **Pre-commit**: Always run `autoflake -i --remove-all-unused-imports <files>` before commits
- **PYTHONPATH**: All tests require `PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker`

---

## Risk Assessment

**Low Risk Areas** (can refactor more aggressively):
- Documentation improvements
- Configuration restructuring
- Test additions

**Medium Risk Areas** (test thoroughly):
- Dependency updates
- Strategy logic refactoring
- API client changes

**High Risk Areas** (validate extensively):
- Order engine modifications
- Portfolio P&L calculations
- Money-touching code paths

---

## Estimated Timeline

- **Phase 1**: 1-2 days
- **Phase 2**: 2-3 days
- **Phase 3**: 3-4 days
- **Phase 4**: 1-2 days
- **Phase 5**: 1 day

**Total**: 8-12 days (1.5-2.5 weeks)

---

## Next Steps

1. Begin Phase 1: Dependency Audit
2. Create feature branch: `modernization-refactor`
3. Work through phases sequentially
4. Commit frequently with descriptive messages
5. Run tests after each significant change
