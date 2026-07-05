# CMAM Tracker - Django Version

A Django-based Community-based Management of Severe Acute Malnutrition (CMAM) tracking system. This is a complete carbon copy of the Laravel CMAM Tracker, rebuilt using Python Django framework with Docker deployment.

## Features

### Core Functionality
- **User Management**: Hierarchical role-based access control (National, Regional, District, Sub-District, Facility levels)
- **Facility Management**: Track OPC (Outpatient Care) and IPC (Inpatient Care) facilities
- **Case Management**: 
  - OPC Registration and Visit tracking
  - SAM (Severe Acute Malnutrition) cases
  - MAM (Moderate Acute Malnutrition) cases
  - IPC cases
- **Inventory Management**: 
  - Track inventory items (RUTF, RUSF, CSB, Oil, Medicines, Supplies)
  - Stock levels by location
  - Stock movements (IN, OUT, TRANSFER, CONSUMPTION, ADJUSTMENT)
- **Location Hierarchy**: Regions → Districts → Sub-Districts → Facilities
- **REST API**: Full REST API with JWT authentication

### Technical Stack
- **Framework**: Django 5.0.1
- **API**: Django REST Framework 3.14.0
- **Database**: MySQL 8.0
- **Authentication**: JWT (Simple JWT)
- **Web Server**: Gunicorn
- **Containerization**: Docker & Docker Compose

## Project Structure

```
cmam-tracker-django/
├── apps/
│   ├── api/          # REST API endpoints
│   ├── cases/        # Case management (SAM/MAM/IPC, OPC)
│   ├── core/         # Base models and utilities
│   ├── facilities/   # Facility management
│   ├── inventory/    # Inventory and stock management
│   ├── locations/    # Geographic hierarchy
│   └── users/        # User authentication and roles
├── config/           # Django project configuration
├── templates/        # HTML templates
├── static/           # Static files (CSS, JS, images)
├── media/            # User uploaded files
├── logs/             # Application logs
├── Dockerfile        # Docker configuration
├── docker-compose.yml
├── requirements.txt  # Python dependencies
└── manage.py         # Django management script
```

## Installation & Setup

### Prerequisites
- Docker and Docker Compose installed
- Ports 8083 (web), 3309 (MySQL), 8084 (phpMyAdmin) available

### Quick Start with Docker

1. **Clone/Navigate to project directory**
   ```bash
   cd c:\wamp64\www\cmam-tracker-django
   ```

2. **Build and start containers**
   ```bash
   docker-compose up -d --build
   ```

3. **Wait for initialization** (migrations, superuser creation)
   ```bash
   docker-compose logs -f web
   ```

4. **Access the application**
   - Main App: http://localhost:8083
   - Admin Panel: http://localhost:8083/admin
   - phpMyAdmin: http://localhost:8084
   - API Docs: http://localhost:8083/api/v1/system/info/

5. **Default Credentials**
   - Email: `admin@cmam.com`
   - Password: `admin123`

### Manual Setup (Without Docker)

1. **Create virtual environment**
   ```bash
   python -m venv venv
   venv\Scripts\activate  # Windows
   source venv/bin/activate  # Linux/Mac
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   copy .env.example .env
   # Edit .env with your database credentials
   ```

4. **Run migrations**
   ```bash
   python manage.py migrate
   ```

5. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run development server**
   ```bash
   python manage.py runserver 8083
   ```

## Docker Commands

### Start services
```bash
docker-compose up -d
```

### Stop services
```bash
docker-compose down
```

### View logs
```bash
docker-compose logs -f web
```

### Restart a service
```bash
docker-compose restart web
```

### Execute Django commands
```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py createsuperuser
docker-compose exec web python manage.py collectstatic
```

### Access database
```bash
docker-compose exec db mysql -u cmam_user_django -p cmam_tracker_django
```

## API Endpoints

### Authentication
- `POST /api/v1/login/` - User login
- `POST /api/v1/logout/` - User logout
- `GET /api/v1/profile/` - Get user profile

