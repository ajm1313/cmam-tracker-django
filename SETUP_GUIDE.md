# CMAM Tracker Django - Complete Setup Guide

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Installation Steps](#installation-steps)
3. [Initial Configuration](#initial-configuration)
4. [Running the Application](#running-the-application)
5. [Accessing the System](#accessing-the-system)
6. [Common Issues](#common-issues)

## Prerequisites

### Required Software
- **Docker Desktop** (Windows/Mac) or **Docker Engine** (Linux)
- **Docker Compose** (usually included with Docker Desktop)
- **Git** (optional, for version control)

### System Requirements
- **RAM**: Minimum 4GB, Recommended 8GB
- **Disk Space**: At least 5GB free space
- **Ports**: 8083, 3309, 8084 must be available

### Check Prerequisites
```bash
# Check Docker version
docker --version
# Should show: Docker version 20.x.x or higher

# Check Docker Compose version
docker-compose --version
# Should show: docker-compose version 1.x.x or higher

# Check if Docker is running
docker ps
# Should list running containers (may be empty)
```

## Installation Steps

### Step 1: Navigate to Project Directory
```bash
cd c:\wamp64\www\cmam-tracker-django
```

### Step 2: Verify Files
Ensure these files exist:
- `Dockerfile`
- `docker-compose.yml`
- `requirements.txt`
- `manage.py`
- `docker-entrypoint.sh`

### Step 3: Build Docker Images
```bash
docker-compose build
```

**Expected Output:**
```
Building web
Step 1/X : FROM python:3.11-slim
...
Successfully built xxxxx
Successfully tagged cmam-tracker-django-web:latest
```

**Build Time**: 3-5 minutes (first time)

### Step 4: Start the Services
```bash
docker-compose up -d
```

**Expected Output:**
```
Creating network "cmam-tracker-django_cmam-django-network" ... done
Creating volume "cmam-tracker-django_db-data-django" ... done
Creating cmam-tracker-django-db ... done
Creating cmam-tracker-django-web ... done
Creating cmam-tracker-django-phpmyadmin ... done
```

### Step 5: Wait for Initialization
The first startup takes 1-2 minutes for:
- Database initialization
- Running migrations
- Creating superuser
- Collecting static files

**Monitor Progress:**
```bash
docker-compose logs -f web
```

**Look for these messages:**
```
Database is ready!
Running migrations...
Operations to perform:
  Apply all migrations: admin, auth, ...
Running migrations:
  Applying contenttypes.0001_initial... OK
  ...
Creating superuser...
Superuser created: admin@cmam.com / admin123
Starting Gunicorn...
[INFO] Listening at: http://0.0.0.0:8000
```

**Press `Ctrl+C` to stop viewing logs** (container continues running)

## Initial Configuration

### Step 1: Verify Services are Running
```bash
docker-compose ps
```

**Expected Output:**
```
Name                          State          Ports
-------------------------------------------------------------------------
cmam-tracker-django-web       Up        0.0.0.0:8083->8000/tcp
cmam-tracker-django-db        Up (healthy) 0.0.0.0:3309->3306/tcp
cmam-tracker-django-phpmyadmin Up        0.0.0.0:8084->80/tcp
```

### Step 2: Check Service Health
```bash
# Check web service
curl http://localhost:8083/health/

# Should return: {"status":"healthy","timestamp":"...","service":"CMAM Tracker API"}
```

### Step 3: Access Django Admin
1. Open browser: http://localhost:8083/admin
2. Login with:
   - **Username**: admin@cmam.com
   - **Password**: admin123

**If login successful**, you're ready to use the system!

## Running the Application

### Daily Operations

**Start the System:**
```bash
docker-compose up -d
```

**Stop the System:**
```bash
docker-compose down
```

**Restart a Service:**
```bash
docker-compose restart web
```

**View Logs:**
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f web
docker-compose logs -f db
```

### Database Operations

**Access MySQL Shell:**
```bash
docker-compose exec db mysql -u cmam_user_django -pcmam_password_django cmam_tracker_django
```

**Backup Database:**
```bash
docker-compose exec db mysqldump -u cmam_user_django -pcmam_password_django cmam_tracker_django > backup.sql
```

**Restore Database:**
```bash
docker-compose exec -T db mysql -u cmam_user_django -pcmam_password_django cmam_tracker_django < backup.sql
```

### Django Management Commands

**Run Migrations:**
```bash
docker-compose exec web python manage.py migrate
```

**Create Superuser:**
```bash
docker-compose exec web python manage.py createsuperuser
```

**Collect Static Files:**
```bash
docker-compose exec web python manage.py collectstatic --noinput
```

**Open Django Shell:**
```bash
docker-compose exec web python manage.py shell
```

## Accessing the System

### Web Interfaces

| Service | URL | Credentials |
|---------|-----|-------------|
| **Main Application** | http://localhost:8083 | admin@cmam.com / admin123 |
| **Django Admin** | http://localhost:8083/admin | admin@cmam.com / admin123 |
| **phpMyAdmin** | http://localhost:8084 | root / root_password_django |
| **API Health** | http://localhost:8083/health/ | No auth required |

### API Access

**Get JWT Token:**
```bash
curl -X POST http://localhost:8083/api/v1/login/ \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@cmam.com","password":"admin123"}'
```

**Use Token:**
```bash
curl -X GET http://localhost:8083/api/v1/profile/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## Common Issues

### Issue 1: Port Already in Use

**Symptom:**
```
Error: bind: address already in use
```

**Solution:**
```bash
# Find what's using port 8083
netstat -ano | findstr :8083

# Option 1: Kill the process
taskkill /PID <process_id> /F

# Option 2: Change port in docker-compose.yml
# Change "8083:8000" to "8085:8000"
```

### Issue 2: Database Connection Failed

**Symptom:**
```
django.db.utils.OperationalError: (2003, "Can't connect to MySQL server")
```

**Solution:**
```bash
# Check database status
docker-compose ps db

# Restart database
docker-compose restart db

# Check database logs
docker-compose logs db

# Wait for "ready for connections" message
```

### Issue 3: Migrations Not Applied

**Symptom:**
```
no such table: users
```

**Solution:**
```bash
# Run migrations
docker-compose exec web python manage.py migrate

# If error persists, reset database
docker-compose down -v
docker-compose up -d
```

### Issue 4: Static Files Not Loading

**Symptom:**
```
CSS/JS files not loading, page looks broken
```

**Solution:**
```bash
# Collect static files
docker-compose exec web python manage.py collectstatic --noinput

# Restart web service
docker-compose restart web
```

### Issue 5: Permission Denied

**Symptom:**
```
PermissionError: [Errno 13] Permission denied
```

**Solution:**
```bash
# Fix permissions
docker-compose exec web chmod -R 755 /app/media /app/staticfiles /app/logs

# Or recreate containers
docker-compose down
docker-compose up -d
```

### Issue 6: Can't Login

**Symptom:**
```
Invalid credentials
```

**Solution:**
```bash
# Reset admin password
docker-compose exec web python manage.py shell

# In shell:
from apps.users.models import User
user = User.objects.get(email='admin@cmam.com')
user.set_password('admin123')
user.save()
exit()
```

### Issue 7: Docker Build Fails

**Symptom:**
```
ERROR: failed to solve: process "/bin/sh -c pip install..." did not complete successfully
```

**Solution:**
```bash
# Clear Docker cache
docker system prune -a

# Rebuild
docker-compose build --no-cache
docker-compose up -d
```

## Performance Optimization

### Increase Workers
Edit `docker-entrypoint.sh`:
```bash
# Change from 4 to 8 workers
--workers 8 \
```

### Allocate More RAM to Docker
Docker Desktop → Settings → Resources → Memory: Increase to 4-8GB

### Enable Database Query Cache
Add to `docker-compose.yml` under db environment:
```yaml
MYSQL_QUERY_CACHE_SIZE: 67108864
```

## Next Steps

After successful setup:

1. **Create Additional Users**: Use Django Admin or `/admin/users/`
2. **Add Locations**: Create Regions, Districts, Sub-Districts
3. **Add Facilities**: Register health facilities
4. **Configure Inventory**: Add inventory items
5. **Start Using**: Register patients and track cases

## Support

**Check Application Status:**
```bash
docker-compose ps
docker-compose logs -f web
```

**Reset Everything:**
```bash
docker-compose down -v
docker-compose up -d --build
```

**Get Help:**
- Check logs: `docker-compose logs -f`
- Access Django shell: `docker-compose exec web python manage.py shell`
- Check database: Visit http://localhost:8084
