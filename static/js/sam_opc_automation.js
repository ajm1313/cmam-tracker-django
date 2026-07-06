// ponytail: SAM OPC automation - minimal decision logic
// Based on SAM_OPC_app_automation_spec.md

const SamOpcAutomation = {
  // IPC Referral Criteria Checks
  checkIpcReferral(data) {
    const reasons = [];
    
    // Infant under 6 months checks
    if (data.age_months < 6) {
      if (data.oedema && data.oedema !== 'None') reasons.push('Infant has oedema');
      if (data.appetite_test === 'Failed') reasons.push('Infant unable to feed');
      if (data.temperature_c && (data.temperature_c > 39 || data.temperature_c < 35)) reasons.push('Temperature out of range');
    }
    
    // Children 6-59 months checks
    if (data.age_months >= 6) {
      if (data.oedema === '+++') reasons.push('Grade +++ oedema');
      if (data.appetite_test === 'Failed') reasons.push('Failed appetite test');
      if (data.intractable_vomiting) reasons.push('Intractable vomiting');
      if (data.convulsions) reasons.push('Convulsions');
      if (data.lethargic) reasons.push('Lethargic or not alert');
      if (data.unconscious) reasons.push('Unconscious');
      if (data.temperature_c && (data.temperature_c > 39 || data.temperature_c < 35)) reasons.push('Temperature out of range');
      
      // Respiratory rate checks
      if (data.respiratory_rate) {
        const rr = parseInt(data.respiratory_rate);
        if (data.age_months < 2 && rr >= 60) reasons.push('High respiratory rate');
        else if (data.age_months < 12 && rr >= 50) reasons.push('High respiratory rate');
        else if (data.age_months < 60 && rr >= 40) reasons.push('High respiratory rate');
      }
      
      if (data.chest_indrawing) reasons.push('Chest indrawing');
      if (data.severe_dehydration) reasons.push('Severe dehydration');
      if (data.severe_pallor) reasons.push('Severe palmar pallor');
      if (data.weight_kg && data.age_months > 6 && parseFloat(data.weight_kg) < 4) reasons.push('Weight < 4kg');
    }
    
    return { needsReferral: reasons.length > 0, reasons };
  },

  // Auto-select admission type
  getAdmissionType(source) {
    const mapping = {
      'community': 'Direct from community',
      'self_referral': 'Direct from community',
      'cwc_or_outreach': 'Direct from community',
      'health_facility_referral': 'Referred from health facility',
      'inpatient_care_referral': 'Referred from inpatient care',
      'other_opc_transfer': 'Referred from health facility',
      'returned_defaulter': 'Re-enrolment/returned defaulter',
      'relapse_after_cure': 'Re-enrolment/relapse'
    };
    return mapping[source] || '';
  },

  // Auto-select reporting category
  getReportingCategory(data) {
    // Old case conditions
    if (['inpatient_care_referral', 'other_opc_transfer', 'returned_defaulter'].includes(data.source)) {
      return 'D: Old case';
    }
    
    // New case conditions
    if (data.age_months < 6) return 'B1: New SAM case under 6 months at risk';
    if (data.oedema && data.oedema !== 'None') return 'B3: New SAM case 6-59 months oedema/marasmic kwashiorkor';
    if (data.age_months >= 6 && data.age_months < 60) return 'B2: New SAM case 6-59 months by MUAC/WFLH';
    if (data.age_months >= 60) return 'C: Other new SAM case';
    
    return 'B2: New SAM case 6-59 months by MUAC/WFLH';
  },

  // Visit action triggers
  checkVisitActions(data) {
    const actions = [];
    
    // Check IPC referral first
    const ipcCheck = this.checkIpcReferral(data);
    if (ipcCheck.needsReferral) {
      return { action: 'R: Referral', reasons: ipcCheck.reasons, priority: 'critical' };
    }
    
    // Check for home visit triggers
    if (data.consecutive_weight_loss >= 2) actions.push({ action: 'HV: Home Visit', reason: 'Weight loss for 2 weeks' });
    if (data.consecutive_static_weight >= 3) actions.push({ action: 'HV: Home Visit', reason: 'Static weight for 3 weeks' });
    if (data.rutf_consumed_percent < 75 && data.visit_number >= 3) actions.push({ action: 'HV: Home Visit', reason: 'Low RUTF consumption' });
    if (data.below_admission_weight_week_3) actions.push({ action: 'HV: Home Visit', reason: 'Below admission weight at week 3' });
    
    if (actions.length > 0) return { action: 'HV: Home Visit', reasons: actions.map(a => a.reason), priority: 'high' };
    
    return { action: 'OK: Continue Treatment', reasons: [], priority: 'normal' };
  },

  // Discharge criteria check
  checkDischargeCriteria(data) {
    // Priority order: Died > Referred > Defaulted > Non-Recovered > Cured
    
    if (data.died) return { outcome: 'X: Died', ready: true };
    
    const ipcCheck = this.checkIpcReferral(data);
    if (ipcCheck.needsReferral) return { outcome: 'R: Referral', ready: true, reasons: ipcCheck.reasons };
    
    if (data.missed_consecutive_visits >= 3) return { outcome: 'D: Defaulted', ready: true };
    
    if (data.weeks_in_treatment >= 16 && !data.meets_cure_criteria) {
      return { outcome: 'NR: Non-Recovered', ready: true, note: 'Confirm medical investigation done' };
    }
    
    // Cured criteria
    const curedChecks = {
      clinically_well: data.clinically_well,
      no_oedema: !data.oedema || data.oedema === 'None',
      muac_ok: data.muac_cm >= 12.5,
      sustained: data.consecutive_recovery_visits >= 3
    };
    
    if (Object.values(curedChecks).every(v => v === true)) {
      return { outcome: 'C: Cured', ready: true, note: 'Complete discharge counselling and linkage' };
    }
    
    return { outcome: 'Continue', ready: false };
  },

  // Show alert/warning
  showAlert(type, message, reasons = []) {
    const colors = {
      critical: { bg: '#fee', border: '#dc2626', text: '#991b1b' },
      high: { bg: '#fef3c7', border: '#f59e0b', text: '#92400e' },
      normal: { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af' },
      success: { bg: '#d1fae5', border: '#10b981', text: '#065f46' }
    };
    
    const color = colors[type] || colors.normal;
    const reasonsList = reasons.length > 0 ? '<ul class="list-disc ml-5 mt-2">' + reasons.map(r => `<li>${r}</li>`).join('') + '</ul>' : '';
    
    const alertDiv = document.createElement('div');
    alertDiv.className = 'fixed top-4 right-4 max-w-md p-4 rounded-lg shadow-lg z-50 animate-slide-in';
    alertDiv.style.backgroundColor = color.bg;
    alertDiv.style.borderLeft = `4px solid ${color.border}`;
    alertDiv.innerHTML = `
      <div class="flex items-start gap-3">
        <div class="flex-1">
          <p class="font-semibold" style="color: ${color.text}">${message}</p>
          ${reasonsList}
        </div>
        <button onclick="this.parentElement.parentElement.remove()" class="text-gray-500 hover:text-gray-700">&times;</button>
      </div>
    `;
    
    document.body.appendChild(alertDiv);
    setTimeout(() => alertDiv.remove(), 10000);
  }
};

// Export for use in forms
if (typeof module !== 'undefined' && module.exports) {
  module.exports = SamOpcAutomation;
}