### Inventory
- `GET /api/v1/inventory/items/` - List inventory items
- `GET /api/v1/inventory/facility/{id}/stock/` - Get facility stock
- `POST /api/v1/inventory/consumption/` - Record consumption
- `GET /api/v1/inventory/facility/{id}/movements/` - Get stock movements

### Facilities
- `GET /api/v1/facilities/` - List accessible facilities

### System
- `GET /api/v1/system/info/` - System information
- `GET /api/health/` - Health check

## Database Models

### Core Models
- **User**: Custom user model with hierarchical access
- **Role**: System roles (National, Regional, District, Sub-District, Facility)
- **UserRole**: User-role-location assignments

### Location Models
- **Region**: Top-level geographic division
- **District**: Second-level division
- **SubDistrict**: Third-level division
- **Facility**: Health facilities (OPC/IPC)

### Case Models
- **Patient**: Patient records
- **OpcRegistration**: OPC patient registration
- **OpcVisit**: Follow-up visits
- **SamCase**: Severe Acute Malnutrition cases
- **MamCase**: Moderate Acute Malnutrition cases
- **IpcCase**: Inpatient Care cases

### Inventory Models
- **InventoryItem**: Items (RUTF, medicines, supplies)
- **StockLevel**: Stock quantities by location
- **StockMovement**: Stock transactions

## Configuration

### Environment Variables (.env)
```
SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_ENGINE=django.db.backends.mysql
DB_NAME=cmam_tracker_django
DB_USER=cmam_user_django
DB_PASSWORD=cmam_password_django
DB_HOST=db
DB_PORT=3306
```

### Docker Ports
- **8083**: Django application
- **3309**: MySQL database
- **8084**: phpMyAdmin

## Development

### Running Tests
```bash
python manage.py test
```

### Create Migrations
```bash
python manage.py makemigrations
python manage.py migrate
```

### Shell Access
```bash
python manage.py shell
```

### Create Admin User
```bash
python manage.py createsuperuser
```

## Differences from Laravel Version

### Same Functionality
✅ All models with same fields and relationships
✅ Hierarchical access control system
✅ REST API with JWT authentication
✅ Inventory management with stock tracking
✅ Case management (SAM/MAM/IPC/OPC)
✅ Docker deployment
✅ Database structure

### Django-Specific Features
- Django Admin interface (built-in)
- Django ORM (instead of Eloquent)
- Django REST Framework (instead of Laravel API)
- Python-based (instead of PHP)
- Gunicorn web server (instead of Apache/nginx)
- Django migrations (instead of Laravel migrations)

## Troubleshooting

### Database Connection Issues
```bash
# Check database is running
docker-compose ps

# Check database logs
docker-compose logs db

# Restart database
docker-compose restart db
```

### Permission Issues
```bash
# Fix permissions in container
docker-compose exec web chmod -R 755 /app/media /app/staticfiles /app/logs
```

### Port Already in Use
```bash
# Check what's using the port
netstat -ano | findstr :8083

# Kill the process or change port in docker-compose.yml
```

## Production Deployment

### Security Checklist
- [ ] Set `DEBUG=False`
- [ ] Generate secure `SECRET_KEY`
- [ ] Use strong database passwords
- [ ] Enable HTTPS
- [ ] Configure ALLOWED_HOSTS properly
- [ ] Set up proper logging
- [ ] Configure email settings
- [ ] Set up backup strategy

### Environment Setup
1. Update `.env` file with production values
2. Set `DEBUG=False`
3. Configure domain in `ALLOWED_HOSTS`
4. Set up SSL/TLS certificates
5. Configure email backend
6. Set up monitoring and logging

## Support

For issues or questions:
- Check logs: `docker-compose logs -f web`
- Access Django shell: `docker-compose exec web python manage.py shell`
- Check database: Access phpMyAdmin at http://localhost:8084

## License

This project mirrors the original Laravel CMAM Tracker functionality.

## Version

- Django Version: 1.0.0
- Based on: Laravel CMAM Tracker
- Last Updated: December 2024
