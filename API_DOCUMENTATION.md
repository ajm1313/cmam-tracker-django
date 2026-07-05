# CMAM Tracker API Documentation

Base URL: `https://nutri.pharn.org/api/v1`

## Authentication

All endpoints except `/login` require JWT authentication.

### Headers
```
Authorization: Bearer <access_token>
Content-Type: application/json
```

## Endpoints

### Authentication

#### POST `/v1/login/`
Login and receive JWT token.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "data": {
    "user": {
      "id": 1,
      "name": "John Doe",
      "email": "user@example.com",
      "phone": "+1234567890",
      "role": {
        "id": 2,
        "name": "Health Worker",
        "level": 3
      },
      "location": {
        "facility_id": 5,
        "facility_name": "Health Center A",
        "district_id": 10,
        "region_id": 2
      }
    },
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
    "expires_at": "2026-06-18T13:52:00Z"
  }
}
```

#### POST `/v1/logout/`
Logout (invalidate token).

#### GET `/v1/profile/`
Get current user profile.

#### POST `/v1/change-password/`
Change user password.

**Request:**
```json
{
  "old_password": "current_password",
  "new_password": "new_password123"
}
```

---

### Cases

#### GET `/v1/cases/`
List all cases with optional filters.

**Query Parameters:**
- `status`: `active`, `discharged`, `defaulter`
- `case_type`: `SAM`, `MAM`, `IPC`
- `facility_id`: Filter by facility
- `search`: Search by name or registration number

**Response:**
```json
{
  "success": true,
  "data": [
    {
      "id": 123,
      "registration_number": "SAM-2026-001",
      "child_name": "Jane Doe",
      "malnutrition_type": "SAM",
      "status": "Active",
      "admission_date": "2026-06-01",
      "age_months": 18,
      "weight_kg": 7.5,
      "muac_cm": 10.8,
      "facility_name": "Health Center A",
      "visit_count": 3,
      "is_visit_due": true
    }
  ]
}
```

#### POST `/v1/cases/create/`
Register a new case.

**Request:**
```json
{
  "facility_id": 5,
  "child_name": "Jane Doe",
  "child_gender": "Female",
  "date_of_birth": "2024-12-01",
  "age_months": 18,
  "malnutrition_type": "SAM",
  "weight_kg": 7.5,
  "height_cm": 75.0,
  "muac_cm": 10.8,
  "oedema": "None",
  "caregiver_name": "Mary Doe",
  "caregiver_phone": "+1234567890"
}
```

#### GET `/v1/cases/<id>/`
Get case details.

#### PUT `/v1/cases/<id>/edit/`
Update case information.

#### DELETE `/v1/cases/<id>/delete/`
Soft-delete a case (sets status to Discharged).

#### POST `/v1/cases/<id>/discharge/`
Process case discharge.

**Request:**
```json
{
  "discharge_date": "2026-06-18",
  "discharge_type": "Cured",
  "discharge_weight_kg": 9.5,
  "discharge_muac_cm": 12.5
}
```

#### GET `/v1/cases/due-visits/`
Get list of cases with due visits.

---

### Visits

#### GET `/v1/cases/<registration_id>/visits/`
Get all visits for a case.

#### POST `/v1/cases/<registration_id>/visits/record/`
Record a new visit.

**Request:**
```json
{
  "visit_date": "2026-06-18",
  "weight_kg": 8.2,
  "height_cm": 76.0,
  "muac_cm": 11.5,
  "oedema": "None",
  "appetite_test": "Good",
  "rutf_sachets_given": 14,
  "next_visit_date": "2026-06-25"
}
```

#### PUT `/v1/cases/<registration_id>/visits/<visit_id>/edit/`
Edit an existing visit.

---

### Facilities

#### GET `/v1/facilities/`
List all facilities.

#### POST `/v1/facilities/create/`
Create a new facility.

**Request:**
```json
{
  "name": "Health Center B",
  "type": "Health Center",
  "district_id": 10,
  "sub_district_id": 25,
  "contact_person": "Dr. Smith",
  "phone": "+1234567890"
}
```

#### GET `/v1/facilities/<id>/`
Get facility details.

#### PUT `/v1/facilities/<id>/edit/`
Update facility.

#### DELETE `/v1/facilities/<id>/delete/`
Delete facility.

---

### Users

#### GET `/v1/users/`
List all users.

#### POST `/v1/users/create/`
Create a new user.

**Request:**
```json
{
  "name": "John Smith",
  "email": "john@example.com",
  "phone": "+1234567890",
  "password": "secure_password",
  "role_id": 3,
  "facility_id": 5
}
```

#### GET `/v1/users/<id>/`
Get user details.

#### PUT `/v1/users/<id>/edit/`
Update user.

#### DELETE `/v1/users/<id>/delete/`
Delete user.

---

### Inventory

#### GET `/v1/inventory/items/`
List all inventory items.

#### POST `/v1/inventory/items/create/`
Create inventory item.

#### GET `/v1/inventory/facility/<facility_id>/stock/`
Get stock levels for a facility.

#### POST `/v1/inventory/consumption/`
Record consumption.

**Request:**
```json
{
  "facility_id": 5,
  "item_id": 2,
  "quantity": 10,
  "consumed_date": "2026-06-18",
  "notes": "Distributed to patients"
}
```

#### GET `/v1/inventory/stock-levels/`
Get all stock levels.

#### POST `/v1/inventory/stock-levels/update/`
Update stock level.

#### GET `/v1/inventory/movements/`
Get stock movements.

#### POST `/v1/inventory/movements/create/`
Record stock movement.

#### GET `/v1/inventory/requests/`
List stock requests.

#### POST `/v1/inventory/requests/create/`
Create stock request.

#### PUT `/v1/inventory/requests/<id>/`
Update stock request (approve/reject).

#### GET `/v1/inventory/batches/`
Get item batches with expiry tracking.

---

### Locations

#### GET `/v1/locations/regions/`
List all regions.

#### POST `/v1/locations/regions/`
Create region (requires admin).

#### GET `/v1/locations/districts/`
List all districts.

**Query Parameters:**
- `region_id`: Filter by region

#### POST `/v1/locations/districts/`
Create district.

#### GET `/v1/locations/sub-districts/`
List all sub-districts.

**Query Parameters:**
- `district_id`: Filter by district

#### POST `/v1/locations/sub-districts/`
Create sub-district.

---

### Reports

#### GET `/v1/reports/summary/`
Get summary statistics.

**Response:**
```json
{
  "success": true,
  "data": {
    "total_cases": 450,
    "active_cases": 320,
    "sam_cases": 180,
    "mam_cases": 140,
    "discharged_this_month": 25,
    "cure_rate": 85.5
  }
}
```

#### GET `/v1/reports/weekly/`
Get weekly SAM/MAM tally report.

**Query Parameters:**
- `start_date`: Start date (YYYY-MM-DD)
- `end_date`: End date (YYYY-MM-DD)
- `facility_id`: Filter by facility

#### GET `/v1/reports/monthly/`
Get monthly facility report.

**Query Parameters:**
- `month`: Month (1-12)
- `year`: Year (YYYY)
- `facility_id`: Filter by facility

---

### Dashboard

#### GET `/v1/dashboard/stats/`
Get dashboard statistics.

**Response:**
```json
{
  "success": true,
  "data": {
    "cases": {
      "total": 450,
      "active": 320,
      "sam": 180,
      "mam": 140
    },
    "visits_today": 15,
    "due_visits": 42,
    "stock_alerts": 3
  }
}
```

#### GET `/v1/dashboard/analytics/`
Get analytics data for charts.

---

### Roles & Access Control

#### GET `/v1/roles/`
List all roles.

#### GET `/v1/access-control/`
Get access control settings.

#### POST `/v1/access-control/update/`
Update role permissions.

---

### Import/Export

#### GET `/v1/export/cases/`
Export cases to Excel.

**Query Parameters:**
- `status`: Filter by status
- `facility_id`: Filter by facility
- `start_date`, `end_date`: Date range

#### GET `/v1/export/inventory/`
Export inventory to Excel.

#### GET `/v1/import/template/<model_type>/`
Download import template.

**model_type**: `cases`, `inventory`

#### POST `/v1/import/cases/preview/`
Preview case import (validate Excel file).

#### POST `/v1/import/cases/execute/`
Execute case import.

#### POST `/v1/import/inventory/preview/`
Preview inventory import.

#### POST `/v1/import/inventory/execute/`
Execute inventory import.

---

## Error Responses

### 400 Bad Request
```json
{
  "success": false,
  "message": "Validation error",
  "errors": {
    "email": ["This field is required"],
    "age_months": ["Must be between 6 and 59"]
  }
}
```

### 401 Unauthorized
```json
{
  "success": false,
  "message": "Invalid or expired token"
}
```

### 403 Forbidden
```json
{
  "success": false,
  "message": "You do not have permission to perform this action"
}
```

### 404 Not Found
```json
{
  "success": false,
  "message": "Resource not found"
}
```

### 500 Internal Server Error
```json
{
  "success": false,
  "message": "An internal error occurred"
}
```

---

## Rate Limiting

- **Rate limit**: 100 requests per minute per user
- **Burst limit**: 20 requests per second

Headers returned:
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1718721120
```

---

## Pagination

List endpoints support pagination:

**Query Parameters:**
- `page`: Page number (default: 1)
- `page_size`: Items per page (default: 20, max: 100)

**Response:**
```json
{
  "success": true,
  "data": [...],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_pages": 15,
    "total_items": 300,
    "has_next": true,
    "has_previous": false
  }
}
```

---

## Postman Collection

Import the Postman collection for easy API testing:

1. Download: [CMAM_Tracker_API.postman_collection.json](./CMAM_Tracker_API.postman_collection.json)
2. Import into Postman
3. Set environment variables:
   - `base_url`: https://nutri.pharn.org/api/v1
   - `access_token`: (obtained from login)

---

## Support

For API issues or questions:
- Email: support@pharn.org
- Documentation: https://nutri.pharn.org/docs
