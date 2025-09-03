/**
 * Access management JavaScript for FAB
 * Handles access opening/closing and status updates
 */

document.addEventListener('DOMContentLoaded', function() {
    const accessForm = document.getElementById('accessForm');
    const closeButtons = document.querySelectorAll('.close-access');
    
    // Handle access form submission
    if (accessForm) {
        accessForm.addEventListener('submit', handleAccessFormSubmit);
    }
    
    // Handle close access buttons
    closeButtons.forEach(button => {
        button.addEventListener('click', handleCloseAccess);
    });
    
    // Start status polling for active accesses
    if (closeButtons.length > 0) {
        startStatusPolling();
    }
    
    // Start countdown timers for active accesses
    startCountdownTimers();
    
    // Convert timestamps to local time
    convertTimestampsToLocalTime();
});

async function handleAccessFormSubmit(e) {
    e.preventDefault();
    
    const form = e.target;
    const submitButton = form.querySelector('button[type="submit"]');
    const token = document.getElementById('sessionToken').value;
    const duration = parseInt(document.getElementById('duration').value);
    
    if (!duration) {
        FAB.showMessage('Пожалуйста, выберите время доступа', 'warning');
        return;
    }
    
    // Show loading state
    FAB.setButtonLoading(submitButton, true);
    
    try {
        const result = await FAB.apiRequest(`${FAB.API.OPEN_ACCESS}/${token}`, {
            method: 'POST',
            body: JSON.stringify({
                duration: duration
            })
        });
        
        if (result.success) {
            FAB.showMessage(
                `✅ Доступ успешно открыт на ${FAB.formatDuration(duration)}!`, 
                'success'
            );
            
            // Refresh page after 2 seconds to show active access
            setTimeout(() => {
                window.location.reload();
            }, 2000);
        } else {
            FAB.showMessage(`❌ Ошибка: ${result.error}`, 'danger');
        }
    } catch (error) {
        FAB.showMessage(`❌ Произошла ошибка: ${error.message}`, 'danger');
    } finally {
        FAB.setButtonLoading(submitButton, false);
    }
}

async function handleCloseAccess(e) {
    const button = e.target.closest('.close-access');
    const accessId = button.getAttribute('data-access-id');
    const token = document.getElementById('sessionToken')?.value;
    
    if (!accessId) {
        FAB.showMessage('❌ Не удалось определить ID доступа', 'danger');
        return;
    }
    
    // Show confirmation
    if (!confirm('Вы уверены, что хотите закрыть доступ?')) {
        return;
    }
    
    // Show loading state
    FAB.setButtonLoading(button, true);
    
    try {
        const requestData = {};
        if (token) {
            requestData.token = token;
        }
        
        const result = await FAB.apiRequest(`${FAB.API.CLOSE_ACCESS}/${accessId}`, {
            method: 'POST',
            body: JSON.stringify(requestData)
        });
        
        if (result.success) {
            FAB.showMessage('✅ Доступ успешно закрыт!', 'success');
            
            // Remove the access card or refresh page
            const accessCard = button.closest('.d-flex');
            if (accessCard) {
                accessCard.style.transition = 'opacity 0.3s ease';
                accessCard.style.opacity = '0';
                setTimeout(() => {
                    accessCard.remove();
                    
                    // Check if no more active accesses
                    const remainingAccesses = document.querySelectorAll('.close-access');
                    if (remainingAccesses.length === 0) {
                        const activeCard = document.querySelector('.active-access');
                        if (activeCard) {
                            activeCard.style.display = 'none';
                        }
                    }
                }, 300);
            }
        } else {
            FAB.showMessage(`❌ Ошибка: ${result.error}`, 'danger');
        }
    } catch (error) {
        FAB.showMessage(`❌ Произошла ошибка: ${error.message}`, 'danger');
    } finally {
        FAB.setButtonLoading(button, false);
    }
}

function startStatusPolling() {
    // Poll for status updates every 30 seconds
    setInterval(checkAccessStatus, 30000);
}

async function checkAccessStatus() {
    const accessCards = document.querySelectorAll('.close-access');
    
    for (const button of accessCards) {
        const accessId = button.getAttribute('data-access-id');
        if (!accessId) continue;
        
        try {
            const result = await FAB.apiRequest(`${FAB.API.STATUS}/${accessId}`);
            
            if (result.success) {
                const status = result.data;
                
                // Check if access expired or was closed
                if (status.status === 'closed' || status.is_expired) {
                    const accessCard = button.closest('.d-flex');
                    if (accessCard) {
                        // Update UI to show closed status
                        const statusIndicator = accessCard.querySelector('.status-indicator');
                        if (statusIndicator) {
                            statusIndicator.classList.remove('status-open');
                            statusIndicator.classList.add('status-closed');
                        }
                        
                        // Update text
                        const statusText = accessCard.querySelector('strong');
                        if (statusText) {
                            statusText.textContent = status.is_expired ? 'Доступ истек' : 'Доступ закрыт';
                        }
                        
                        // Disable close button
                        button.disabled = true;
                        button.innerHTML = '<i class="bi bi-check"></i> Закрыт';
                        button.classList.remove('btn-danger');
                        button.classList.add('btn-secondary');
                    }
                }
            }
        } catch (error) {
            console.error(`Error checking status for access ${accessId}:`, error);
        }
    }
}

