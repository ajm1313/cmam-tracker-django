# CMAM Tracker Django - Quick Start

## 🚀 Fastest Way to Get Started

### Option 1: Windows Batch Script (Recommended for Windows)

1. **Double-click** `docker-start.bat`
2. **Wait** for the build and startup (2-3 minutes first time)
3. **Access** the application at http://localhost:8083
4. **Login** with:
   - Email: `admin@cmam.com`
   - Password: `admin123`

### Option 2: Command Line

```bash
# Navigate to project directory
cd c:\wamp64\www\cmam-tracker-django

# Start the application
docker-compose up -d --build

# Wait 30 seconds for initialization
# Then open http://localhost:8083
```

## 📌 Access Points

| Service | URL | Credentials |
|---------|-----|-------------|
| **Main Application** | http://localhost:8083 | admin@cmam.com / admin123 |
| **Admin Panel** | http://localhost:8083/admin | admin@cmam.com / admin123 |
| **phpMyAdmin** | http://localhost:8084 | root / root_password_django |
| **API Health Check** | http://localhost:8083/health/ | No auth required |

## ✅ Verify Installation

### Check if services are running:
```bash
docker-compose ps
```

You should see:
- `cmam-tracker-django-web` - Up
- `cmam-tracker-django-db` - Up (healthy)
- `cmam-tracker-django-phpmyadmin` - Up

### Check logs:
```bash
docker-compose logs -f web
```

Look for: `Listening at: http://0.0.0.0:8000`

## 🛠️ Common Commands

### Start
```bash
docker-compose up -d
```

### Stop
```bash
docker-compose down
```

### View Logs
```bash
# All services
docker-compose logs -f

# Web service only
docker-compose logs -f web
```

### Restart
```bash
docker-compose restart web
```

## 📱 Using the Application

### 1. Login
- Go to http://localhost:8083
- Enter credentials: `admin@cmam.com` / `admin123`

### 2. Explore Dashboard
- View statistics (Users, Facilities, Cases)
- Navigate using top menu

### 3. Key Features
- **Users**: Manage system users and roles
- **Facilities**: Track health facilities
- **Inventory**: Manage stock and supplies
- **Cases**: Register and track SAM/MAM/IPC cases

## 🔧 Troubleshooting

### Port Already in Use
If port 8083 is busy:
1. Edit `docker-compose.yml`
2. Change `"8083:8000"` to `"8085:8000"`
3. Run `docker-compose up -d`
4. Access at http://localhost:8085

### Can't Connect to Database
```bash
docker-compose restart db
docker-compose logs db
```

Wait for message: `ready for connections`

### Reset Everything
```bash
docker-compose down -v
docker-compose up -d --build
```

## 📚 Next Steps

1. **Create Users**: Admin Panel → Users → Add User
2. **Add Locations**: Admin Panel → Regions/Districts
3. **Register Facilities**: Facilities → Create Facility
4. **Add Inventory Items**: Inventory → Create Item
5. **Start Tracking**: Cases → New Registration

## 🆘 Need Help?

Check detailed guides:
- **Full Setup**: See `SETUP_GUIDE.md`
- **Documentation**: See `README.md`

View application logs:
```bash
docker-compose logs -f web
```

Check database:
- Visit http://localhost:8084
- Login: root / root_password_django

## ⚡ Pro Tips

### Speed Up Startup
After first build, startup takes only 10-15 seconds:
```bash
docker-compose up -d
```

### API Testing
```bash
# Get token
curl -X POST http://localhost:8083/api/v1/login/ \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"admin@cmam.com\",\"password\":\"admin123\"}"

# Use token
curl http://localhost:8083/api/v1/facilities/ \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Django Shell Access
```bash
docker-compose exec web python manage.py shell
```

## 🎯 Quick Checklist

- [ ] Docker installed and running
- [ ] Ports 8083, 3309, 8084 available
- [ ] Run `docker-compose up -d --build`
- [ ] Wait 30 seconds
- [ ] Access http://localhost:8083
- [ ] Login with admin@cmam.com / admin123
- [ ] ✅ You're ready to go!

---

**Application**: CMAM Tracker Django
**Port**: 8083
**Default User**: admin@cmam.com / admin123
**Documentation**: README.md
