# Database Migration Guide - Add Clinical Fields

## Overview
This migration adds 70+ clinical fields to the `OpcRegistration` model to prevent data loss from comprehensive form submissions.

## Changes Made

### 1. Model Updates (`apps/cases/models.py`)
- ✅ Added 70+ new fields to `OpcRegistration` model
- ✅ Changed z-score fields from `DecimalField` to `CharField` (supports both categorical and numeric values)
- ✅ All new fields are nullable (`null=True, blank=True`)

### 2. API Updates (`apps/api/views.py`)
- ✅ Updated `case_create_api` to save all 70+ fields
- ✅ All fields use `.get()` with safe defaults

### 3. Form Fixes (`templates/cases/partials/*.html`)
- ✅ Fixed field name mismatches in SAM, MAM, and IPC forms

---

## Migration Steps

### Step 1: Create Migration File

```bash
cd c:\wamp64\www\cmam\cmam-tracker-django
python manage.py makemigrations cases --name add_clinical_fields
```

This will create a migration file like: `apps/cases/migrations/0XXX_add_clinical_fields.py`

### Step 2: Review Migration

Open the generated migration file and verify it includes:
- Adding all new fields
- Changing z-score fields from DecimalField to CharField

### Step 3: Backup Database

**CRITICAL: Backup your database before running migrations!**

```bash
# For PostgreSQL
pg_dump -U your_user -d cmam_db > backup_before_clinical_fields_$(date +%Y%m%d).sql

# For SQLite (development)
cp db.sqlite3 db.sqlite3.backup_$(date +%Y%m%d)
```

### Step 4: Run Migration

```bash
python manage.py migrate cases
```

Expected output:
```
Running migrations:
  Applying cases.0XXX_add_clinical_fields... OK
```

### Step 5: Verify Migration

```bash
python manage.py shell
```

```python
from apps.cases.models import OpcRegistration

# Check that new fields exist
fields = [f.name for f in OpcRegistration._meta.get_fields()]
print('father_alive' in fields)  # Should print: True
print('respiratory_rate' in fields)  # Should print: True
print('amoxicillin_date' in fields)  # Should print: True

# Check z-score field types
z_wfh_field = OpcRegistration._meta.get_field('z_score_wfh')
print(type(z_wfh_field).__name__)  # Should print: CharField
```

---

## Testing

### Test 1: Create Case via API (Mobile App)

```bash
curl -X POST http://localhost:8000/api/v1/cases/create/ \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "child_name": "Test Child",
    "child_gender": "Male",
    "date_of_birth": "2024-01-01",
    "age_months": 24,
    "malnutrition_type": "SAM",
    "admission_date": "2026-06-18",
    "weight_kg": 8.5,
    "height_cm": 75.0,
    "facility_id": 1,
    "father_alive": "Yes",
    "diarrhoea": "No",
    "respiratory_rate": "30-39",
    "amoxicillin_date": "2026-06-18",
    "rutf_sachets_given": 14
  }'
```

### Test 2: Verify Data Saved

```python
from apps.cases.models import OpcRegistration

case = OpcRegistration.objects.latest('id')
print(f"Father Alive: {case.father_alive}")  # Should print: Yes
print(f"Diarrhoea: {case.diarrhoea}")  # Should print: No
print(f"Respiratory Rate: {case.respiratory_rate}")  # Should print: 30-39
print(f"Amoxicillin Date: {case.amoxicillin_date}")  # Should print: 2026-06-18
print(f"RUTF Sachets: {case.rutf_sachets_given}")  # Should print: 14
```

### Test 3: Create Case via Webapp

1. Navigate to: http://localhost:8000/cases/create/
2. Select SAM tab
3. Fill in all fields including:
   - Medical history (diarrhoea, vomiting, etc.)
   - Physical exam (respiratory rate, temperature, etc.)
   - Medicines (amoxicillin, vitamin A, etc.)
4. Submit form
5. Verify all data is saved in database

---

## Rollback Plan

If migration fails or causes issues:

### Option 1: Rollback Migration

```bash
# Find the migration number before this one
python manage.py showmigrations cases

# Rollback to previous migration
python manage.py migrate cases 0XXX_previous_migration_name
```

### Option 2: Restore from Backup

```bash
# For PostgreSQL
psql -U your_user -d cmam_db < backup_before_clinical_fields_YYYYMMDD.sql

# For SQLite
cp db.sqlite3.backup_YYYYMMDD db.sqlite3
```

---

## Field Mapping Reference

### New Fields Added (70+ total)

#### Demographic/Social (5 fields)
- `father_alive` - CharField(10)
- `mother_alive` - CharField(10)
- `house_location` - CharField(255)
- `travel_time` - CharField(50)
- `referral_source` - CharField(100)

#### Medical History (11 fields)
- `diarrhoea` - CharField(10)
- `stool_frequency` - CharField(10)
- `vomiting` - CharField(10)
- `cough` - CharField(10)
- `passing_urine` - CharField(10)
- `oedema_duration_days` - IntegerField
- `breastfeeding_status` - CharField(10)
- `breastfeeding_prospect` - CharField(20)
- `immunization_status` - CharField(50)
- `g6pd_status` - CharField(50)
- `additional_medical_history` - TextField

