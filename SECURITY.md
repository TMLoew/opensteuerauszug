# Security Guidelines

This repository handles sensitive personal tax and financial data. Follow these guidelines to protect your privacy.

## Files That Should NEVER Be Committed

### Personal Configuration
- ❌ `config.toml` - Contains your name, canton, account numbers
- ✅ `config.toml.example` - Template file (safe to commit)

### Financial Data
- ❌ `data/*.xml` - Broker statements with your trading history
- ❌ `data/manual_prices.csv` - Your portfolio holdings
- ❌ `data/security_identifiers.csv` - Your security mappings

### Generated Output
- ❌ `out/*.pdf` - Tax statements with your personal data
- ❌ `out/*.xml` - Tax data in XML format

### System Files
- ❌ `.DS_Store` - macOS metadata (may leak file information)
- ❌ `*.log` - May contain sensitive information

## Protected by .gitignore

The following patterns are automatically ignored:

```gitignore
# Sensitive data files
/data/*.xml
/data/manual_prices.csv
/data/security_identifiers.csv
/config.toml

# Generated outputs
/out/*.pdf
/out/*.xml

# System files
.DS_Store
**/.DS_Store
```

## Setup Checklist

When setting up your local instance:

1. **Copy template files:**
   ```bash
   cp config.toml.example config.toml
   cp data/manual_prices.csv.example data/manual_prices.csv
   cp data/security_identifiers.csv.example data/security_identifiers.csv
   ```

2. **Edit with your data:**
   - Update `config.toml` with your personal information
   - Add your securities to `manual_prices.csv` (if needed)
   - Add your ISIN/Valor mappings to `security_identifiers.csv` (if needed)

3. **Verify protection:**
   ```bash
   git status  # Should NOT show config.toml or data/*.csv
   ```

## Before Every Commit

Run this checklist:

```bash
# Check for sensitive files
git status | grep -E "(config\.toml|\.xml|manual_prices\.csv|\.pdf)"

# If anything shows up, DO NOT commit
```

## If You Accidentally Commit Sensitive Data

If you accidentally commit sensitive data but **haven't pushed yet**:

```bash
# Remove the file from the last commit
git reset HEAD~1
git add .gitignore
git commit -m "Add .gitignore"
```

If you've **already pushed** to a remote repository:

1. **Consider the data compromised** - Change passwords, rotate credentials if applicable
2. Remove the file from git:
   ```bash
   git rm --cached sensitive_file.xml
   git commit -m "Remove sensitive data"
   git push
   ```
3. **Note:** The data is still in git history. To completely remove:
   - Use `git filter-branch` or BFG Repo-Cleaner
   - Force push to remote
   - Notify anyone who has cloned the repository

## Data Privacy Best Practices

1. **Never share your `config.toml`** or any files in `data/` directory
2. **Be careful with screenshots** - They may contain account numbers or personal data
3. **Use example data in issues** - When reporting bugs, use fake/example data
4. **Review PDFs before sharing** - Generated PDFs contain all your tax data
5. **Keep backups encrypted** - Use encrypted storage for your tax files

## Safe to Share

These files are safe to share publicly:

- ✅ `*.example` files (templates)
- ✅ `scripts/*.py` (unless modified with your data)
- ✅ `src/**/*.py` (source code)
- ✅ `tests/**/*.py` (test code)
- ✅ Documentation files (`README.md`, etc.)

## Questions?

If you're unsure whether a file is safe to commit:
1. Check if it contains your name, account numbers, ISINs, or financial values
2. If yes → DO NOT commit
3. If unsure → Ask or err on the side of caution
