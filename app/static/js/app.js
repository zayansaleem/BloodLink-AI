/**
 * BloodLink AI - Front-End Interactions
 */

document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss alerts after 5 seconds
  setTimeout(function () {
    const alerts = document.querySelectorAll('.alert-banner');
    alerts.forEach(alert => {
      alert.style.transition = 'opacity 0.5s ease-out';
      alert.style.opacity = '0';
      setTimeout(() => alert.remove(), 500);
    });
  }, 5000);

  // Setup Live Priority Calculator if elements exist
  setupLivePriorityCalculator();

  // Setup Blood Compatibility Tool if exists
  setupCompatibilityWidget();
});

/**
 * Live Priority Calculator for Blood Request Form
 */
function setupLivePriorityCalculator() {
  const urgencySelect = document.getElementById('req-urgency');
  const bloodSelect = document.getElementById('req-blood-group');
  const unitsInput = document.getElementById('req-units');
  const previewScore = document.getElementById('preview-priority-score');
  const previewBar = document.getElementById('preview-priority-bar');
  const previewBadge = document.getElementById('preview-priority-badge');
  const previewDesc = document.getElementById('preview-priority-desc');

  if (!urgencySelect || !previewScore) return;

  async function updatePriorityPreview() {
    const urgency = urgencySelect.value;
    const bloodGroup = bloodSelect.value;
    const units = unitsInput.value || 1;

    try {
      const response = await fetch('/api/priority-calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          urgency_level: urgency,
          blood_group: bloodGroup,
          units_needed: units
        })
      });

      if (!response.ok) return;
      const data = await response.json();

      previewScore.textContent = data.priority_score;
      if (previewBar) {
        previewBar.style.width = `${Math.min(100, data.priority_score)}%`;
        if (data.priority_score >= 80) {
          previewBar.className = 'h-2 rounded-full transition-all duration-300 bg-red-600';
        } else if (data.priority_score >= 60) {
          previewBar.className = 'h-2 rounded-full transition-all duration-300 bg-orange-500';
        } else if (data.priority_score >= 40) {
          previewBar.className = 'h-2 rounded-full transition-all duration-300 bg-amber-500';
        } else {
          previewBar.className = 'h-2 rounded-full transition-all duration-300 bg-blue-500';
        }
      }

      if (previewBadge) {
        previewBadge.textContent = data.level;
      }
      if (previewDesc) {
        previewDesc.textContent = data.description;
      }
    } catch (err) {
      console.error('Error fetching priority preview:', err);
    }
  }

  urgencySelect.addEventListener('change', updatePriorityPreview);
  bloodSelect.addEventListener('change', updatePriorityPreview);
  unitsInput.addEventListener('input', updatePriorityPreview);
  updatePriorityPreview();
}

/**
 * Interactive Compatibility Explorer
 */
