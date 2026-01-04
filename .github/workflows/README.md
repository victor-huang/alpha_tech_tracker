# GitHub Actions Workflows

This directory contains GitHub Actions workflows for continuous integration and testing.

## Workflows

### 1. `test.yml` - Main Test Suite

**Triggers:**
- Push to `main`, `develop`, or `refactor_code_cleanup_mordenization` branches
- Pull requests to `main` or `develop`
- Manual trigger via Actions tab

**What it does:**
- Runs the full test suite (209 tests)
- Tests across Python 3.8, 3.9, and 3.10
- Auto-skips credential tests (14 tests) and slow tests (10 tests)
- Generates code coverage reports
- Uploads results as artifacts

**Runtime:** ~1-2 minutes per Python version (tests run in ~4 seconds + setup time)

**Status Badge:**
Add this to your README.md to show test status:
```markdown
![Tests](https://github.com/YOUR_USERNAME/alpha_tech_tracker/actions/workflows/test.yml/badge.svg)
```

### 2. `test-credentials.yml` - Integration Tests

**Triggers:**
- Manual trigger only (requires API credentials)

**What it does:**
- Runs integration tests that require API credentials
- Choose which tests to run: all, alpaca, or etrade
- Requires GitHub Secrets to be configured (see below)

**Usage:**
1. Go to Actions tab in GitHub
2. Select "Integration Tests (with Credentials)"
3. Click "Run workflow"
4. Choose test type (all, alpaca, or etrade)

## Setting Up API Credentials

To run integration tests, add these secrets in your GitHub repository:

**Settings → Secrets and variables → Actions → New repository secret**

### Alpaca Credentials
- `ALPACA_API_KEY` - Your Alpaca API key
- `ALPACA_SECRET_KEY` - Your Alpaca secret key

### ETrade Credentials
- `ETRADE_API_KEY_ID` - Your ETrade API key ID
- `ETRADE_API_SECRET_KEY` - Your ETrade API secret key

## Test Results

### Current Test Suite Status
- ✅ **209 tests passed**
- ⏭️ **10 tests skipped** (strategy tuning, data persistence, streaming)
- 🚫 **14 tests deselected** (credential tests - auto-skipped in CI)
- ⚡ **~4 second runtime** (core tests only)

### Coverage
Coverage reports are automatically generated and can be:
- Viewed in Actions artifacts
- Uploaded to Codecov (if configured)
- Downloaded from workflow runs

## Local Testing

To run tests locally with the same configuration as CI:

```bash
# Core tests (default - no credentials needed)
PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" pytest tests/ -v

# With coverage
PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" pytest tests/ -v --cov=alpha_tech_tracker

# Integration tests (requires real credentials)
PYTHONPATH=. \
  TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" \
  ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..." \
  pytest tests/ -m "alpaca" -v
```

## Troubleshooting

### Tests Failing in CI but Pass Locally
1. Check Python version - CI tests on 3.8, 3.9, 3.10
2. Ensure requirements.txt is up to date
3. Check for environment-specific dependencies

### Coverage Upload Failing
This is usually non-critical. Coverage upload to Codecov may fail if:
- Codecov is not configured
- Token is missing
The workflow is configured to continue on coverage upload errors.

### Integration Tests Not Running
- Integration tests only run when manually triggered
- Ensure API credentials are configured in GitHub Secrets
- Check that secret names match exactly

## Optimization

### Caching
The workflows use pip caching to speed up dependency installation:
- First run: ~30-60 seconds to install dependencies
- Subsequent runs: ~5-10 seconds (cached)

### Parallel Execution
Tests run in parallel across multiple Python versions using matrix strategy.

### Fast Feedback
- Core tests run first (fastest feedback)
- Integration tests are optional (run manually when needed)

## Maintenance

### Updating Python Versions
Edit the matrix in `test.yml`:
```yaml
strategy:
  matrix:
    python-version: ['3.8', '3.9', '3.10', '3.11']  # Add/remove versions
```

### Adding New Secrets
1. Add secret to GitHub repository settings
2. Update workflow to use the secret
3. Document in this README

### Modifying Test Execution
Edit the pytest command in the workflow:
```yaml
pytest tests/ -v --tb=short --cov=alpha_tech_tracker
```

Common modifications:
- Add `-x` to stop on first failure
- Add `-n auto` for parallel test execution (requires pytest-xdist)
- Add `--maxfail=3` to stop after 3 failures
- Change `--tb=short` to `--tb=long` for more detailed error output
