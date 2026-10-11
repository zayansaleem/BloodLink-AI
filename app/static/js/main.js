/**
 * BloodLink AI - Core Frontend Utilities
 */

document.addEventListener('DOMContentLoaded', function () {
  // Auto-dismiss alerts after 5 seconds
  setTimeout(function () {
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      if (bsAlert) bsAlert.close();
    });
  }, 5000);

  // Close mobile offcanvas navigation menu when navigation link is clicked
  const offcanvasEl = document.getElementById('navbarOffcanvas');
  if (offcanvasEl) {
    const offcanvasLinks = offcanvasEl.querySelectorAll('.nav-link, .dropdown-item');
    offcanvasLinks.forEach(function (link) {
      link.addEventListener('click', function () {
        const bsOffcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
        if (bsOffcanvas) bsOffcanvas.hide();
      });
    });
  }
});

/**
 * Leaflet Blood Bank Map Initializer with Pan-India Bounds & Interactive Filtering
 */
function initBloodBankMap(banks) {
  const mapElement = document.getElementById('bloodBankMap');
  if (!mapElement) return;

  // Center on India geographic center (22.5 N, 78.9 E) with nationwide zoom
  const indiaCenterLat = 22.5000;
  const indiaCenterLng = 78.9000;
  const map = L.map('bloodBankMap').setView([indiaCenterLat, indiaCenterLng], 5);

  // OpenStreetMap Tile Layer with standard attribution
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }).addTo(map);

  let markersLayer = L.featureGroup().addTo(map);

  function renderMarkers(filteredBanks) {
    markersLayer.clearLayers();
    if (!filteredBanks || filteredBanks.length === 0) return;

    filteredBanks.forEach(function (bank) {
      if (bank.lat && bank.lng) {
        const marker = L.marker([bank.lat, bank.lng]);
        const popupContent = `
          <div class="p-1" style="min-width: 220px;">
            <div class="d-flex align-items-center justify-content-between mb-1">
              <strong class="text-crimson">${bank.name}</strong>
            </div>
            <div class="mb-1">
              <span class="badge bg-secondary" style="font-size: 10px;">DEMO DATA</span>
              <span class="badge bg-success bg-opacity-10 text-success ms-1" style="font-size: 10px;">Verified Bank</span>
            </div>
            <small class="text-muted d-block">${bank.address || ''}</small>
            <small class="text-secondary fw-semibold d-block mt-1">${bank.city}, ${bank.district || ''} (${bank.state || ''})</small>
            <div class="mt-2 d-flex justify-content-between align-items-center">
              <span class="badge bg-danger">${bank.total_units} Reported Units</span>
              <a href="tel:${bank.phone}" class="btn btn-outline-secondary btn-sm py-0 px-2" style="font-size: 11px;">
                <i class="bi bi-telephone"></i>
              </a>
            </div>
          </div>
        `;
        marker.bindPopup(popupContent);
        markersLayer.addLayer(marker);
      }
    });

    if (markersLayer.getLayers().length > 0) {
      map.fitBounds(markersLayer.getBounds().pad(0.1));
    }
  }

  // Initial render of all blood banks
  renderMarkers(banks);

  // Filter listeners if controls exist on map.html
  const stateFilter = document.getElementById('mapStateFilter');
  const districtFilter = document.getElementById('mapDistrictFilter');

  function applyMapFilters() {
    const selectedState = stateFilter ? stateFilter.value : '';
    const selectedDistrict = districtFilter ? districtFilter.value : '';

    const filtered = (banks || []).filter(function (b) {
      if (selectedState && b.state !== selectedState) return false;
      if (selectedDistrict && b.district !== selectedDistrict) return false;
      return true;
    });

    renderMarkers(filtered);
    if (filtered.length === 0) {
      map.setView([indiaCenterLat, indiaCenterLng], 5);
    }
  }

  if (stateFilter) {
    stateFilter.addEventListener('change', function () {
      applyMapFilters();
    });
  }
  if (districtFilter) {
    districtFilter.addEventListener('change', function () {
      applyMapFilters();
    });
  }

  // Handle responsive map resizing across viewport changes
  window.addEventListener('resize', function () {
    if (map) map.invalidateSize();
  });
  setTimeout(function () {
    if (map) map.invalidateSize();
  }, 350);
}

/**
 * Admin Chart.js Analytics Initializer
 */
