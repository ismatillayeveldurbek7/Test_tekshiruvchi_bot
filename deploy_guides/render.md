# Deploy Telegram OMR Bot on Render

Render manages containerized services securely. Here is how to configure your Telegram bot as a **Background Worker**.

## Steps:
1. **GitHub Setup**:
   Upload all sources to a public/private GitHub repository.

2. **Render Workspace Setup**:
   - Sign up/Login to the [Render Console](https://render.com/).
   - Click **New +** and select **Background Worker**.
   - Connect your GitHub repository.

3. **Background Worker Settings**:
   - **Language**: `Python`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python bot.py`

4. **Add Environment Settings**:
   Under **Environment**, click **Add Environment Variable**:
   - `BOT_TOKEN`: your_api_token
   - `ADMIN_IDS`: your_telegram_numeric_id
   - `DATABASE_PATH`: `/opt/render/project/src/sqlite_omr_db.sqlite` (to persist logs in build directories)

5. **Deploy**:
   - Click **Create Background Worker** and wait for logs to report `Telegram OMR Test Checker Bot started successfully!`
