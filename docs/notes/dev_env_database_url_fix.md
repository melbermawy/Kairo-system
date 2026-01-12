# Fixing Rogue DATABASE_URL Override

**Problem:** `DATABASE_URL` in your shell environment overrides the value in `.env`, causing Django to connect to localhost instead of Supabase.

---

## Diagnosis

When you run:
```bash
echo $DATABASE_URL
```

If it shows `postgresql://postgres:postgres@localhost:5432/postgres` (or similar localhost URL) instead of your Supabase URL, your shell has an exported environment variable that takes precedence over `.env`.

**Why this happens:**
- Environment variables set via `export` in your shell take precedence over `.env` files
- `python-dotenv` (which loads `.env`) does NOT override existing environment variables by default
- The rogue export likely came from: shell config files, conda activation scripts, or a previous terminal session

---

## Locate the Source (macOS/zsh)

Run these commands to find where the rogue export lives:

```bash
# Check shell config files
grep -r "DATABASE_URL" ~/.zshrc ~/.zshenv ~/.zprofile ~/.bash_profile ~/.bashrc 2>/dev/null

# Check conda environments (if using conda)
grep -r "DATABASE_URL" ~/miniconda3/envs/*/etc/conda/activate.d/ 2>/dev/null
grep -r "DATABASE_URL" ~/anaconda3/envs/*/etc/conda/activate.d/ 2>/dev/null
grep -r "DATABASE_URL" /opt/miniconda3/envs/*/etc/conda/activate.d/ 2>/dev/null

# Check current conda env activation scripts
if [ -n "$CONDA_PREFIX" ]; then
    grep -r "DATABASE_URL" "$CONDA_PREFIX/etc/conda/activate.d/" 2>/dev/null
fi

# Check if it's set by some other tool
env | grep DATABASE_URL
```

---

## Remove the Override

### Option A: Remove from shell config
If found in `~/.zshrc`, `~/.zprofile`, etc.:
```bash
# Edit the file and remove/comment the export line
nano ~/.zshrc  # or whichever file contains it

# Then reload
source ~/.zshrc
```

### Option B: Remove from conda activation script
If found in conda:
```bash
# Edit the activation script
nano "$CONDA_PREFIX/etc/conda/activate.d/env_vars.sh"

# Remove the DATABASE_URL line, save, then reactivate
conda deactivate && conda activate <your-env>
```

### Option C: Immediate fix for current session
```bash
unset DATABASE_URL
```

---

## Verification

After fixing, verify:

```bash
# Should show nothing or your Supabase URL from .env
echo $DATABASE_URL

# Should connect to Supabase successfully
python manage.py check

# Should show Supabase URL
python -c "from django.conf import settings; print(settings.DATABASE_URL)"
```

---

## One-Command Workaround

If you can't fix the root cause immediately, use the helper script:

```bash
# Instead of:
python manage.py <command>

# Use:
python scripts/run_manage.py <command>

# Examples:
python scripts/run_manage.py check
python scripts/run_manage.py migrate
python scripts/run_manage.py shell
```

This script explicitly loads `.env` and overrides any rogue environment variables before running Django.

---

## Why .env Doesn't Override

By default, `python-dotenv`'s `load_dotenv()` does NOT override existing environment variables. This is intentional—it allows deployment environments to set variables that won't be clobbered by `.env`.

However, it means a rogue `export DATABASE_URL=...` in your shell will always win. The helper script works around this by explicitly setting the variable after loading `.env`.
