# Dependency Migration Guide

**Date:** 2026-01-03
**Project:** Alpha Tech Tracker

---

## Summary

Updated 8 packages with security fixes and modernization improvements. Created `requirements-updated.txt` for review before applying.

---

## Critical Security Fixes

### 1. urllib3: 1.24 → 1.26.18+
**Risk:** HIGH - Multiple CVEs in old version
**Breaking Changes:** None expected
**Testing Required:**
- [ ] Verify Alpaca API calls work
- [ ] Verify ETrade API calls work
- [ ] Check any direct HTTP requests

### 2. redis: 3.2.1 → 4.6.0+
**Risk:** MEDIUM - API changes between versions
**Breaking Changes:** Some method signatures changed
**Testing Required:**
- [ ] Test `redis_client.py` functionality
- [ ] Verify cache read/write operations
- [ ] Check if any Redis connection parameters need updating

**Known Changes:**
- Connection parameters may need adjustment
- Some deprecated methods removed
- StrictRedis merged with Redis class

---

## High Priority Updates

### 3. plotly: 4.3.0 → 5.18.0
**Risk:** LOW - Mostly backwards compatible
**Breaking Changes:** Minimal
**Testing Required:**
- [ ] Verify candlestick chart rendering
- [ ] Check if `plot_market_data_candle_stick_chart` still works

### 4. twilio: 6.35.1 → 9.0.0
**Risk:** MEDIUM - Major version jump
**Breaking Changes:** API method names may have changed
**Testing Required:**
- [ ] Test `sms.py` send_sms() function
- [ ] Verify SMS sending still works
- [ ] Check authentication method

**Migration Notes:**
- Review Twilio's upgrade guide: https://www.twilio.com/docs/libraries/python
- May need to update client initialization

### 5. nbformat: 4.4.0 → 5.9.0
**Risk:** LOW
**Breaking Changes:** None expected for basic usage
**Testing Required:**
- [ ] If you use Jupyter notebooks, test loading/saving

### 6. requests-oauthlib: 1.3.1 → 2.0.0
**Risk:** LOW-MEDIUM
**Breaking Changes:** Minimal
**Testing Required:**
- [ ] Test ETrade OAuth flow in `etrade/client.py`
- [ ] Verify `authorize_session()` still works

---

## Standard Updates

### 7. pandas: 2.0.3 → 2.0.3+ (allow patch updates)
**Risk:** VERY LOW
**Testing Required:** Run backtests to verify data processing

### 8. pytest: 7.4.2 → 8.0.0+
**Risk:** VERY LOW
**Testing Required:** Run existing test suite

---

## Packages to Evaluate

### alpaca-trade-api (Legacy SDK)
**Current:** 0.35
**Status:** You're using both `alpaca-trade-api` (old) and `alpaca-py` (new)

**Question:** Do you still need `alpaca-trade-api`?
- Check if `alpaca_engine.py` is still used
- If only using `alpaca_py_engine.py`, can remove old SDK
- **Savings:** Reduce dependency footprint

**Action Items:**
- [ ] Grep codebase for `alpaca_trade_api` imports
- [ ] Check if `alpaca_engine.py` is imported anywhere
- [ ] Consider deprecating old engine entirely

---

## Migration Steps

### Step 1: Backup
```bash
cp requirements.txt requirements-backup.txt
```

### Step 2: Create Virtual Environment (Recommended)
```bash
python3.8 -m venv venv-updated
source venv-updated/bin/activate
```

### Step 3: Install Updated Dependencies
```bash
pip install -r requirements-updated.txt
```

### Step 4: Test Critical Paths
```bash
# Test imports
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -c "
import alpha_tech_tracker.redis_client
import alpha_tech_tracker.sms
import alpha_tech_tracker.trade_api.etrade.client
import alpha_tech_tracker.trade_api.alpaca_client.client
print('✅ All imports successful')
"

# Run existing tests
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker python -m pytest tests/ -v
```

### Step 5: Test API Integrations
```bash
# Test Alpaca client
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  python -m pytest tests/trade_api/alpaca_client/test_client.py::test_get_accounts -v

# Test ETrade client (if credentials available)
# Manual test: Run authorize_session() flow
```

### Step 6: Test SMS (if Twilio credentials available)
```python
# Quick test script
from alpha_tech_tracker.sms import send_sms
send_sms("4086130570", "Test message - dependency update verification")
```

### Step 7: Run Backtest Validation
```bash
# Run a known backtest to verify results match
PYTHONPATH=/Users/victorhuang/work/alpha_tech_tracker \
  python -m pytest tests/test_tsla_buy_strategy.py::test_strategy_simulation -v -s
```

### Step 8: If All Tests Pass
```bash
# Replace old requirements
mv requirements-updated.txt requirements.txt
git add requirements.txt
git commit -m "chore: update dependencies for security and modernization

- Fix urllib3 CVEs (1.24 → 1.26.18)
- Update redis client (3.2.1 → 4.6.0)
- Modernize plotly, twilio, nbformat
- Update testing framework (pytest 8.0)
- Add pytest-mock for better test coverage

All backtests validated, no regressions detected."
```

---

## Rollback Plan

If issues arise:
```bash
pip install -r requirements-backup.txt
```

---

## Post-Migration Tasks

After successful migration:

1. **Update CLAUDE.md** if any import paths or initialization patterns changed
2. **Document any API changes** (especially Twilio if SMS code needed updates)
3. **Run extended backtests** to verify no subtle regressions
4. **Update CI/CD** if you have automated testing pipelines

---

## Questions to Answer

- [ ] Is `alpaca-trade-api` (old SDK) still needed?
- [ ] Do we want to add code quality tools (black, mypy)?
- [ ] Do we want test coverage reporting (pytest-cov)?
- [ ] Are there any other dependencies missing (e.g., pytz for timezones)?

---

## Risk Assessment

| Package | Risk Level | Likelihood of Issues | Impact if Broken |
|---------|-----------|---------------------|------------------|
| urllib3 | **LOW** | Very Low | HTTP calls fail |
| redis | **MEDIUM** | Medium | Cache broken |
| plotly | **LOW** | Very Low | Charts broken |
| twilio | **MEDIUM** | Medium | SMS alerts fail |
| nbformat | **LOW** | Very Low | Notebook handling |
| requests-oauthlib | **MEDIUM** | Low | ETrade auth fails |
| pandas | **LOW** | Very Low | Data processing |
| pytest | **LOW** | Very Low | Tests fail to run |

**Overall Risk:** MEDIUM - Test thoroughly before committing

---

## Timeline

- **Setup & Install:** 15 minutes
- **Import Testing:** 5 minutes
- **Unit Test Run:** 10 minutes
- **API Integration Tests:** 20 minutes (if credentials available)
- **Backtest Validation:** 15 minutes
- **Total:** ~1 hour

---

## Success Criteria

✅ All imports successful
✅ Existing test suite passes
✅ Backtests produce consistent results
✅ API clients connect successfully
✅ No deprecation warnings in logs