const RBC_COMPATIBILITY = {
  'O-': { canDonateTo: ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'], canReceiveFrom: ['O-'] },
  'O+': { canDonateTo: ['O+', 'A+', 'B+', 'AB+'], canReceiveFrom: ['O-', 'O+'] },
  'A-': { canDonateTo: ['A-', 'A+', 'AB-', 'AB+'], canReceiveFrom: ['O-', 'A-'] },
  'A+': { canDonateTo: ['A+', 'AB+'], canReceiveFrom: ['O-', 'O+', 'A-', 'A+'] },
  'B-': { canDonateTo: ['B-', 'B+', 'AB-', 'AB+'], canReceiveFrom: ['O-', 'B-'] },
  'B+': { canDonateTo: ['B+', 'AB+'], canReceiveFrom: ['O-', 'O+', 'B-', 'B+'] },
  'AB-': { canDonateTo: ['AB-', 'AB+'], canReceiveFrom: ['O-', 'A-', 'B-', 'AB-'] },
  'AB+': { canDonateTo: ['AB+'], canReceiveFrom: ['O-', 'O+', 'A-', 'A+', 'B-', 'B+', 'AB-', 'AB+'] }
};

function setupCompatibilityWidget() {
  const selector = document.getElementById('compat-selector');
  const donateList = document.getElementById('compat-can-donate');
  const receiveList = document.getElementById('compat-can-receive');

  if (!selector || !donateList || !receiveList) return;

  function renderCompatibility() {
    const group = selector.value;
    const info = RBC_COMPATIBILITY[group];
    if (!info) return;

    donateList.innerHTML = info.canDonateTo
      .map(t => `<span class="px-2.5 py-1 bg-red-100 text-red-700 font-bold rounded-full text-xs shadow-sm">${t}</span>`)
      .join(' ');

    receiveList.innerHTML = info.canReceiveFrom
      .map(t => `<span class="px-2.5 py-1 bg-emerald-100 text-emerald-700 font-bold rounded-full text-xs shadow-sm">${t}</span>`)
      .join(' ');
  }

  selector.addEventListener('change', renderCompatibility);
  renderCompatibility();
}

/**
 * Open AI Match Modal for a specific Blood Request
 */
async function openMatchModal(requestId) {
  const modal = document.getElementById('matchModal');
  const modalContent = document.getElementById('matchModalContent');
  const modalLoading = document.getElementById('matchModalLoading');

  if (!modal) return;

  modal.classList.remove('hidden');
  modalContent.classList.add('hidden');
  modalLoading.classList.remove('hidden');

  try {
    const res = await fetch(`/api/match/${requestId}`);
    if (!res.ok) throw new Error('Failed to load matching data');
    const data = await res.json();

    document.getElementById('modalReqId').textContent = `#${data.request_id}`;
    document.getElementById('modalPatientName').textContent = data.patient_name;
    document.getElementById('modalBloodGroup').textContent = data.blood_group;
    document.getElementById('modalUnits').textContent = `${data.units_needed} Unit(s)`;
    document.getElementById('modalHospital').textContent = data.hospital_name;
    document.getElementById('modalPriority').textContent = `${data.priority_score}/100 (${data.urgency_level})`;

    // Render Donors
    const donorsContainer = document.getElementById('modalDonorsList');
    if (data.matching_donors && data.matching_donors.length > 0) {
      donorsContainer.innerHTML = data.matching_donors.map(d => `
        <div class="p-4 bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
          <div class="flex items-center justify-between mb-2">
            <div>
              <span class="font-bold text-gray-900">${d.name}</span>
              <span class="ml-2 px-2 py-0.5 bg-red-50 text-red-700 font-bold text-xs rounded border border-red-200">${d.blood_group}</span>
              ${d.is_exact ? '<span class="ml-1 text-xs text-emerald-600 font-semibold">(Exact)</span>' : ''}
            </div>
            <div class="text-right">
              <span class="inline-block px-3 py-1 bg-rose-600 text-white font-extrabold text-xs rounded-full shadow-sm">
                ${d.match_score}% AI Match
              </span>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs text-gray-600 mb-2">
            <div><i class="fa-solid fa-location-dot text-rose-500 mr-1"></i> ${d.city} (${d.distance_km} km)</div>
            <div><i class="fa-regular fa-clock text-amber-500 mr-1"></i> ETA: ~${d.eta_mins} mins</div>
            <div><i class="fa-solid fa-phone text-blue-500 mr-1"></i> ${d.phone}</div>
            <div><i class="fa-solid fa-circle-check text-emerald-500 mr-1"></i> ${d.eligible ? 'Ready to Donate' : 'Cooldown Active'}</div>
          </div>
          <div class="flex flex-wrap gap-1 mt-2">
            ${d.reasons.map(r => `<span class="text-[11px] px-2 py-0.5 bg-gray-100 text-gray-700 rounded-md">${r}</span>`).join('')}
          </div>
        </div>
      `).join('');
    } else {
      donorsContainer.innerHTML = `
        <div class="p-6 text-center text-gray-500 bg-gray-50 rounded-xl">
          <i class="fa-solid fa-user-slash text-2xl mb-2 text-gray-400"></i>
          <p class="text-sm">No registered donors within immediate radius. Checking blood banks...</p>
        </div>
      `;
    }

    // Render Blood Banks
    const banksContainer = document.getElementById('modalBanksList');
    if (data.matching_blood_banks && data.matching_blood_banks.length > 0) {
      banksContainer.innerHTML = data.matching_blood_banks.map(b => `
        <div class="p-4 bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition">
          <div class="flex items-center justify-between mb-2">
            <span class="font-bold text-gray-900">${b.name}</span>
            <span class="text-xs px-2.5 py-1 ${b.has_sufficient ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'} font-bold rounded-full">
              ${b.exact_stock} ${data.blood_group} Units
            </span>
          </div>
          <div class="grid grid-cols-2 gap-2 text-xs text-gray-600 mb-2">
            <div><i class="fa-solid fa-location-dot text-rose-500 mr-1"></i> ${b.city} (${b.distance_km} km)</div>
            <div><i class="fa-solid fa-route text-indigo-500 mr-1"></i> ETA: ~${b.eta_mins} mins</div>
            <div><i class="fa-solid fa-phone text-blue-500 mr-1"></i> ${b.phone}</div>
            <div><i class="fa-solid fa-cubes-stacked text-purple-500 mr-1"></i> ${b.compatible_stock} Total Compatible Units</div>
          </div>
        </div>
      `).join('');
    } else {
      banksContainer.innerHTML = `
        <div class="p-6 text-center text-gray-500 bg-gray-50 rounded-xl">
          <i class="fa-solid fa-hospital-user text-2xl mb-2 text-gray-400"></i>
          <p class="text-sm">No blood bank inventory found for this blood group.</p>
        </div>
      `;
    }

    modalLoading.classList.add('hidden');
    modalContent.classList.remove('hidden');
  } catch (err) {
    console.error(err);
    alert('Error loading matching candidates.');
    closeMatchModal();
  }
}

function closeMatchModal() {
  const modal = document.getElementById('matchModal');
  if (modal) modal.classList.add('hidden');
}

/**
 * Toggle Donor Availability status
 */
async function toggleAvailability() {
  try {
    const res = await fetch('/api/toggle-availability', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    const data = await res.json();
    if (data.success) {
      window.location.reload();
    }
  } catch (err) {
    console.error('Error toggling availability:', err);
  }
}