#### Physical Examination (13 fields)
- `respiratory_rate` - CharField(20)
- `temperature_celsius` - DecimalField(4,1)
- `chest_indrawing` - CharField(10)
- `eyes_condition` - CharField(50)
- `conjunctiva` - CharField(50)
- `ears_condition` - CharField(50)
- `mouth_condition` - CharField(50)
- `lymph_nodes` - CharField(50)
- `hands_feet` - CharField(50)
- `skin_changes` - CharField(50)
- `disability` - CharField(10)
- `disability_details` - CharField(255)
- `physical_exam_notes` - TextField

#### Medicines at Enrollment (14 fields)
- `amoxicillin_date` - DateField
- `amoxicillin_dosage` - CharField(100)
- `vitamin_a_date` - DateField
- `vitamin_a_dosage` - CharField(100)
- `folic_acid_date` - DateField
- `folic_acid_dosage` - CharField(100)
- `deworming_date` - DateField
- `deworming_dosage` - CharField(100)
- `measles_vaccine_date` - DateField
- `measles_vaccine_dosage` - CharField(100)
- `malaria_test_date` - DateField
- `malaria_test_result` - CharField(20)
- `antimalarial_date` - DateField
- `antimalarial_dosage` - CharField(100)

#### RUTF and Supplies (3 fields)
- `rutf_sachets_given` - IntegerField
- `rutf_ration_per_day` - DecimalField(4,1)
- `next_visit_date` - DateField

#### Other Medicines (9 fields)
- `other_drug_1` - CharField(100)
- `other_drug_1_date` - DateField
- `other_drug_1_dosage` - CharField(100)
- `other_drug_2` - CharField(100)
- `other_drug_2_date` - DateField
- `other_drug_2_dosage` - CharField(100)
- `other_drug_3` - CharField(100)
- `other_drug_3_date` - DateField
- `other_drug_3_dosage` - CharField(100)

#### Additional (1 field)
- `additional_notes` - TextField

### Modified Fields (3)
- `z_score_wfh` - Changed from DecimalField to CharField(50)
- `z_score_wfa` - Changed from DecimalField to CharField(50)
- `z_score_hfa` - Changed from DecimalField to CharField(50)

---

## Performance Considerations

### Database Size Impact
- **Before**: ~25 columns in `opc_registrations` table
- **After**: ~95 columns in `opc_registrations` table
- **Estimated size increase**: 30-40% per row (most fields are nullable and will be NULL for old records)

### Query Performance
- No impact on existing queries (new fields are optional)
- Indexes on frequently queried fields remain unchanged
- Consider adding indexes if filtering by new fields in future

### Recommendations
1. Monitor database size after migration
2. Run `VACUUM ANALYZE` (PostgreSQL) or `OPTIMIZE TABLE` (MySQL) after migration
3. Update any custom queries/reports that need new fields

---

## Troubleshooting

### Issue: Migration fails with "column already exists"
**Solution**: Check if migration was partially applied. Rollback and try again.

### Issue: Z-score data type error
**Solution**: The migration changes z-score fields to CharField. Existing numeric values will be converted to strings automatically.

### Issue: API returns 500 error after migration
**Solution**: 
1. Check Django logs: `tail -f logs/django.log`
2. Verify migration completed successfully
3. Restart Django server

### Issue: Webapp forms not saving new fields
**Solution**: Clear browser cache and verify form field names match model fields.

---

## Post-Migration Tasks

### 1. Update Serializers (if needed)

Check `apps/api/serializers.py` and add new fields to serializers if they need to be exposed via API:

```python
class OpcRegistrationDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = OpcRegistration
        fields = '__all__'  # Or explicitly list all fields
```

### 2. Update Admin Interface (optional)

Update `apps/cases/admin.py` to display new fields:

```python
@admin.register(OpcRegistration)
class OpcRegistrationAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Basic Information', {
            'fields': ('child_name', 'child_gender', 'date_of_birth', ...)
        }),
        ('Medical History', {
            'fields': ('diarrhoea', 'vomiting', 'cough', ...),
            'classes': ('collapse',)
        }),
        # ... more fieldsets
    )
```

### 3. Update Reports (if needed)

If you have custom reports that should include new fields, update them accordingly.

### 4. Documentation

Update user documentation to reflect new fields available in forms.

---

## Success Criteria

✅ Migration runs without errors
✅ All 70+ new fields exist in database
✅ Z-score fields are now CharField
✅ Mobile app can submit comprehensive forms
✅ Webapp can submit comprehensive forms
✅ All submitted data is saved (no data loss)
✅ Existing cases remain intact
✅ API responses include new fields

---

## Support

If you encounter issues:
1. Check Django logs
2. Verify database schema: `python manage.py dbshell` then `\d opc_registrations` (PostgreSQL)
3. Review migration file for errors
4. Restore from backup if needed

---

**Migration Status**: ⚠️ Ready to Execute
**Estimated Downtime**: < 5 minutes
**Risk Level**: Low (all new fields are nullable)
**Backup Required**: ✅ Yes (CRITICAL)
