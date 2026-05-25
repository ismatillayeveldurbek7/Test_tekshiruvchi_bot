# Deploy Telegram OMR Bot on Railway

Railway is a great cloud platform for running persistent python daemons.

## Steps:
1. **Prepare GitHub Repository**:
   - Pack the files of the ZIP generated here into a Git source repository.
   - Verify that `requirements.txt` is at the project root directory.

2. **Setup Railway Project**:
   - Create a free account on [Railway.app](https://railway.app/).
   - Click **New Project** -> **Deploy from GitHub repo**.
   - Authenticate with GitHub and select your repository.

3. **Configure Environment Variables**:
   In your Railway service panel, navigate to the **Variables** tab and add:
   - `BOT_TOKEN`: Your secret Telegram bot token from @BotFather.
   - `ADMIN_IDS`: Your personal numeric Telegram userID (e.g., `59091811`).
   - `DATABASE_PATH`: Set to `sqlite_omr_db.sqlite`.

4. **Verify Persistent Volumes (Optional but Recommended)**:
   By default, containers can be restarted, which wipes the local SQLite database. 
   - Add a volume mount to path `/app/data` to persist data permanently.
   - Update your container settings environment with `DATABASE_PATH=/app/data/sqlite_omr_db.sqlite`.

5. **Deploy**:
   Railway auto-detects Python and executes `python bot.py` automatically!