function startCountdownTimers() {
    const timers = document.querySelectorAll('.countdown-timer[data-expires]');
    
    if (timers.length === 0) return;
    
    // Update all timers immediately
    updateCountdownTimers();
    
    // Update timers every second
    setInterval(updateCountdownTimers, 1000);
}

function updateCountdownTimers() {
    const timers = document.querySelectorAll('.countdown-timer[data-expires]');
    
    timers.forEach(timer => {
        const expiresTimestamp = parseFloat(timer.getAttribute('data-expires'));
        const expiresAt = new Date(expiresTimestamp * 1000); // Convert seconds to milliseconds
        const now = new Date();
        const remainingMs = expiresAt.getTime() - now.getTime();
        
        if (remainingMs <= 0) {
            // Timer expired
            timer.innerHTML = '<i class="bi bi-clock-history"></i> Истек';
            timer.classList.add('danger');
            
            // Trigger status check for this access
            const accessId = timer.getAttribute('data-access-id');
            if (accessId) {
                checkSingleAccessStatus(accessId);
            }
        } else {
            // Format and display remaining time
            const formatted = formatCountdown(remainingMs);
            timer.innerHTML = `<i class="bi bi-clock"></i> ${formatted}`;
            
            // Update styling based on remaining time
            updateTimerStyling(timer, remainingMs);
        }
    });
}

function formatCountdown(remainingMs) {
    const totalSeconds = Math.floor(remainingMs / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    
    if (hours > 0) {
        return `${hours}ч ${minutes.toString().padStart(2, '0')}м ${seconds.toString().padStart(2, '0')}с`;
    } else if (minutes > 0) {
        return `${minutes}м ${seconds.toString().padStart(2, '0')}с`;
    } else {
        return `${seconds}с`;
    }
}

function updateTimerStyling(timer, remainingMs) {
    const remainingMinutes = remainingMs / (1000 * 60);
    
    // Remove existing classes
    timer.classList.remove('warning', 'danger');
    
    if (remainingMinutes <= 2) {
        // Less than 2 minutes - danger (red, pulsing)
        timer.classList.add('danger');
    } else if (remainingMinutes <= 10) {
        // Less than 10 minutes - warning (orange)
        timer.classList.add('warning');
    }
    // More than 10 minutes - default green styling
}

async function checkSingleAccessStatus(accessId) {
    try {
        const result = await FAB.apiRequest(`${FAB.API.STATUS}/${accessId}`);
        
        if (result.success) {
            const status = result.data;
            
            // Check if access expired or was closed
            if (status.status === 'closed' || status.is_expired) {
                const accessCard = document.querySelector(`[data-access-id="${accessId}"]`).closest('.d-flex');
                const closeButton = document.querySelector(`.close-access[data-access-id="${accessId}"]`);
                
                if (accessCard && closeButton) {
                    // Update UI to show closed status
                    const statusIndicator = accessCard.querySelector('.status-indicator');
                    if (statusIndicator) {
                        statusIndicator.classList.remove('status-open');
                        statusIndicator.classList.add('status-closed');
                    }
                    
                    // Update text
                    const statusText = accessCard.querySelector('strong');
                    if (statusText) {
                        statusText.textContent = status.is_expired ? 'Доступ истек' : 'Доступ закрыт';
                    }
                    
                    // Disable close button
                    closeButton.disabled = true;
                    closeButton.innerHTML = '<i class="bi bi-check"></i> Закрыт';
                    closeButton.classList.remove('btn-danger');
                    closeButton.classList.add('btn-secondary');
                    
                    // Hide countdown timer
                    const timer = document.getElementById(`countdown-${accessId}`);
                    if (timer) {
                        timer.style.display = 'none';
                    }
                }
            }
        }
    } catch (error) {
        console.error(`Error checking status for access ${accessId}:`, error);
    }
}

function convertTimestampsToLocalTime() {
    const timeElements = document.querySelectorAll('.local-time[data-timestamp]');
    
    timeElements.forEach(element => {
        const timestamp = parseFloat(element.getAttribute('data-timestamp'));
        if (!timestamp || isNaN(timestamp)) {
            element.textContent = 'Неизвестно';
            return;
        }
        
        // Convert timestamp (seconds) to milliseconds and create Date object
        const date = new Date(timestamp * 1000);
        
        // Format to local time with full date and time
        const localTime = formatLocalDateTime(date);
        element.textContent = localTime;
    });
}

function formatLocalDateTime(date) {
    const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false
    };
    
    const formatter = new Intl.DateTimeFormat('ru-RU', options);
    return formatter.format(date);
}

// Export functions for potential external use
window.AccessManager = {
    handleAccessFormSubmit,
    handleCloseAccess,
    checkAccessStatus,
    startCountdownTimers,
    updateCountdownTimers,
    convertTimestampsToLocalTime,
    formatLocalDateTime
};
