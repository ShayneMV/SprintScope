# Deployment Guide: SprintScope on Streamlit Cloud

This guide explains how to deploy the SprintScope app to Streamlit Cloud for public access.

## Prerequisites

- GitHub account with this repository
- Streamlit Cloud account (free at https://streamlit.io/)
- Your OneDrive data or CSV files ready to share

## Step 1: Deploy to Streamlit Cloud

1. Go to https://streamlit.io/cloud
2. Click **"New app"**
3. Select your repository: `ShayneMV/SprintScope`
4. Main file path: `_app/app.py`
5. Click **"Deploy"**

Streamlit Cloud will:
- Clone your repo
- Install dependencies from `requirements.txt`
- Run the app at a public URL like: `https://your-app-name.streamlit.app`

## Step 2: Configure Secrets

Since the deployed app can't access your local OneDrive, you have two options:

### Option A: Upload CSV Files via Browser (Recommended for Sharing)

Add a file upload widget to the UI so users can upload their own CSV files. This is the easiest way to share with others.

**Todo**: Implement file upload in the UI.

### Option B: Use Streamlit Cloud Secrets

1. Go to your app on Streamlit Cloud dashboard
2. Click **Settings** → **Secrets**
3. Add environment variables:
   ```
   data_root = "/tmp/laveg"
   db_path = "/tmp/laveg.sqlite"
   ```
4. Re-deploy or the app will use these values

## Step 3: Manage Data

On Streamlit Cloud, the `/tmp` directory is temporary and resets when the app restarts.

**Options for persistent data storage**:

1. **SQLite Database in Repo** (Simple, but not ideal)
   - Commit `laveg.sqlite` to git
   - App will read/write to it
   - Data persists across deployments
   - ⚠️ Git history will grow large with db updates

2. **Google Drive / OneDrive Integration** (Advanced)
   - Use `pydrive` or `microsoft-graph-api` to fetch files
   - Requires OAuth setup

3. **AWS S3 / Cloud Storage** (Professional)
   - Upload CSV files to S3
   - App fetches them from cloud
   - Database stored in DynamoDB or RDS

4. **User Uploads** (Simplest for Sharing)
   - Implement file upload widget in UI
   - Users upload their own CSV files
   - Database is session-specific or stored in repo

## Step 4: Share with Others

Once deployed, share the app URL with others:
- **Public link**: `https://your-app-name.streamlit.app`
- They can import their own CSV files using the "Scan for CSV files" button
- All analysis is done in-browser

## Local Testing Before Deployment

Test the app locally to make sure it works:

```bash
cd /workspace/laveg_app
python -m streamlit run _app/app.py
```

Visit `http://localhost:8501` to test.

## Troubleshooting

### App fails to deploy
- Check `requirements.txt` for all dependencies
- Look at deployment logs in Streamlit Cloud dashboard
- Ensure `_app/app.py` exists and is syntactically correct

### App works locally but crashes on cloud
- Likely a path issue (`/tmp` vs absolute paths)
- Check `.streamlit/config.toml` and environment setup
- Review app logs in the dashboard

### Database not persisting
- Temporary `/tmp` directory resets
- Consider committing SQLite to git or use cloud storage

## Next Steps

1. **Add file upload to UI** — let users upload CSV files instead of scanning local paths
2. **Document for users** — create a user guide for analyzing sprint data
3. **Add more analysis features** — e.g., export reports, statistical comparisons, etc.

## Resources

- Streamlit Cloud: https://streamlit.io/cloud
- Streamlit Secrets: https://docs.streamlit.io/deploy/streamlit-cloud/deploy-your-app/secrets-management
- SprintScope README: [README.md](README.md)
