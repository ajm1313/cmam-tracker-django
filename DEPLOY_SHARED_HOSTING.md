# Deploying CMAM Tracker on Shared Hosting (nutri.pharn.org)
## Step-by-Step Guide for First Timers — No Terminal Required

---

## BEFORE YOU START — Check These With Stormerhost Support

Contact stormerhost.com support and ask:
> "Do your hosting plans support Django/Python apps via cPanel's **Setup Python App** feature (Phusion Passenger)?"

You need a plan that includes:
- ✅ Python 3.11 support (via cPanel Python App)
- ✅ MySQL database
- ✅ File Manager access
- ✅ Custom subdomain support

---

## PHASE 1 — Prepare the .env File (Do This on Your Computer First)

1. Find the file `.env.production` in this project folder
2. Make a **copy** of it and rename the copy to `.env`
3. Open `.env` in Notepad and fill in every value:

```
SECRET_KEY=        ← Go to https://djecrety.ir/ and copy the generated key
DEBUG=True         ← Set to True NOW — you will change it to False in Phase 6
ALLOWED_HOSTS=nutri.pharn.org,www.nutri.pharn.org

DB_NAME=           ← Your cPanel username + _cmam  (e.g. pharnorg_cmam)
DB_USER=           ← Your cPanel username + _cmamuser  (e.g. pharnorg_cmamuser)
DB_PASSWORD=       ← The password you set for the DB user
DB_HOST=localhost
DB_PORT=3306

SETUP_SECRET=      ← Make up any password (e.g. MySetup@2026) — you'll use this once
ADMIN_PASSWORD=    ← Password for the admin account (e.g. Admin@2026!)
```

4. Save the `.env` file. **Never share this file — it contains your passwords.**

---

## PHASE 2 — Create the Deployment ZIP

On your computer:

1. Open the project folder (`cmam-tracker-django`)
2. Select ALL files and folders **except**:
   - `__pycache__` folders anywhere
   - `.git` folder
   - `*.pyc` files
   - `docker-compose.yml`, `Dockerfile`, `docker-entrypoint.sh`
   - `docker-start.bat`, `docker-stop.bat`
3. Make sure to **include**:
   - ✅ `.env` (the filled-in one you just created — NOT `.env.production`)
   - ✅ `staticfiles/` folder (pre-built static files)
   - ✅ `passenger_wsgi.py`
   - ✅ `.htaccess`
   - ✅ `deploy/` folder
   - ✅ All `apps/` migration files
4. Zip everything into `cmam-tracker.zip`

---

## PHASE 3 — Set Up on cPanel (stormerhost.com)

### Step 3.1 — Log into cPanel
- Go to your hosting control panel URL (stormerhost will email this to you)
- Log in with your credentials

### Step 3.2 — Create a Subdomain
1. In cPanel → **Domains** → **Subdomains** (or just "Domains")
2. Create subdomain: `nutri` under `pharn.org`
3. Document root: `/public_html/nutri` (or accept the default suggestion)
4. Click **Create**

### Step 3.3 — Create MySQL Database
1. cPanel → **Databases** → **MySQL Databases**
2. Under "Create New Database" → type `cmam` → click **Create Database**
   - cPanel will auto-prefix it with your username → e.g. `pharnorg_cmam`
   - **Write down the full name shown**
3. Under "MySQL Users" → Create New User:
   - Username: `cmamuser` → cPanel prefixes it → e.g. `pharnorg_cmamuser`
   - Password: choose a strong password → **write it down**
4. Under "Add User To Database":
   - User: select `pharnorg_cmamuser`
   - Database: select `pharnorg_cmam`
   - Click **Add** → on the next screen select **ALL PRIVILEGES** → click **Make Changes**

### Step 3.4 — Upload the ZIP File
1. cPanel → **File Manager**
2. Navigate to `/public_html/nutri/` (the subdomain folder you created)
3. Click **Upload** (top toolbar)
4. Upload your `cmam-tracker.zip`
5. Go back to `/public_html/nutri/` → right-click the ZIP → **Extract**
6. If files extracted into a subfolder (like `cmam-tracker-django/`), move them up:
   - Select all files inside that subfolder
   - Move them to `/public_html/nutri/`
   - Delete the now-empty subfolder
7. Final structure should look like:
   ```
   /public_html/nutri/
   ├── .env
   ├── .htaccess
   ├── passenger_wsgi.py
   ├── manage.py
   ├── requirements.txt
   ├── config/
   ├── apps/
   ├── templates/
   ├── staticfiles/
   ├── deploy/
   └── ...
   ```

