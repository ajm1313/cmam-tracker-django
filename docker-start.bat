@echo off
echo ========================================
echo CMAM Tracker Django - Docker Startup
echo ========================================
echo.

echo [1/4] Checking Docker...
docker --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker is not installed or not running!
    echo Please install Docker Desktop and start it.
    pause
    exit /b 1
)
echo Docker is available.
echo.

echo [2/4] Building Docker images (this may take a few minutes on first run)...
docker-compose build
if errorlevel 1 (
    echo ERROR: Docker build failed!
    pause
    exit /b 1
)
echo Build completed successfully.
echo.

echo [3/4] Starting containers...
docker-compose up -d
if errorlevel 1 (
    echo ERROR: Failed to start containers!
    pause
    exit /b 1
)
echo Containers started successfully.
echo.

echo [4/4] Waiting for initialization (30 seconds)...
timeout /t 30 /nobreak >nul
echo.

echo ========================================
echo CMAM Tracker is now running!
echo ========================================
echo.
echo Access the application at:
echo   - Main App:     http://localhost:8083
echo   - Admin Panel:  http://localhost:8083/admin
echo   - phpMyAdmin:   http://localhost:8084
echo   - API Health:   http://localhost:8083/health/
echo.
echo Default Login:
echo   Email:    admin@cmam.com
echo   Password: admin123
echo.
echo To view logs:    docker-compose logs -f web
echo To stop:         docker-compose down
echo ========================================
echo.

start http://localhost:8083
pause
