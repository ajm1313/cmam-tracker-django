"""
Core middleware for CMAM Tracker
Includes rate limiting and audit logging
"""
import time
import json
from django.http import JsonResponse
from django.conf import settings
from django.utils.deprecation import MiddlewareMixin
from apps.users.models import AuditLog


class HealthCheckMiddleware:
    """Bypass SecurityMiddleware SSL redirect for healthcheck endpoint."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/health/':
            return JsonResponse({'status': 'healthy'})
        return self.get_response(request)


class RateLimitMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware for API endpoints.
    Tracks requests per IP and per user.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # In-memory store for rate limiting (use Redis in production)
        self.ip_requests = {}
        self.user_requests = {}
        
    def __call__(self, request):
        # Skip rate limiting for non-API paths
        if not request.path.startswith('/api/'):
            return self.get_response(request)
        
        # Get client identifier
        ip_address = self._get_client_ip(request)
        user_id = request.user.id if hasattr(request, 'user') and request.user.is_authenticated else None
        
        # Check rate limits
        if self._is_rate_limited(ip_address, user_id):
            return JsonResponse({
                'success': False,
                'error': 'Rate limit exceeded. Please try again later.',
                'retry_after': 60
            }, status=429)
        
        # Record request
        self._record_request(ip_address, user_id)
        
        return self.get_response(request)
    
    def _get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', 'unknown')
    
    def _is_rate_limited(self, ip_address, user_id):
        """Check if request should be rate limited"""
        now = time.time()
        window = 60  # 1 minute window
        
        # IP-based rate limit: 100 requests per minute
        ip_key = f"ip:{ip_address}"
        ip_count = self._get_request_count(self.ip_requests, ip_key, now, window)
        if ip_count > 100:
            return True
        
        # User-based rate limit: 200 requests per minute for authenticated users
        if user_id:
            user_key = f"user:{user_id}"
            user_count = self._get_request_count(self.user_requests, user_key, now, window)
            if user_count > 200:
                return True
        
        return False
    
    def _get_request_count(self, store, key, now, window):
        """Get count of requests in the time window"""
        if key not in store:
            return 0
        
        # Clean old entries
        store[key] = [t for t in store[key] if now - t < window]
        return len(store[key])
    
    def _record_request(self, ip_address, user_id):
        """Record request timestamp"""
        now = time.time()
        
        ip_key = f"ip:{ip_address}"
        if ip_key not in self.ip_requests:
            self.ip_requests[ip_key] = []
        self.ip_requests[ip_key].append(now)
        
        if user_id:
            user_key = f"user:{user_id}"
            if user_key not in self.user_requests:
                self.user_requests[user_key] = []
            self.user_requests[user_key].append(now)


class AuditLogMiddleware(MiddlewareMixin):
    """
    Middleware to log user actions for audit purposes.
    Logs create, update, delete operations.
    """
    
    AUDIT_METHODS = ['POST', 'PUT', 'PATCH', 'DELETE']
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Only log API requests
        if not request.path.startswith('/api/'):
            return response
        
        # Only log modifying operations
        if request.method not in self.AUDIT_METHODS:
            return response
        
        # Only log authenticated users
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return response
        
        # Skip logging for certain endpoints
        if self._should_skip_logging(request):
            return response
        
        # Log the action
        self._log_action(request, response)
        
        return response
    
    def _should_skip_logging(self, request):
        """Determine if request should be skipped"""
        # Skip login/logout for now (too noisy)
        if '/login/' in request.path or '/logout/' in request.path:
            return True
        
        # Skip health checks
        if '/health/' in request.path:
            return True
        
        # Skip preview operations
        if '/preview/' in request.path:
            return True
        
        return False
    
    def _log_action(self, request, response):
        """Log the user action"""
        try:
            # Get action description based on path and method
            action = self._get_action_description(request)
            
            # Get resource type from path
            resource_type = self._get_resource_type(request.path)
            
            # Try to get resource ID from path
            resource_id = self._get_resource_id(request.path)
            
            # Get IP address
            ip_address = self._get_client_ip(request)
            
            # Get user agent
            user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
            
            # Create audit log entry
            AuditLog.objects.create(
                user=request.user,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details=self._get_request_details(request)
            )
        except Exception as e:
            # Log error but don't break the request
            print(f"Audit log error: {e}")
    
    def _get_action_description(self, request):
        """Get human-readable action description"""
        method_map = {
            'POST': 'create',
            'PUT': 'update',
            'PATCH': 'update',
            'DELETE': 'delete'
        }
        return method_map.get(request.method, request.method.lower())
    
    def _get_resource_type(self, path):
        """Extract resource type from URL path"""
        parts = path.strip('/').split('/')
        if len(parts) >= 2:
            return parts[1]  # e.g., 'v1/cases/' -> 'cases'
        return 'unknown'
    
    def _get_resource_id(self, path):
        """Try to extract resource ID from URL path"""
        parts = path.strip('/').split('/')
        for part in parts:
            try:
                return int(part)
            except ValueError:
                continue
        return None
    
    def _get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()[:45]
        return request.META.get('REMOTE_ADDR', 'unknown')[:45]
    
    def _get_request_details(self, request):
        """Get request details for logging"""
        details = {
            'path': request.path,
            'method': request.method,
        }
        
        # Add query params if present
        if request.GET:
            details['query_params'] = dict(request.GET)
        
        # Add request body for POST/PUT/PATCH (sanitized)
        if request.method in ['POST', 'PUT', 'PATCH']:
            try:
                if hasattr(request, 'data'):
                    # DRF request
                    body = request.data
                    if isinstance(body, dict):
                        # Remove sensitive fields
                        sanitized = {k: v for k, v in body.items() 
                                     if k not in ['password', 'token', 'secret']}
                        details['body'] = sanitized
            except Exception:
                pass
        
        return json.dumps(details, default=str)[:1000]


class OverdueVisitSchedulerMiddleware:
    """
    Lightweight daily scheduler for overdue visit notifications.
    Runs once per day (on first request after midnight) to send push
    notifications for overdue cases. This is a fallback for deployments
    without Railway cron (e.g., Docker, local).
    """
    _last_run_date = None

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from datetime import date
        today = date.today()
        if OverdueVisitSchedulerMiddleware._last_run_date != today:
            OverdueVisitSchedulerMiddleware._last_run_date = today
            try:
                from django.core.management import call_command
                call_command('send_overdue_notifications')
            except Exception:
                pass
        return self.get_response(request)
