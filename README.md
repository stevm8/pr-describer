# PR Describer

> AI-powered GitHub App that writes pull request descriptions from diffs.
> Built with FastAPI, Groq (free LLM), Supabase (free DB), Stripe, and Render (free hosting).
> **Total running cost at zero users: $0/month.**

---

## How it works

1. Developer opens a PR
2. GitHub sends a webhook to your server
3. Server fetches the diff via GitHub API
4. Diff is sent to Groq (Llama 3.3 70B) for description generation
5. Description is posted back to the PR automatically

---

## Setup (step by step)

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/pr-describer.git
cd pr-describer
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

---

### 2. Create a GitHub App

Go to https://github.com/settings/apps/new and fill in:

| Field | Value |
|---|---|
| App name | PR Describer (or anything) |
| Homepage URL | Your Render URL (can be placeholder for now) |
| Webhook URL | `https://YOUR_RENDER_URL/webhook/github` |
| Webhook secret | A random string — copy it to `GITHUB_WEBHOOK_SECRET` |

**Permissions needed:**
- Repository → Pull requests: **Read & Write**
- Repository → Contents: **Read** (for fetching diffs)
- Account → Email addresses: **Read** (for Stripe billing)

**Subscribe to events:**
- Pull request
- Installation
- Installation repositories

After creating the app:
- Copy the **App ID** → `GITHUB_APP_ID`
- Copy the **Client ID** → `GITHUB_CLIENT_ID`
- Generate a **Client secret** → `GITHUB_CLIENT_SECRET`
- Generate a **Private key** (downloads a .pem file) → paste contents into `GITHUB_APP_PRIVATE_KEY`

Update `routes/auth.py` line with your app's slug:
```python
app_slug = "your-app-slug-here"
```

---

### 3. Get a free Groq API key

1. Go to https://console.groq.com
2. Create account (free)
3. Generate API key → `GROQ_API_KEY`

Free tier: 14,400 requests/day. Enough for hundreds of PRs.

---

### 4. Create Supabase project

1. Go to https://supabase.com and create a free project
2. Settings → API → copy **Project URL** → `SUPABASE_URL`
3. Settings → API → copy **service_role** key → `SUPABASE_KEY`

Tables are created automatically on first boot via `db.py:init_db()`.
If that fails, run the SQL in `db.py` manually in the Supabase SQL editor.

---

### 5. Set up Stripe

1. Create account at https://stripe.com
2. Dashboard → API Keys → copy **Secret key** → `STRIPE_SECRET_KEY`
3. Create a product: Products → Add product → "$9/month" recurring price
4. Copy the **Price ID** → `STRIPE_PRICE_ID`
5. Add webhook endpoint later (after deploy) → `STRIPE_WEBHOOK_SECRET`

---

### 6. Deploy to Render (free)

1. Push this repo to GitHub
2. Go to https://render.com → New → Web Service → connect your repo
3. Render auto-detects `render.yaml`
4. Fill in all env vars in the Render dashboard
5. Deploy — you'll get a URL like `https://pr-describer.onrender.com`

Update in GitHub App settings:
- **Homepage URL**: your Render URL
- **Webhook URL**: `https://your-render-url.onrender.com/webhook/github`
- **Callback URL**: `https://your-render-url.onrender.com/auth/callback`

Then add your Stripe webhook:
- Stripe Dashboard → Webhooks → Add endpoint
- URL: `https://your-render-url.onrender.com/billing/webhook`
- Events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_failed`
- Copy the signing secret → `STRIPE_WEBHOOK_SECRET` in Render

---

### 7. Run locally for development

```bash
# In one terminal — start the server
source venv/bin/activate
uvicorn main:app --reload

# In another terminal — forward GitHub webhooks to localhost
# Install: https://github.com/cli/cli then:
gh webhook forward --repo=OWNER/REPO --events=pull_request,installation --url=http://localhost:8000/webhook/github
```

---

## Project structure

```
pr-describer/
├── main.py                 # FastAPI app + startup
├── config.py               # All env vars (pydantic-settings)
├── db.py                   # Supabase client + DB helpers
├── routes/
│   ├── webhook.py          # GitHub webhook handler (the core logic)
│   ├── auth.py             # GitHub OAuth flow
│   └── billing.py          # Stripe checkout + webhook
├── services/
│   ├── github.py           # GitHub API calls (tokens, diff, update PR)
│   ├── groq_ai.py          # Groq LLM — generates descriptions
│   └── stripe_svc.py       # Stripe session helpers
├── landing/
│   └── index.html          # Marketing landing page
├── requirements.txt
├── render.yaml             # One-click Render deployment
└── .env.example
```

---

## Monetisation

- **$9/month** per organisation — all repos, unlimited PRs
- **14-day free trial** (Stripe handles this automatically)
- Payment flows entirely through Stripe — you never touch card details
- Stripe takes 2.9% + 30¢ per transaction
- At 10 paying customers: ~$81/month profit. At 100: ~$810/month.

---

## Customising the AI prompt

Edit `services/groq_ai.py` → `SYSTEM_PROMPT` to change the output format,
tone, or sections. The model is set to `llama-3.3-70b-versatile` (best free model).

---

## License

MIT — do whatever you want with it.
