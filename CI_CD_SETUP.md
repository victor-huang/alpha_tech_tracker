# CI/CD Setup Guide

This document explains how to set up and use the GitHub Actions CI/CD pipelines for Alpha Tech Tracker.

## Quick Start

The CI/CD is already configured! Just push your code to GitHub:

```bash
git add .github/
git commit -m "Add GitHub Actions CI/CD workflows"
git push origin your-branch
```

## What Happens Automatically

### On Every Push/PR
When you push to `main`, `develop`, or `refactor_code_cleanup_mordenization` branches (or create a PR):

1. **Automated Testing** runs across Python 3.8, 3.9, 3.10
2. **209 core tests** execute in ~4 seconds
3. **Coverage reports** are generated
4. **Results uploaded** as artifacts

### Tests That Auto-Skip (No Credentials Needed)
- ✅ 209 core tests run
- ⏭️ 10 tests skipped (strategy tuning, data persistence)
- 🚫 14 tests auto-skipped (credential tests - perfect for CI!)

## Viewing Results

### In GitHub UI
1. Go to your repository on GitHub
2. Click the **Actions** tab
3. See workflow runs and their status
4. Click on any run to see detailed logs

### Adding Status Badge to README
Add this to your `README.md`:

```markdown
![Tests](https://github.com/YOUR_USERNAME/alpha_tech_tracker/actions/workflows/test.yml/badge.svg)
```

Replace `YOUR_USERNAME` with your GitHub username.

## Running Integration Tests (Optional)

Integration tests require API credentials and run manually:

### 1. Add Secrets to GitHub

Go to: **Repository Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

**For Alpaca tests:**
- Name: `ALPACA_API_KEY` → Value: Your Alpaca API key
- Name: `ALPACA_SECRET_KEY` → Value: Your Alpaca secret key

**For ETrade tests:**
- Name: `ETRADE_API_KEY_ID` → Value: Your ETrade API key ID
- Name: `ETRADE_API_SECRET_KEY` → Value: Your ETrade API secret key

### 2. Trigger Manual Run

1. Go to **Actions** tab
2. Select **"Integration Tests (with Credentials)"** workflow
3. Click **"Run workflow"** button
4. Choose test type: `all`, `alpaca`, or `etrade`
5. Click green **"Run workflow"** button

## Workflow Files

### `.github/workflows/test.yml`
Main test suite - runs automatically on push/PR

**Features:**
- Multi-version Python testing (3.8, 3.9, 3.10)
- Code coverage reporting
- Artifact uploads
- Fast feedback (~1-2 minutes including setup)

### `.github/workflows/test-credentials.yml`
Integration tests - manual trigger only

**Features:**
- Runs tests requiring API credentials
- Selective test execution (choose which APIs to test)
- Safe secret handling

## Local Testing (Same as CI)

Test locally with the exact same configuration as CI:

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run core tests (same as CI)
PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" \
  pytest tests/ -v --tb=short --cov=alpha_tech_tracker

# Run with coverage report
PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" \
  pytest tests/ -v --cov=alpha_tech_tracker --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

## Advanced Configuration

### Changing Python Versions

Edit `.github/workflows/test.yml`:

```yaml
strategy:
  matrix:
    python-version: ['3.8', '3.9', '3.10', '3.11']  # Add/remove versions
```

### Modifying Test Execution

Edit the pytest command:

```yaml
# Stop on first failure
pytest tests/ -v -x --cov=alpha_tech_tracker

# Parallel execution (faster)
pip install pytest-xdist
pytest tests/ -v -n auto --cov=alpha_tech_tracker

# Stop after N failures
pytest tests/ -v --maxfail=3 --cov=alpha_tech_tracker
```

### Adding More Branches

Edit the trigger section:

```yaml
on:
  push:
    branches: [main, develop, your-feature-branch]
```

## Troubleshooting

### Tests Pass Locally but Fail in CI

**Common causes:**
1. **Python version mismatch** - CI tests on 3.8, 3.9, 3.10
   - Solution: Test locally with all versions or use `pyenv`

2. **Missing dependencies** - `requirements.txt` not updated
   - Solution: Run `pip freeze > requirements.txt`

3. **File paths** - Absolute paths instead of relative
   - Solution: Use relative paths or `os.path.join()`

4. **Environment variables** - Different values locally vs CI
   - Solution: Check workflow env section matches your setup

### Workflow Not Triggering

**Check:**
1. Pushing to correct branch (`main`, `develop`, etc.)
2. `.github/workflows/` directory is committed
3. Workflow file is valid YAML (no syntax errors)
4. Actions are enabled in repository settings

### Coverage Upload Failing

**This is usually fine!** The workflow continues even if coverage upload fails.

To fix:
1. Sign up for [Codecov](https://codecov.io)
2. Add `CODECOV_TOKEN` to repository secrets
3. Update workflow to use the token

Or remove the coverage upload step if not needed.

## Performance Tips

### Caching Works Automatically
- First run: ~30-60s to install dependencies
- Subsequent runs: ~5-10s (cached)
- Saves time on every push!

### Parallel Testing Locally
```bash
pip install pytest-xdist
pytest tests/ -n auto  # Uses all CPU cores
```

### Skip Slow Tests During Development
```bash
# Skip all skipped tests explicitly
pytest tests/ -v --runxfail

# Run only fast tests
pytest tests/ -m "not slow"
```

## Monitoring and Maintenance

### Weekly Checks
- Review failed workflow runs
- Update dependencies if needed
- Check for deprecated Actions versions

### Monthly Tasks
- Review test coverage trends
- Update Python versions in matrix
- Archive old workflow runs (automatic after 90 days)

### Updating Actions
GitHub will create PRs to update Actions automatically if you enable Dependabot:

1. Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

## Best Practices

1. **Always run tests locally before pushing**
   ```bash
   PYTHONPATH=. TWILIO_ACCOUNT_ID="test" TWILIO_AUTH_TOKEN="test" pytest tests/ -v
   ```

2. **Use feature branches**
   - Create branch: `git checkout -b feature/my-feature`
   - Push and create PR: Tests run automatically!

3. **Review test failures immediately**
   - Don't let failing tests accumulate
   - Fix or skip intentionally with good reasons

4. **Keep test suite fast**
   - Current: ~4 seconds core tests ⚡
   - Target: Under 10 seconds
   - Skip slow tests by default (we already do this!)

## Need Help?

- Check workflow logs in Actions tab
- Review `.github/workflows/README.md` for detailed docs
- See `TESTING.md` for local testing guide
- Open an issue if you encounter problems

## Summary

✅ **CI/CD is ready to use!**
- Core tests run automatically on every push
- Integration tests available manually
- Fast feedback (~4 second test runtime)
- Multi-version Python testing
- Coverage reporting included

Just push your code and watch the tests run! 🚀
