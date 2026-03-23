# PR Describer

> AI-powered GitHub App that writes pull request descriptions from diffs.
> Built with FastAPI, Groq, Supabase, Stripe, and Render.

---

## How it works

1. Developer opens a PR
2. GitHub sends a webhook to your server
3. Server fetches the diff via GitHub API
4. Diff is sent to Groq (Llama 3.3 70B) for description generation
5. Description is posted back to the PR automatically


