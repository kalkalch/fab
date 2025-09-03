/**
 * Main JavaScript file for FAB - Firewall Access Bot
 * Provides common functionality and utilities
 */

// Global utilities
const FAB = {
    // API endpoints
    API: {
        OPEN_ACCESS: '/a',
        CLOSE_ACCESS: '/c',
        STATUS: '/s'
    },

    // Show notification message
    showMessage: function(message, type = 'info', container = '#statusMessages') {
        const alertClass = `alert alert-${type}`;
        const iconClass = this.getIconClass(type);
        
        const messageHtml = `
            <div class="${alertClass} alert-dismissible fade show message fade-in" role="alert">
                <i class="${iconClass}"></i> ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        
        const container_elem = document.querySelector(container);
        if (container_elem) {
            container_elem.innerHTML = messageHtml;
            
            // Auto-hide after 5 seconds
            setTimeout(() => {
                const alert = container_elem.querySelector('.alert');
                if (alert) {
                    const bsAlert = new bootstrap.Alert(alert);
                    bsAlert.close();
                }
            }, 5000);
        }
    },

    // Get appropriate icon class for message type
    getIconClass: function(type) {
        const icons = {
            'success': 'bi bi-check-circle',
            'error': 'bi bi-exclamation-triangle',
            'warning': 'bi bi-exclamation-triangle',
            'info': 'bi bi-info-circle',
            'danger': 'bi bi-x-circle'
        };
        return icons[type] || icons['info'];
    },

    // Format duration in human readable format
    formatDuration: function(seconds) {
        if (seconds < 60) {
            return `${seconds} сек`;
        } else if (seconds < 3600) {
            return `${Math.floor(seconds / 60)} мин`;
        } else {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return minutes > 0 ? `${hours} ч ${minutes} мин` : `${hours} ч`;
        }
    },

    // Format datetime
    formatDateTime: function(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('ru-RU', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    },

    // Show loading state for button
    setButtonLoading: function(button, loading = true) {
        if (loading) {
            button.disabled = true;
            const originalText = button.innerHTML;
            button.setAttribute('data-original-text', originalText);
            button.innerHTML = '<span class="loading"></span> Загрузка...';
        } else {
            button.disabled = false;
            const originalText = button.getAttribute('data-original-text');
            if (originalText) {
                button.innerHTML = originalText;
                button.removeAttribute('data-original-text');
            }
        }
    },

    // Make API request
    apiRequest: async function(url, options = {}) {
        const defaultOptions = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
            }
        };

        const config = { ...defaultOptions, ...options };

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            return { success: true, data };
        } catch (error) {
            console.error('API request failed:', error);
            return { success: false, error: error.message };
        }
    },

    // Initialize common functionality
    init: function() {
        // Add smooth scrolling
        document.documentElement.style.scrollBehavior = 'smooth';

        // Add click handlers for close buttons in alerts
        document.addEventListener('click', function(e) {
            if (e.target.matches('.btn-close') || e.target.closest('.btn-close')) {
                const alert = e.target.closest('.alert');
                if (alert) {
                    const bsAlert = new bootstrap.Alert(alert);
                    bsAlert.close();
                }
            }
        });

        // Add form validation styling
        const forms = document.querySelectorAll('form');
        forms.forEach(form => {
            form.addEventListener('submit', function(e) {
                if (!form.checkValidity()) {
                    e.preventDefault();
                    e.stopPropagation();
                }
                form.classList.add('was-validated');
            });
        });

        console.log('FAB utilities initialized');
    }
};

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    FAB.init();
});

// Export FAB object for use in other scripts
window.FAB = FAB;