async function initAdminAnalytics() {
  const groupCanvas = document.getElementById('requestsBloodGroupChart');
  const componentCanvas = document.getElementById('inventoryComponentChart');

  if (groupCanvas) {
    try {
      const res = await fetch('/admin/api/analytics/blood-groups');
      const data = await res.json();
      new Chart(groupCanvas, {
        type: 'bar',
        data: {
          labels: data.labels,
          datasets: [{
            label: 'Emergency Requests',
            data: data.data,
            backgroundColor: '#c8102e',
            borderRadius: 6
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    } catch (err) {
      console.error("Error loading blood group analytics:", err);
    }
  }

  if (componentCanvas) {
    try {
      const res = await fetch('/admin/api/analytics/inventory');
      const data = await res.json();
      new Chart(componentCanvas, {
        type: 'doughnut',
        data: {
          labels: data.labels,
          datasets: [{
            data: data.data,
            backgroundColor: ['#B5122A', '#E63946', '#f59e0b', '#14213D']
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom' } }
        }
      });
    } catch (err) {
      console.error("Error loading inventory analytics:", err);
    }
  }

  const stateCanvas = document.getElementById('stateDonorsChart');
  const urgencyCanvas = document.getElementById('requestUrgencyChart');

  if (stateCanvas) {
    try {
      const res = await fetch('/admin/api/analytics/states-distribution');
      const data = await res.json();
      new Chart(stateCanvas, {
        type: 'bar',
        data: {
          labels: data.donors.labels,
          datasets: [{
            label: 'Voluntary Donors',
            data: data.donors.data,
            backgroundColor: '#0d9488',
            borderRadius: 6
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      });
    } catch (err) {
      console.error("Error loading state distribution analytics:", err);
    }
  }

  if (urgencyCanvas) {
    try {
      const res = await fetch('/admin/api/analytics/request-urgency');
      const data = await res.json();
      const colorMap = {
        'CRITICAL': '#c8102e',
        'HIGH': '#ea580c',
        'MEDIUM': '#f59e0b',
        'LOW': '#10b981'
      };
      const bgColors = data.labels.map(l => colorMap[l] || '#64748b');
      new Chart(urgencyCanvas, {
        type: 'pie',
        data: {
          labels: data.labels,
          datasets: [{
            data: data.data,
            backgroundColor: bgColors
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom' } }
        }
      });
    } catch (err) {
      console.error("Error loading urgency analytics:", err);
    }
  }
}

/**
 * Reusable Indian State -> District -> City Cascade Dropdown Controller
 * Supports all 28 States & 8 Union Territories with instant client lookup & API fallback.
 */
function getLocationHierarchy() {
  if (window.INDIAN_LOCATIONS && Object.keys(window.INDIAN_LOCATIONS).length > 0) {
    return Promise.resolve(window.INDIAN_LOCATIONS);
  }
  return fetch('/api/locations/hierarchy')
    .then(function (res) { return res.json(); })
    .then(function (data) {
      window.INDIAN_LOCATIONS = data;
      return data;
    })
    .catch(function (err) {
      console.error("Failed to load Indian location hierarchy:", err);
      return {};
    });
}

function initLocationCascade(stateSelectId, districtSelectId, cityInputId, initialDistrict = '', initialCity = '', allowAllOption = false) {
  const stateSelect = typeof stateSelectId === 'string' ? document.getElementById(stateSelectId) : stateSelectId;
  const districtSelect = typeof districtSelectId === 'string' ? document.getElementById(districtSelectId) : districtSelectId;
  const cityInput = typeof cityInputId === 'string' ? document.getElementById(cityInputId) : cityInputId;

  if (!stateSelect || !districtSelect) return;

  function doPopulate(hierarchy, selectedState, preselectDistrict) {
    districtSelect.innerHTML = '';

    if (!selectedState || !hierarchy || !hierarchy[selectedState]) {
      const opt = document.createElement('option');
      opt.value = '';
      opt.textContent = selectedState ? '-- Select District --' : '-- Select State First --';
      districtSelect.appendChild(opt);
      return;
    }

    const defaultOpt = document.createElement('option');
    defaultOpt.value = '';
    defaultOpt.textContent = allowAllOption ? `All Districts in ${selectedState}` : '-- Select District --';
    districtSelect.appendChild(defaultOpt);

    const districts = hierarchy[selectedState] || [];
    districts.forEach(function (d) {
      const opt = document.createElement('option');
      opt.value = d;
      opt.textContent = d;
      if (preselectDistrict && (d.toLowerCase() === preselectDistrict.toLowerCase())) {
        opt.selected = true;
      }
      districtSelect.appendChild(opt);
    });
  }

  // Pre-fill initial city placeholder if present
  if (cityInput && cityInput.tagName === 'INPUT' && initialCity) {
    cityInput.value = initialCity;
  }

  // Immediately bind state change listener so user interactions are never missed
  stateSelect.addEventListener('change', function () {
    const selectedState = this.value;
    getLocationHierarchy().then(function (hierarchy) {
      doPopulate(hierarchy, selectedState, '');
    });
    if (cityInput && cityInput.tagName === 'INPUT' && !initialCity) {
      cityInput.placeholder = 'City / Town';
    }
  });

  districtSelect.addEventListener('change', function () {
    if (cityInput && cityInput.tagName === 'INPUT' && !cityInput.value) {
      cityInput.placeholder = this.value ? `City / Town in ${this.value}` : 'City / Town';
    }
  });

  // Populate districts immediately using cached data or async fallback
  getLocationHierarchy().then(function (hierarchy) {
    if (stateSelect.value) {
      doPopulate(hierarchy, stateSelect.value, initialDistrict);
    } else {
      doPopulate(hierarchy, '', '');
    }
  });
}

/**
 * Show/Hide Password Toggle Controller
 */
function initPasswordToggle(toggleBtnId, passwordInputId) {
  const toggleBtn = document.getElementById(toggleBtnId);
  const passwordInput = document.getElementById(passwordInputId);
  if (!toggleBtn || !passwordInput) return;

  toggleBtn.addEventListener('click', function () {
    const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
    passwordInput.setAttribute('type', type);
    const icon = toggleBtn.querySelector('i');
    if (icon) {
      icon.classList.toggle('bi-eye');
      icon.classList.toggle('bi-eye-slash');
    }
  });
}

/**
 * Global Form Submit Anti-Double-Click and Loading Feedback
 * Prevents accidental duplicate submissions while providing accessible visual feedback.
 */
document.addEventListener('submit', function (e) {
  const form = e.target;
  if (form && form.method && form.method.toUpperCase() !== 'GET') {
    const submitBtn = form.querySelector('button[type="submit"]:not(.no-spin)');
    if (submitBtn && !submitBtn.disabled) {
      setTimeout(function () {
        submitBtn.disabled = true;
        submitBtn.classList.add('btn-loading');
        const icon = submitBtn.querySelector('i');
        if (icon) {
          icon.className = 'spinner-border spinner-border-sm me-1';
        }
      }, 40);
    }
  }
});