### Step 3.5 — Set Up Python App in cPanel
1. cPanel → **Software** → **Setup Python App**
2. Click **Create Application**
3. Fill in:
   - **Python version**: `3.11` (pick the closest available)
   - **Application root**: `public_html/nutri`
   - **Application URL**: `nutri.pharn.org`
   - **Application startup file**: `passenger_wsgi.py`
   - **Application entry point**: `application`
4. Click **Create**
5. You will see a command like:
   ```
   source /home/pharnorg/virtualenv/nutri/3.11/bin/activate
   ```
   **Copy this path** — you need it in the next step

### Step 3.6 — Install Python Packages (via cPanel UI — No Terminal)
Still in **Setup Python App**, with your app selected:

1. Find the **"Configuration files"** or **"pip install"** section
2. In the text box for packages, paste the contents of `requirements.txt`:
   ```
   Django==5.0.1
   djangorestframework==3.14.0
   django-cors-headers==4.3.1
   mysqlclient==2.2.1
   python-decouple==3.8
   Pillow==10.2.0
   whitenoise==6.6.0
   djangorestframework-simplejwt==5.3.1
   django-filter==23.5
   pytz==2024.1
   ```
3. Click **Run pip install** or **Save** (the button label varies by cPanel version)
4. Wait for the installation to complete (may take 2–5 minutes)

---

## PHASE 4 — Initialize the Database (One Click From Your Browser)

1. Open your browser and go to:
   ```
   https://nutri.pharn.org/deploy-setup/?secret=YOUR_SETUP_SECRET
   ```
   Replace `YOUR_SETUP_SECRET` with the value you put in the `.env` file

2. You should see a page saying:
   - ✔ Migrations applied successfully
   - ✔ Static files collected
   - ✔ Superuser created: admin@cmam.com / Admin@2026!

3. If you see a **500 error instead**, check:
   - The `.env` file is in `/public_html/nutri/` (not inside a subfolder)
   - The DB name/user in `.env` exactly match what cPanel created (including the username prefix)
   - The Python app was restarted in cPanel

---

## PHASE 5 — Final Steps

### Step 5.1 — Restart the App
After setup completes:
1. cPanel → **Setup Python App** → click **Restart** on your app

### Step 5.2 — Test the App (HTTP first)
1. Open `http://nutri.pharn.org` → you should see the login page
2. Log in with:
   - Email: `admin@cmam.com`
   - Password: `Admin@2026!` (or whatever you set in `ADMIN_PASSWORD`)

### Step 5.3 — Enable SSL (HTTPS)
1. cPanel → **Security** → **Let's Encrypt SSL** (or SSL/TLS)
2. Select `nutri.pharn.org` → click **Issue/Renew**
3. Wait ~2 minutes → SSL is active
4. Test: open `https://nutri.pharn.org` — it should load with a padlock

---

## PHASE 6 — Security Hardening (IMPORTANT — Do After SSL Works)

### Step 6.1 — Switch to production mode
1. In cPanel **File Manager** → go to `/public_html/nutri/`
2. Click on `.env` → **Edit**
3. Change `DEBUG=True` → `DEBUG=False`
4. Save the file

### Step 6.2 — Remove the setup script
1. In **File Manager** → go to `/public_html/nutri/deploy/`
2. Delete `setup_view.py`
3. In `/public_html/nutri/config/urls.py`, click **Edit** and delete these two lines:
   ```python
   from deploy.setup_view import run_setup
   path('deploy-setup/', run_setup, name='deploy_setup'),
   ```
4. Save the file

### Step 6.3 — Restart
1. cPanel → **Setup Python App** → click **Restart**
2. Open `https://nutri.pharn.org` — app is now fully secured

⚠️ **Why this order matters**: `DEBUG=False` enables forced HTTPS redirect. You must have SSL working before enabling it, otherwise the app becomes unreachable.

---

## TROUBLESHOOTING

| Problem | Fix |
|--------|-----|
| 500 Internal Server Error | Check cPanel → **Errors** log; check `.env` DB credentials |
| "Module not found" error | Packages not installed — redo Step 3.6 |
| Static files (CSS/images) not loading | Make sure `staticfiles/` folder was included in ZIP |
| "Table doesn't exist" | Re-run the setup URL in Phase 4 |
| Login shows "Invalid email or password" | Confirm `ADMIN_PASSWORD` in `.env` matches what you used |
| `.env` values not loading | Make sure the file is named exactly `.env` (not `.env.txt`) |

---

## Need Help?

- Check cPanel's **Error Logs** (cPanel → Metrics → Errors)
- Check `/public_html/nutri/logs/django.log` in File Manager
