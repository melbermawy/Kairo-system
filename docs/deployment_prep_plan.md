# Kairo Deployment Preparation Plan

> **What is this document?**
> This is your complete guide to getting Kairo ready for real users. It covers everything from adding user accounts, to letting users bring their own API keys, to actually putting it live on the internet. Each section builds on the previous one, so work through them in order.

---

## Table of Contents

- [Overview: What We're Building](#overview-what-were-building)
- [Phase 1: Authentication (User Accounts)](#phase-1-authentication-user-accounts)
  - [1.1 Backend Changes](#11-backend-changes)
  - [1.2 Frontend Changes](#12-frontend-changes)
- [Phase 2: BYOK (Bring Your Own Key)](#phase-2-byok-bring-your-own-key)
  - [2.1 Why BYOK?](#21-why-byok)
  - [2.2 Backend: Key Storage](#22-backend-key-storage)
  - [2.3 Frontend: Settings Page](#23-frontend-settings-page)
  - [2.4 Demo Mode](#24-demo-mode)
- [Phase 3: Speed & Quality Improvements](#phase-3-speed--quality-improvements)
  - [3.1 Remove Budget Restrictions](#31-remove-budget-restrictions)
  - [3.2 Collect More Evidence](#32-collect-more-evidence)
  - [3.3 Enable All Platforms](#33-enable-all-platforms)
  - [3.4 Add TikTok Trends Scraper](#34-add-tiktok-trends-scraper)
  - [3.5 Make It Faster (Parallel Execution)](#35-make-it-faster-parallel-execution)
  - [3.6 Show Progress to Users](#36-show-progress-to-users)
- [Phase 4: Frontend Polish](#phase-4-frontend-polish)
  - [4.1 Onboarding Flow](#41-onboarding-flow)
  - [4.2 Today Board](#42-today-board)
  - [4.3 Demo Mode Banner](#43-demo-mode-banner)
  - [4.4 General Polish](#44-general-polish)
- [Phase 5: Data Migration](#phase-5-data-migration)
- [Phase 6: Deployment (Going Live)](#phase-6-deployment-going-live)
  - [6.1 The Big Picture](#61-the-big-picture)
  - [6.2 Recommended Setup](#62-recommended-setup)
  - [6.3 Deploy the Backend (Railway)](#63-deploy-the-backend-railway)
  - [6.4 Deploy the Frontend (Vercel)](#64-deploy-the-frontend-vercel)
  - [6.5 Database (Supabase)](#65-database-supabase)
  - [6.6 Background Jobs Explained](#66-background-jobs-explained)
  - [6.7 Connect Frontend to Backend](#67-connect-frontend-to-backend)
  - [6.8 Custom Domains](#68-custom-domains)
  - [6.9 Monitoring Your App](#69-monitoring-your-app)
  - [6.10 Cost Breakdown](#610-cost-breakdown)
  - [6.11 Step-by-Step Deployment Walkthrough](#611-step-by-step-deployment-walkthrough)
- [Quick Reference: Environment Variables](#quick-reference-environment-variables)
- [Security Checklist](#security-checklist)
- [Success Criteria (How to Know You're Done)](#success-criteria-how-to-know-youre-done)

---

## Overview: What We're Building

Right now, Kairo works but it's not ready for other people to use. Here's what needs to change:

| Current State | What We Need |
|--------------|--------------|
| No user accounts - anyone can see everything | Real login/signup with user accounts |
| Uses your API keys for everyone | Each user brings their own API keys |
| Budget limits to save your money | No limits (users pay for their own usage) |
| Only runs on your computer | Live on the internet for anyone to access |

**The plan has 6 phases:**

1. **Authentication** - Add user accounts so people can sign up and log in
2. **BYOK** - Let users connect their own Apify and OpenAI keys
3. **Speed & Quality** - Remove budget limits, add more data sources, make it faster
4. **Polish** - Make the interface smoother and more professional
5. **Migration** - Keep your existing Goodie AI brand data
6. **Deployment** - Put it live on the internet

---

## Phase 1: Authentication (User Accounts)

### What We're Doing

Right now, there are no user accounts. Anyone who opens Kairo can see all the brands. We need to add:
- A way for people to sign up with email/password
- A way for people to log in
- A way to make sure each user only sees their own brands

We'll use **Supabase Auth** for this because you're already using Supabase for the database, and it's free.

### 1.1 Backend Changes

**What needs to happen:**

First, we need to create a User model in Django. This is a database table that stores information about each user:

```python
# kairo/users/models.py

class User(AbstractBaseUser):
    """
    Represents a user account in Kairo.
    Links to Supabase Auth for actual login/password handling.
    """
    id = UUIDField(primary_key=True)
    email = EmailField(unique=True)
    supabase_uid = CharField(unique=True)  # This connects to Supabase
    created_at = DateTimeField(auto_now_add=True)
```

Then we need to link brands to users:

```python
# Add this to the Brand model
owner = ForeignKey(User, on_delete=CASCADE)
```

Finally, we need "middleware" - code that runs on every request to check if the user is logged in:

```python
# What the middleware does:
# 1. Look for a "token" in the request (sent by the frontend)
# 2. Ask Supabase "is this token valid?"
# 3. If yes, attach the user to the request
# 4. If no, return a "please log in" error
```

### 1.2 Frontend Changes

**New pages we need to create:**

| Page | What it does |
|------|-------------|
| `/login` | Email/password form to log in |
| `/signup` | Email/password form to create account |

**Changes to existing pages:**

- All brand pages (`/brands/...`) now require login
- If you're not logged in, you get redirected to `/login`
- The top bar shows your email and a logout button

**New dependencies to install:**

```bash
npm install @supabase/supabase-js @supabase/ssr
```

---

## Phase 2: BYOK (Bring Your Own Key)

### 2.1 Why BYOK?

BYOK stands for "Bring Your Own Key". Here's why it matters:

**The problem:** Kairo uses Apify (to scrape social media) and OpenAI (to generate opportunities). These services cost money per use. Right now, those costs come from your accounts.

**The solution:** Each user connects their own API keys. They pay for their own usage directly to Apify and OpenAI. You don't pay anything.

**The benefit:** You can have unlimited users without worrying about costs.

### 2.2 Backend: Key Storage

Users will paste in their API keys. We need to store them securely:

```python
class UserAPIKeys(models.Model):
    """
    Stores a user's API keys (encrypted).
    We never store keys in plain text!
    """
    user = OneToOneField(User, on_delete=CASCADE)

    # The actual keys, encrypted
    apify_token_encrypted = BinaryField(null=True)
    openai_key_encrypted = BinaryField(null=True)

    # Just the last 4 characters, for display
    # So users can see "sk-...7x4f" and know which key they added
    apify_token_last4 = CharField(max_length=4, null=True)
    openai_key_last4 = CharField(max_length=4, null=True)
```

**API endpoints we need:**

| Endpoint | What it does |
|----------|-------------|
| `GET /api/user/api-keys/` | Shows if keys are connected (just last 4 chars) |
| `PUT /api/user/api-keys/` | Save new keys |
| `POST /api/user/api-keys/validate/` | Test if a key actually works |

### 2.3 Frontend: Settings Page

We need a new Settings page where users can manage their API keys:

```
┌─────────────────────────────────────────────────────────────┐
│  Settings                                                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  API Keys                                                    │
│  ─────────                                                   │
│                                                              │
│  Apify Token                                                 │
│  ┌─────────────────────────────────┐  ┌──────────────────┐  │
│  │ ●●●●●●●●●●●●●●●●               │  │ Test Connection  │  │
│  └─────────────────────────────────┘  └──────────────────┘  │
│  ✓ Connected (ends in ...3Bvt)                              │
│                                                              │
│  OpenAI API Key                                              │
│  ┌─────────────────────────────────┐  ┌──────────────────┐  │
│  │ ●●●●●●●●●●●●●●●●               │  │ Test Connection  │  │
│  └─────────────────────────────────┘  └──────────────────┘  │
│  ✓ Connected (ends in ...tYA)                               │
│                                                              │
│                                        ┌────────────────┐   │
│                                        │  Save Changes  │   │
│                                        └────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**How the flow works:**

1. User goes to Settings
2. Pastes their Apify token
3. Clicks "Test Connection" - we try to use the key with Apify
4. If it works, show green checkmark
5. User clicks "Save Changes"
6. Now when they regenerate opportunities, their key is used

### 2.4 Demo Mode

**What if a user doesn't have API keys yet?**

They can still explore Kairo in "Demo Mode":

- They see sample/fake opportunity data (not real data)
- They can go through onboarding and set up a brand
- The "Regenerate" button is disabled or shows a message
- A banner at the top says "Demo Mode - Connect your API keys for real data"

This lets people try Kairo before committing to getting API keys.

---

## Phase 3: Speed & Quality Improvements

### 3.1 Remove Budget Restrictions

**Why we had budget limits:**

During development, you were paying for all Apify usage. So we added strict limits to avoid surprise bills:

```python
# Current limits (very conservative)
APIFY_DAILY_SPEND_CAP_USD = 0.50    # Only 50 cents per day
APIFY_PER_REGENERATE_CAP_USD = 0.25  # Only 25 cents per regeneration
MIN_EVIDENCE_ITEMS = 8               # Stop early if we have 8 items
```

**Why we're removing them:**

With BYOK, users pay for their own usage. They control their own Apify account limits. We don't need to protect your wallet anymore.

```python
# New approach - let it run freely
APIFY_PER_REGENERATE_CAP_USD = None  # No cap
MIN_EVIDENCE_ITEMS = None            # Don't stop early
```

### 3.2 Collect More Evidence

More evidence = better opportunities. We're increasing how much content we scrape:

| Source | Old Limit | New Limit | What This Means |
|--------|-----------|-----------|-----------------|
| Instagram hashtag search | 20 posts | 40 posts | 2x more Instagram content |
| Instagram reels with transcripts | 5 reels | 10 reels | 2x more video insights |
| TikTok videos | 15 videos | 30 videos | 2x more TikTok trends |
| YouTube videos | 10 videos | 20 videos | 2x more YouTube content |

**Result:** Instead of ~30 pieces of evidence, we'll get ~100. This gives the AI much more to work with when generating opportunities.

### 3.3 Enable All Platforms

Currently, we only scrape Instagram to save money. With BYOK, we can turn everything on:

```python
# Old (budget-constrained)
DEFAULT_EXECUTION_PLAN = ["IG-1", "IG-3"]  # Just Instagram

# New (full coverage)
DEFAULT_EXECUTION_PLAN = [
    "IG-1",       # Instagram hashtag search
    "IG-3",       # Instagram keyword search
    "TT-1",       # TikTok keyword search
    "TT-TRENDS",  # TikTok trending content (NEW!)
    "YT-1",       # YouTube search
    "LI-1",       # LinkedIn posts
]
```

### 3.4 Add TikTok Trends Scraper

**What is this?**

A new data source that pulls what's actually trending on TikTok right now. Instead of searching for topics and hoping they're relevant, we get straight from TikTok's trend data:

- Top trending hashtags
- Trending videos
- Trending creators

**Why it matters:**

Current approach: "Let me search TikTok for 'marketing' and hope the results are trending"

New approach: "Let me get TikTok's actual trending content and find what's relevant to this brand"

**Technical details (for implementation):**

```python
"TT-TRENDS": RecipeSpec(
    recipe_id="TT-TRENDS",
    platform="tiktok",
    description="TikTok Trends Discovery",
    stage1_actor="clockworks/tiktok-trends-scraper",
    stage1_input_builder=build_tt_trends_input,
    stage1_result_limit=100,
)
```

The input builder looks at the brand's positioning and pillars to pick relevant industry categories (Technology, Marketing, Business, etc.).

### 3.5 Make It Faster (Parallel Execution)

**Current problem:**

Right now, we scrape platforms one at a time:
1. Search Instagram hashtags (wait 15 seconds)
2. Search Instagram keywords (wait 15 seconds)
3. Search TikTok (wait 15 seconds)
4. ... and so on

Total: 45-60 seconds of waiting.

**The fix:**

Run them all at the same time (in parallel):
1. Search Instagram hashtags AND Instagram keywords AND TikTok AND YouTube simultaneously
2. Wait ~15 seconds for all of them to finish

Total: ~15-20 seconds.

**Expected improvement:** 3x faster evidence collection.

### 3.6 Show Progress to Users

**Current problem:**

When a user clicks "Regenerate", they just see a spinner. They have no idea what's happening or how long it will take.

**The fix:**

Show progress stages:

```
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  Generating your opportunities...                            │
│                                                              │
│  [=========>                    ] Step 2 of 4               │
│                                                              │
│  ✓ Collecting evidence (found 87 posts)                     │
│  → Analyzing trends...                                       │
│  ○ Synthesizing opportunities                                │
│  ○ Scoring and ranking                                       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Phase 4: Frontend Polish

### 4.1 Onboarding Flow

**Current issues:**

- The step indicator isn't clear about where you are
- Validation only happens when you submit, not as you type
- Source connection (Instagram URL, etc.) is confusing
- Transitions between steps feel janky

**Improvements:**

1. **Progress bar at top** showing: Basics → Sources → Details → Compile
2. **Real-time validation** - show errors as the user types, not after
3. **Better source setup** - guide users through connecting Instagram/TikTok with examples
4. **Smooth animations** - use Framer Motion for nice transitions

### 4.2 Today Board

**Current issues:**

- When generating, it's just a spinner with no context
- When opportunities appear, they just pop in suddenly
- Error states say "something went wrong" with no help
- "Insufficient evidence" feels like a dead end
- Today board triggers opportunity regeneration even when BrandBrain hasn't been onboarded yet

**Improvements:**

1. **Skeleton loading** - show placeholder cards that shimmer while loading
2. **Staggered animation** - cards animate in one by one
3. **Helpful errors** - tell users what went wrong and what to do:
   - "Your API key might be invalid - check Settings"
   - "Rate limited - try again in 5 minutes"
4. **Insufficient evidence guidance** - "Try adding more source connections or adjusting your content pillars"
5. **Pre-onboarding guard** - Check for snapshot existence before allowing/triggering regeneration. Show a message like "Complete BrandBrain onboarding first" if no snapshot exists.

### 4.3 Demo Mode Banner

When users don't have API keys, show a clear banner:

```
┌─────────────────────────────────────────────────────────────┐
│ 🎭 Demo Mode - You're viewing sample data                   │
│ Connect your API keys to generate real insights             │
│                                        [Connect Keys →]     │
└─────────────────────────────────────────────────────────────┘
```

This appears at the top of the page (below the navigation) and links to Settings.

### 4.4 General Polish

Small improvements that add up:

| Area | Improvement |
|------|-------------|
| Loading states | Use skeleton loaders instead of spinners |
| Empty states | Show helpful illustrations, not blank pages |
| Toast notifications | Show success/error messages in bottom-right |
| Mobile | Make sure everything works on phones |
| Keyboard | Tab, Enter, and Escape should work as expected |

---

## Phase 5: Data Migration

**The situation:**

You have a test brand called "Goodie AI" with onboarding data, snapshots, and generated opportunities. When we add user accounts, we need to make sure this data isn't lost.

**The plan:**

1. When the auth system goes live, create your user account (mohamedabdouelbermawy@gmail.com)
2. Run a migration script that assigns the Goodie AI brand to your account
3. All existing data (onboarding answers, snapshots, opportunities) stays intact

```python
# Migration pseudo-code
your_user = User.objects.create(email="mohamedabdouelbermawy@gmail.com")
Brand.objects.filter(name="Goodie AI").update(owner=your_user)
```

---

## Phase 6: Deployment (Going Live)

### 6.1 The Big Picture

**What does "deployment" mean?**

Right now, Kairo runs on your computer. When you close your laptop, it stops. "Deployment" means putting it on servers in the cloud that run 24/7, so anyone can access it from anywhere.

**What needs to be deployed?**

Kairo has multiple parts that need to run:

| Part | What It Is | Where We'll Put It |
|------|-----------|-------------------|
| **Backend** | The Python/Django server that handles API requests and runs background jobs | Railway |
| **Frontend** | The Next.js website that users actually see and interact with | Vercel |
| **Database** | PostgreSQL database storing all the data | Supabase (already done!) |

**Good news:** You already have the database set up on Supabase. We just need to deploy the backend and frontend.

### 6.2 Recommended Setup

After researching options, here's the best setup for someone new to deployment:

| Service | What | Cost | Why This One |
|---------|------|------|--------------|
| **Vercel** | Frontend hosting | Free | Made for Next.js, super easy, automatic deploys |
| **Railway** | Backend hosting | $0-5/month | Easy Python hosting, handles background jobs |
| **Supabase** | Database | Free | You already have this |

**Total cost: $0-5 per month** to start. That's it.

### 6.3 Deploy the Backend (Railway)

**Step 1: Create some config files**

Railway needs to know how to run your app. Create these files in the `Kairo-system` folder:

**`Procfile`** (tells Railway what command to run):
```
web: gunicorn kairo.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2
```

**`runtime.txt`** (tells Railway which Python version):
```
python-3.11.7
```

Also add `gunicorn>=21.0.0` to your dependencies (in `pyproject.toml` or `requirements.txt`). Gunicorn is the "production server" for Django.

**Step 2: Sign up for Railway**

1. Go to [railway.app](https://railway.app)
2. Click "Login" and choose "Login with GitHub"
3. Authorize Railway to access your GitHub

**Step 3: Create a new project**

1. Click "New Project" on the dashboard
2. Click "Deploy from GitHub repo"
3. Find and select `Kairo-system`
4. Railway will detect it's Python and start building

**Step 4: Add environment variables**

The build will probably fail because it needs environment variables. In the Railway dashboard:

1. Click on your service
2. Go to "Variables" tab
3. Add these variables (copy values from your `.env` file):

```
DJANGO_SECRET_KEY=<generate a new random string for production>
DATABASE_URL=<your Supabase connection string>
DJANGO_DEBUG=false
ALLOWED_HOSTS=<your-app-name>.up.railway.app
CORS_ALLOWED_ORIGINS=https://<your-vercel-url>.vercel.app
```

**Step 5: Wait for deployment**

Railway will rebuild with the environment variables. Once it's green, you'll get a URL like `https://kairo-system-production.up.railway.app`.

Test it by visiting `https://kairo-system-production.up.railway.app/health/` - it should return a success response.

### 6.4 Deploy the Frontend (Vercel)

**Step 1: Sign up for Vercel**

1. Go to [vercel.com](https://vercel.com)
2. Click "Sign Up" and choose "Continue with GitHub"
3. Authorize Vercel

**Step 2: Import your project**

1. Click "Add New..." → "Project"
2. Find and select `kairo-frontend`
3. **Important:** Under "Root Directory", click "Edit" and set it to `ui`
   - This is because your Next.js app is inside the `ui` folder, not the root
4. Click "Deploy"

**Step 3: Add environment variables**

The first deploy might fail or show errors. Add environment variables:

1. Go to your project settings
2. Click "Environment Variables"
3. Add these:

```
NEXT_PUBLIC_API_BASE_URL=https://your-railway-url.up.railway.app
NEXT_PUBLIC_API_MODE=real
NEXT_PUBLIC_SUPABASE_URL=https://qtohqspbwroqibnjnbue.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your Supabase anon key>
```

**Step 4: Redeploy**

1. Go to "Deployments" tab
2. Click the "..." menu on the latest deployment
3. Click "Redeploy"

Once it's done, you'll have a URL like `https://kairo-frontend.vercel.app`.

### 6.5 Database (Supabase)

**You're already set up!** Your Supabase database is already running in the cloud.

**One thing to check:** Make sure you're using the "pooled" connection string (has port 6543). This handles multiple connections better:

```
postgresql://postgres.[project-ref]:[password]@aws-0-us-west-2.pooler.supabase.com:6543/postgres
```

You can find this in Supabase Dashboard → Settings → Database → Connection string → Mode: Transaction.

### 6.6 Background Jobs Explained

**You might be wondering:** "I heard Kairo has background jobs - don't I need something special for that?"

**The simple answer:** No, it's already handled.

**The longer explanation:**

When a user clicks "Regenerate", we can't make them wait 30-60 seconds for the page to load. Instead:

1. We immediately return "OK, we're working on it" (takes 1 second)
2. A "background job" runs separately to do the actual work
3. The frontend polls every few seconds to check if it's done
4. When it's done, the frontend shows the results

**How Kairo handles this:**

Many apps use something called "Celery" with "Redis" for background jobs. Kairo uses a simpler approach:

- Jobs are stored in the database (a table called `OpportunitiesJob`)
- The same Django process that handles web requests also processes these jobs
- No extra services needed!

This means when you deploy to Railway, background jobs just work automatically. You don't need to set up anything extra.

**In the future:** If you get lots of users and need more power, you could run a separate "worker" process. But for now, the simple setup is fine.

### 6.7 Connect Frontend to Backend

After deploying both, you need to make sure they can talk to each other:

**Step 1: Tell the frontend where the backend is**

In Vercel, make sure `NEXT_PUBLIC_API_BASE_URL` is set to your Railway URL:
```
https://kairo-system-production.up.railway.app
```

**Step 2: Tell the backend to accept requests from the frontend**

In Railway, make sure `CORS_ALLOWED_ORIGINS` includes your Vercel URL:
```
https://kairo-frontend.vercel.app
```

**Step 3: Test it**

1. Open your Vercel URL in a browser
2. Open browser developer tools (F12) and go to the Network tab
3. Try to do something that calls the API (like loading the homepage)
4. Make sure the requests to your Railway backend succeed (200 status)

If you see "CORS error" or "blocked by CORS policy", double-check the `CORS_ALLOWED_ORIGINS` setting in Railway.

### 6.8 Custom Domains

Both Railway and Vercel give you free URLs, but they look like:
- `https://kairo-frontend.vercel.app`
- `https://kairo-system-production.up.railway.app`

**If you have your own domain** (like `kairo.app`), you can connect it:

| Subdomain | Points To | How |
|-----------|-----------|-----|
| `app.kairo.app` | Vercel | Vercel dashboard → Domains → Add |
| `api.kairo.app` | Railway | Railway dashboard → Settings → Domains |

Both platforms handle SSL certificates automatically, so you get `https://` for free.

**If you don't have a domain:** That's fine! The free URLs work perfectly.

### 6.9 Monitoring Your App

Once you're live, you'll want to know if something breaks.

**Basic monitoring (free):**

- **Railway logs:** Dashboard → Your service → Logs tab
- **Vercel logs:** Dashboard → Your project → Logs tab
- **UptimeRobot:** Free service that pings your site every 5 minutes and emails you if it's down

**Advanced monitoring (later, when you have users):**

- **Sentry:** Automatic error tracking - when something crashes, you get an alert with details
- **LogDNA/Papertrail:** Searchable logs

For now, just check the Railway and Vercel logs if something seems wrong.

### 6.10 Cost Breakdown

Let's talk money:

| Service | Free Tier Includes | When You'd Pay |
|---------|-------------------|----------------|
| **Vercel** | 100GB bandwidth/month, unlimited deploys | If you get thousands of users |
| **Railway** | $5 free credit, 500 hours/month | When credit runs out (~$5/month) |
| **Supabase** | 500MB database, 50K monthly active users | If you need more storage |

**For launching and getting your first users: $0-5/month**

**If Kairo takes off:** Maybe $50-100/month at scale, but that's a good problem to have!

### 6.11 Step-by-Step Deployment Walkthrough

Here's the exact sequence, in plain English:

```
BEFORE YOU START
================
□ Make sure your code is pushed to GitHub
□ Have your .env file handy (you'll copy values from it)

STEP 1: PREPARE BACKEND CODE
============================
□ Create a file called "Procfile" (no extension) in Kairo-system folder
  Contents: web: gunicorn kairo.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --threads 2

□ Create a file called "runtime.txt" in Kairo-system folder
  Contents: python-3.11.7

□ Add "gunicorn>=21.0.0" to your dependencies

□ Commit and push these changes to GitHub

STEP 2: DEPLOY BACKEND TO RAILWAY
=================================
□ Go to railway.app and sign in with GitHub
□ Click "New Project"
□ Click "Deploy from GitHub repo"
□ Select "Kairo-system"
□ Wait for it to detect Python and start building
□ Go to Variables tab and add your environment variables
□ Wait for it to redeploy
□ Copy your Railway URL (something.up.railway.app)
□ Test: visit your-url/health/ - should work

STEP 3: DEPLOY FRONTEND TO VERCEL
=================================
□ Go to vercel.com and sign in with GitHub
□ Click "Add New" → "Project"
□ Select "kairo-frontend"
□ Set Root Directory to "ui"
□ Click Deploy
□ Go to Settings → Environment Variables
□ Add NEXT_PUBLIC_API_BASE_URL = your Railway URL
□ Add other environment variables
□ Go to Deployments and click Redeploy
□ Copy your Vercel URL (something.vercel.app)

STEP 4: CONNECT THEM
====================
□ In Railway, add your Vercel URL to CORS_ALLOWED_ORIGINS
□ Wait for Railway to redeploy
□ Open your Vercel URL in browser
□ Check browser dev tools - API calls should work (no CORS errors)

STEP 5: VERIFY EVERYTHING WORKS
===============================
□ Can you see the homepage?
□ Can you create an account? (after Phase 1 is implemented)
□ Can you create a brand?
□ Can you go through onboarding?
□ Does Regenerate work? (if you have API keys configured)

YOU'RE LIVE! 🎉
```

---

## Quick Reference: Environment Variables

### Backend (.env on Railway)

```bash
# REQUIRED
DJANGO_SECRET_KEY=<long random string - generate a new one for production>
DATABASE_URL=<your Supabase pooled connection string>
DJANGO_DEBUG=false
ALLOWED_HOSTS=your-app.up.railway.app,localhost

# AUTHENTICATION (after Phase 1)
SUPABASE_URL=https://qtohqspbwroqibnjnbue.supabase.co
SUPABASE_SERVICE_KEY=<your Supabase service role key>
ENCRYPTION_KEY=<for encrypting user API keys>

# CORS
CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app,http://localhost:3000

# OPTIONAL (can leave empty if using BYOK)
OPENAI_API_KEY=<your key or empty>
APIFY_TOKEN=<your token or empty>
APIFY_ENABLED=true
```

### Frontend (.env on Vercel)

```bash
# API
NEXT_PUBLIC_API_BASE_URL=https://your-backend.up.railway.app
NEXT_PUBLIC_API_MODE=real

# AUTHENTICATION (after Phase 1)
NEXT_PUBLIC_SUPABASE_URL=https://qtohqspbwroqibnjnbue.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your Supabase anon/public key>
```

---

## Security Checklist

Before going live with real users, make sure:

- [ ] API keys are encrypted in the database (not plain text)
- [ ] API keys are never written to logs
- [ ] API keys are never returned in full in API responses (only last 4 chars)
- [ ] Supabase JWT is validated on every API request
- [ ] Users can only access their own brands (not other users' data)
- [ ] CORS only allows your frontend domain (not `*`)
- [ ] `DJANGO_DEBUG=false` in production
- [ ] Using HTTPS (both Railway and Vercel do this automatically)

---

## Success Criteria (How to Know You're Done)

Use this checklist to verify each phase is complete:

### Phase 1: Authentication
- [ ] User can sign up with email/password
- [ ] User can log in and stay logged in
- [ ] User can only see their own brands
- [ ] Logout works
- [ ] Pages redirect to login if not authenticated

### Phase 2: BYOK
- [ ] Settings page exists with API key inputs
- [ ] "Test Connection" button works
- [ ] Keys are saved and show as "•••• ending in xxxx"
- [ ] Regeneration uses user's own keys
- [ ] Keys are encrypted in database

### Phase 3: Speed & Quality
- [ ] Regeneration takes <30 seconds (was 60-90s)
- [ ] All platforms enabled (Instagram, TikTok, YouTube, LinkedIn)
- [ ] TikTok Trends recipe works
- [ ] ~100 evidence items collected (was ~30)

### Phase 4: Frontend Polish
- [ ] Onboarding has clear progress indicator
- [ ] Today board shows skeleton loaders while generating
- [ ] Error states are helpful (not just "something went wrong")
- [ ] Demo mode banner shows for users without keys

### Phase 5: Data Migration
- [ ] Goodie AI brand still exists
- [ ] All snapshots preserved
- [ ] Brand assigned to your account

### Phase 6: Deployment
- [ ] Backend running on Railway
- [ ] Frontend running on Vercel
- [ ] Frontend can call backend (no CORS errors)
- [ ] Database migrations ran successfully
- [ ] Health check endpoint works
- [ ] Full user flow works (signup → create brand → onboard → regenerate)

---

**You've got this!** Take it one phase at a time. If you get stuck, the error messages usually tell you what's wrong - check Railway/Vercel logs first.
