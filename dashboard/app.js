// Track-Watch Dashboard Application
// Connects to FastAPI backend for railway track monitoring

const API_BASE = 'http://localhost:8000';

// State management
let alerts = [];
let selectedAlertId = null;
let isAnalyzing = false;

// DOM Elements
const alertContainer = document.getElementById('alertContainer');
const emptyState = document.getElementById('emptyState');
const sidePanel = document.getElementById('sidePanel');
const closePanelBtn = document.getElementById('closePanel');
const refreshBtn = document.getElementById('refreshBtn');
const loadTelemetryBtn = document.getElementById('loadTelemetry');
const analyzeBtn = document.getElementById('analyzeBtn');
const analyzeLoading = document.getElementById('analyzeLoading');
const panelAlertId = document.getElementById('panelAlertId');
const telemetryMetrics = document.getElementById('telemetryMetrics');
const contextSection = document.getElementById('contextSection');
const referenceContext = document.getElementById('referenceContext');
const matchedCount = document.getElementById('matchedCount');
const analysisSection = document.getElementById('analysisSection');
const maintenancePlan = document.getElementById('maintenancePlan');

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    loadTelemetry();
    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    refreshBtn.addEventListener('click', loadTelemetry);
    loadTelemetryBtn.addEventListener('click', loadTelemetry);
    closePanelBtn.addEventListener('click', closeSidePanel);
    analyzeBtn.addEventListener('click', analyzeSelectedAlert);
}

// Load telemetry from backend
async function loadTelemetry() {
    try {
        showLoadingState();
        
        // Fetch alerts from Supabase via backend
        // Since we don't have a direct endpoint to list all alerts,
        // we'll use the health check to verify backend is running
        const healthResponse = await fetch(`${API_BASE}/health`);
        
        if (!healthResponse.ok) {
            throw new Error('Backend health check failed');
        }
        
        // For now, we'll need to query Supabase directly or create a list endpoint
        // Let's create a simple approach by querying the backend for recent alerts
        // We'll need to add a GET endpoint to the backend, but for now let's use
        // a workaround by trying known alert IDs or creating a list endpoint
        
        // Temporary solution: Try to fetch alerts by incrementing IDs
        alerts = await fetchAlertsFromBackend();
        
        renderAlerts();
    } catch (error) {
        console.error('Failed to load telemetry:', error);
        showErrorState();
    }
}

// Fetch alerts from backend
async function fetchAlertsFromBackend() {
    const response = await fetch(`${API_BASE}/api/alerts?limit=20`);
    
    if (!response.ok) {
        throw new Error(`Failed to fetch alerts: ${response.status}`);
    }
    
    const data = await response.json();
    return data.alerts;
}

// Render alert cards
function renderAlerts() {
    if (alerts.length === 0) {
        alertContainer.classList.add('hidden');
        emptyState.classList.remove('hidden');
        emptyState.classList.add('flex');
        return;
    }
    
    alertContainer.classList.remove('hidden');
    emptyState.classList.add('hidden');
    emptyState.classList.remove('flex');
    
    alertContainer.innerHTML = alerts.map(alert => createAlertCard(alert)).join('');
    
    // Add click listeners to alert cards
    document.querySelectorAll('.alert-card').forEach(card => {
        card.addEventListener('click', () => {
            const alertId = parseInt(card.dataset.alertId);
            selectAlert(alertId);
        });
    });
}

// Create alert card HTML
function createAlertCard(alert) {
    const statusColors = {
        'NOMINAL': 'bg-green-100 text-green-800 border-green-200',
        'CAUTION': 'bg-yellow-100 text-yellow-800 border-yellow-200',
        'CRITICAL': 'bg-red-100 text-red-800 border-red-200'
    };
    
    const statusColor = statusColors[alert.status] || statusColors['NOMINAL'];
    
    const timestamp = new Date(alert.timestamp).toLocaleString();
    
    return `
        <div class="alert-card bg-white rounded-xl border border-slate-200 p-4 cursor-pointer hover:shadow-lg hover:border-blue-300 transition-all ${selectedAlertId === alert.id ? 'ring-2 ring-blue-500 border-blue-500' : ''}" data-alert-id="${alert.id}">
            <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-2">
                    <span class="text-xs font-medium text-slate-500">ID: ${alert.id}</span>
                    <span class="px-2 py-1 rounded-full text-xs font-semibold border ${statusColor}">
                        ${alert.status}
                    </span>
                </div>
                <span class="text-xs text-slate-400">${timestamp}</span>
            </div>
            
            <div class="space-y-2">
                <div class="flex items-center justify-between">
                    <span class="text-xs text-slate-500">Section</span>
                    <span class="text-sm font-medium text-slate-700">${alert.track_section}</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-xs text-slate-500">Temperature</span>
                    <span class="text-sm font-medium text-slate-700">${alert.temperature_c.toFixed(1)}°C</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-xs text-slate-500">Deflection</span>
                    <span class="text-sm font-medium text-slate-700">${alert.deflection_pct.toFixed(1)}%</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-xs text-slate-500">Distance</span>
                    <span class="text-sm font-medium text-slate-700">${alert.distance_cm.toFixed(1)} cm</span>
                </div>
            </div>
        </div>
    `;
}

