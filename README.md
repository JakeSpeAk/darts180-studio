# darts180 Studio — Railway Deployment

Brand image generator for darts180.fr. Generates on-brand visuals for Instagram, blog, and product reviews using OpenAI's image generation API.

## Architecture

Single Docker container running:
- **Express server** (Node.js) — serves the React frontend + API routes
- **Python FastAPI** — handles image generation via OpenAI + logo compositing via Pillow

## Prerequisites

1. A [Railway account](https://railway.app) (free tier: 500 hours/month, $5 usage)
2. An [OpenAI API key](https://platform.openai.com/api-keys) with access to `gpt-image-1` (or `dall-e-3`)

## Deployment Steps

### Step 1: Push to GitHub

Create a new GitHub repository (private recommended):

```bash
cd darts180-railway
git init
git add .
git commit -m "Initial deploy - darts180 Studio"
git remote add origin https://github.com/YOUR_USERNAME/darts180-studio.git
git push -u origin main
```

### Step 2: Create Railway Project

1. Go to [railway.app](https://railway.app) and sign in
2. Click **"New Project"** → **"Deploy from GitHub Repo"**
3. Select your `darts180-studio` repository
4. Railway will detect the Dockerfile and start building

### Step 3: Add Environment Variables

In Railway dashboard → your service → **Variables** tab, add:

| Variable | Value | Required |
|----------|-------|----------|
| `OPENAI_API_KEY` | `sk-...` (your OpenAI key) | Yes |
| `PYTHON_IMAGE_SERVER` | `http://127.0.0.1:5001` | Already set in Dockerfile |
| `NODE_ENV` | `production` | Already set in Dockerfile |

### Step 4: Generate a Domain

1. In Railway → your service → **Settings** tab
2. Under **Networking** → click **"Generate Domain"**
3. You'll get a URL like: `darts180-studio-production.up.railway.app`
4. (Optional) Add a custom domain like `studio.darts180.fr`

### Step 5: Verify

Visit your Railway URL. You should see the darts180 Studio interface. Try generating an image to confirm the OpenAI connection works.

## Custom Domain Setup (Optional)

To use `studio.darts180.fr`:

1. In Railway → Settings → Networking → **"Custom Domain"**
2. Enter `studio.darts180.fr`
3. Railway will show you a CNAME record to add
4. In your DNS provider (likely Shopify or your domain registrar), add:
   - **Type:** CNAME
   - **Name:** `studio`
   - **Value:** (the Railway CNAME target)
5. Wait for DNS propagation (~5-30 minutes)

## Environment Variables Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | HTTP port (set automatically by Railway) | `3000` |
| `OPENAI_API_KEY` | OpenAI API key for image generation | (required) |
| `PYTHON_IMAGE_SERVER` | Internal Python server URL | `http://127.0.0.1:5001` |
| `NODE_ENV` | Node environment | `production` |

## OpenAI API Costs

Image generation pricing (as of 2026):
- **gpt-image-1**: ~$0.04–0.08 per image (1024×1024), ~$0.08–0.12 for larger
- **dall-e-3**: ~$0.04–0.08 per image

At ~50 images/month, expect roughly $2–6/month in OpenAI costs.

## Updating the App

Push changes to GitHub → Railway auto-deploys:

```bash
git add .
git commit -m "Update description"
git push
```

## Troubleshooting

**Build fails:** Check Railway build logs. Common issue: Python dependency version conflicts.

**Image generation fails:** Verify `OPENAI_API_KEY` is set correctly in Railway Variables.

**Slow first load:** Free tier services sleep after inactivity. First request may take 10–20s to wake up.

**Logo not appearing:** Ensure `logo-light.jpg` and `logo-dark.jpg` are in the root of the Docker build context.