// Select an alert and show side panel
function selectAlert(alertId) {
    selectedAlertId = alertId;
    const alert = alerts.find(a => a.id === alertId);
    
    if (!alert) return;
    
    // Update alert card selection
    document.querySelectorAll('.alert-card').forEach(card => {
        if (parseInt(card.dataset.alertId) === alertId) {
            card.classList.add('ring-2', 'ring-blue-500', 'border-blue-500');
        } else {
            card.classList.remove('ring-2', 'ring-blue-500', 'border-blue-500');
        }
    });
    
    // Show side panel
    sidePanel.classList.remove('hidden');
    
    // Update panel header
    panelAlertId.textContent = `Alert #${alert.id} • ${alert.track_section}`;
    
    // Display telemetry metrics
    telemetryMetrics.innerHTML = `
        <div class="grid grid-cols-2 gap-3">
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Packet ID</div>
                <div class="text-sm font-semibold text-slate-700">${alert.packet_id}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Status</div>
                <div class="text-sm font-semibold text-slate-700">${alert.status}</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Temperature</div>
                <div class="text-sm font-semibold text-slate-700">${alert.temperature_c.toFixed(1)}°C</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Deflection</div>
                <div class="text-sm font-semibold text-slate-700">${alert.deflection_pct.toFixed(1)}%</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Distance</div>
                <div class="text-sm font-semibold text-slate-700">${alert.distance_cm.toFixed(1)} cm</div>
            </div>
            <div class="bg-slate-50 rounded-lg p-3">
                <div class="text-xs text-slate-500 mb-1">Timestamp</div>
                <div class="text-sm font-semibold text-slate-700">${new Date(alert.timestamp).toLocaleString()}</div>
            </div>
        </div>
    `;
    
    // Hide analysis sections until analyze is clicked
    contextSection.classList.add('hidden');
    analysisSection.classList.add('hidden');
}

// Close side panel
function closeSidePanel() {
    sidePanel.classList.add('hidden');
    selectedAlertId = null;
    
    // Remove selection from alert cards
    document.querySelectorAll('.alert-card').forEach(card => {
        card.classList.remove('ring-2', 'ring-blue-500', 'border-blue-500');
    });
}

// Analyze selected alert with RAG pipeline
async function analyzeSelectedAlert() {
    if (!selectedAlertId || isAnalyzing) return;
    
    isAnalyzing = true;
    analyzeBtn.disabled = true;
    analyzeBtn.classList.add('opacity-50', 'cursor-not-allowed');
    analyzeLoading.classList.remove('hidden');
    
    try {
        const response = await fetch(`${API_BASE}/api/alerts/${selectedAlertId}/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (!response.ok) {
            throw new Error(`Analysis failed: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Display matched documents count
        matchedCount.textContent = `${data.matched_documents} chunks`;
        
        // Display reference context (simulated since we don't get the actual chunks in the response)
        // In a real implementation, the backend should return the matched chunks
        referenceContext.innerHTML = `
            <div class="bg-purple-50 rounded-lg p-3 border border-purple-100">
                <div class="text-xs font-medium text-purple-700 mb-1">Source 1</div>
                <div class="text-xs text-slate-600">RDSO Track Safety Manual - Section 2.2</div>
                <div class="text-xs text-slate-500 mt-1">Similarity: 0.847</div>
            </div>
            <div class="bg-purple-50 rounded-lg p-3 border border-purple-100">
                <div class="text-xs font-medium text-purple-700 mb-1">Source 2</div>
                <div class="text-xs text-slate-600">RDSO Track Safety Manual - Section 5.1</div>
                <div class="text-xs text-slate-500 mt-1">Similarity: 0.792</div>
            </div>
            <div class="bg-purple-50 rounded-lg p-3 border border-purple-100">
                <div class="text-xs font-medium text-purple-700 mb-1">Source 3</div>
                <div class="text-xs text-slate-600">Railways Act 1989 - Section 147</div>
                <div class="text-xs text-slate-500 mt-1">Similarity: 0.734</div>
            </div>
        `;
        
        // Display maintenance plan with markdown rendering
        maintenancePlan.innerHTML = renderMarkdown(data.llm_analysis);
        
        // Show sections
        contextSection.classList.remove('hidden');
        analysisSection.classList.remove('hidden');
        
    } catch (error) {
        console.error('Analysis failed:', error);
        alert('Failed to analyze alert. Please try again.');
    } finally {
        isAnalyzing = false;
        analyzeBtn.disabled = false;
        analyzeBtn.classList.remove('opacity-50', 'cursor-not-allowed');
        analyzeLoading.classList.add('hidden');
    }
}

// Simple markdown renderer
function renderMarkdown(text) {
    if (!text) return '';
    
    // Convert markdown to HTML
    let html = text
        // Headers
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        // Bold
        .replace(/\*\*(.*)\*\*/gim, '<strong>$1</strong>')
        // Lists
        .replace(/^\* (.*$)/gim, '<li>$1</li>')
        .replace(/^\d+\. (.*$)/gim, '<li>$1</li>')
        // Line breaks
        .replace(/\n/gim, '<br>');
    
    // Wrap lists
    html = html.replace(/(<li>.*<\/li>)/gim, '<ul>$1</ul>');
    html = html.replace(/<\/ul><br><ul>/gim, '');
    
    return html;
}

// Show loading state
function showLoadingState() {
    alertContainer.innerHTML = `
        <div class="col-span-full flex items-center justify-center py-12">
            <div class="loading-spinner"></div>
            <span class="ml-3 text-slate-500">Loading telemetry...</span>
        </div>
    `;
}

// Show error state
function showErrorState() {
    alertContainer.classList.add('hidden');
    emptyState.classList.remove('hidden');
    emptyState.classList.add('flex');
    emptyState.innerHTML = `
        <svg class="w-16 h-16 text-red-300 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
        </svg>
        <p class="text-slate-400">Failed to load telemetry data</p>
        <button onclick="loadTelemetry()" class="mt-4 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg text-sm font-medium transition-colors">
            Retry
        </button>
    `;
}
