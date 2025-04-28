// Main JavaScript file for Text Adventure Builder Store

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltips = document.querySelectorAll('.tooltip');
    tooltips.forEach(tooltip => {
        new bootstrap.Tooltip(tooltip);
    });

    // Rating system
    const ratingStars = document.querySelectorAll('.rating-form .rating i');
    if (ratingStars.length > 0) {
        ratingStars.forEach(star => {
            star.addEventListener('click', function() {
                const value = this.getAttribute('data-value');
                document.getElementById('rating-value').value = value;
                
                // Update visual stars
                ratingStars.forEach(s => {
                    const starValue = s.getAttribute('data-value');
                    if (starValue <= value) {
                        s.classList.remove('far');
                        s.classList.add('fas');
                    } else {
                        s.classList.remove('fas');
                        s.classList.add('far');
                    }
                });
            });
            
            star.addEventListener('mouseover', function() {
                const value = this.getAttribute('data-value');
                
                // Update visual stars on hover
                ratingStars.forEach(s => {
                    const starValue = s.getAttribute('data-value');
                    if (starValue <= value) {
                        s.classList.remove('far');
                        s.classList.add('fas');
                    } else {
                        s.classList.remove('fas');
                        s.classList.add('far');
                    }
                });
            });
            
            star.addEventListener('mouseout', function() {
                const currentValue = document.getElementById('rating-value').value;
                
                // Reset to current value on mouseout
                ratingStars.forEach(s => {
                    const starValue = s.getAttribute('data-value');
                    if (starValue <= currentValue) {
                        s.classList.remove('far');
                        s.classList.add('fas');
                    } else {
                        s.classList.remove('fas');
                        s.classList.add('far');
                    }
                });
            });
        });
    }

    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
        themeToggle.addEventListener('click', function() {
            document.body.classList.toggle('dark-theme');
            
            // Save preference if admin
            if (document.body.classList.contains('admin-page')) {
                const theme = document.body.classList.contains('dark-theme') ? 'dark' : 'light';
                
                fetch('/admin/settings', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: `theme=${theme}`
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showAlert('Theme updated successfully', 'success');
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                });
            }
        });
    }

    // File upload validation
    const adventureFileInput = document.getElementById('adventure-file');
    if (adventureFileInput) {
        adventureFileInput.addEventListener('change', function() {
            const filePath = this.value;
            const allowedExtensions = /(\.zip)$/i;
            
            if (!allowedExtensions.exec(filePath)) {
                showAlert('Please upload a zip file only', 'danger');
                this.value = '';
                return false;
            }
            
            // Check file size (max 50MB)
            if (this.files[0].size > 50 * 1024 * 1024) {
                showAlert('File size exceeds 50MB limit', 'danger');
                this.value = '';
                return false;
            }
        });
    }

    // Initialize charts if on admin stats page
    if (document.getElementById('stats-page')) {
        initializeCharts();
        initializeApiUsageChart(); // Call the new function
    }

    // Alert auto-close
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            alert.classList.add('fade');
            setTimeout(() => {
                alert.remove();
            }, 500);
        }, 5000);
    });
});

// Function to show alerts
function showAlert(message, type) {
    const alertContainer = document.getElementById('alert-container');
    if (!alertContainer) return;
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type} fade-in`;
    alert.innerHTML = message;
    
    alertContainer.appendChild(alert);
    
    setTimeout(() => {
        alert.classList.add('fade');
        setTimeout(() => {
            alert.remove();
        }, 500);
    }, 5000);
}

// Function to initialize charts
function initializeCharts() {
    // User roles chart
    if (document.getElementById('user-roles-chart')) {
        const ctx = document.getElementById('user-roles-chart').getContext('2d');
        const userRolesData = JSON.parse(document.getElementById('user-roles-data').textContent);
        
        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: userRolesData.labels,
                datasets: [{
                    data: userRolesData.data,
                    backgroundColor: [
                        'rgba(106, 17, 203, 0.8)',
                        'rgba(37, 117, 252, 0.8)',
                        'rgba(255, 193, 7, 0.8)'
                    ],
                    borderColor: [
                        'rgba(106, 17, 203, 1)',
                        'rgba(37, 117, 252, 1)',
                        'rgba(255, 193, 7, 1)'
                    ],
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        }
                    }
                }
            }
        });
    }
    
    // Tag usage chart
    if (document.getElementById('tag-usage-chart')) {
        const ctx = document.getElementById('tag-usage-chart').getContext('2d');
        const tagUsageData = JSON.parse(document.getElementById('tag-usage-data').textContent);
        
        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: tagUsageData.labels,
                datasets: [{
                    label: 'Number of Adventures',
                    data: tagUsageData.data,
                    backgroundColor: 'rgba(37, 117, 252, 0.8)',
                    borderColor: 'rgba(37, 117, 252, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        },
                        grid: {
                            color: 'rgba(200, 200, 200, 0.1)'
                        }
                    },
                    x: {
                        ticks: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        },
                        grid: {
                            color: 'rgba(200, 200, 200, 0.1)'
                        }
                    }
                },
                plugins: {
                    legend: {
                        labels: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        }
                    }
                }
            }
        });
    }
    
    // Daily stats chart
    if (document.getElementById('daily-stats-chart')) {
        const ctx = document.getElementById('daily-stats-chart').getContext('2d');
        const dailyStatsData = JSON.parse(document.getElementById('daily-stats-data').textContent);
        
        new Chart(ctx, {
            type: 'line',
            data: {
                // Use the 'days' array from one of the stats (assuming they are the same)
                labels: dailyStatsData.page_views.days, 
                datasets: [
                    {
                        label: 'Page Views',
                        data: dailyStatsData.page_views.values,
                        borderColor: 'rgba(106, 17, 203, 1)',
                        backgroundColor: 'rgba(106, 17, 203, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Logins',
                        data: dailyStatsData.logins.values,
                        borderColor: 'rgba(37, 117, 252, 1)',
                        backgroundColor: 'rgba(37, 117, 252, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Registrations',
                        data: dailyStatsData.registrations.values,
                        borderColor: 'rgba(255, 193, 7, 1)', // Example color, adjust as needed
                        backgroundColor: 'rgba(255, 193, 7, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Downloads',
                        data: dailyStatsData.downloads.values,
                        borderColor: 'rgba(40, 167, 69, 1)',
                        backgroundColor: 'rgba(40, 167, 69, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Uploads',
                        data: dailyStatsData.uploads.values,
                        borderColor: 'rgba(255, 193, 7, 1)',
                        backgroundColor: 'rgba(255, 193, 7, 0.1)',
                        tension: 0.4,
                        fill: true
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        },
                        grid: {
                            color: 'rgba(200, 200, 200, 0.1)'
                        }
                    },
                    x: {
                        ticks: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        },
                        grid: {
                            color: 'rgba(200, 200, 200, 0.1)'
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: getComputedStyle(document.documentElement).getPropertyValue('--text-color')
                        }
                    }
                }
            }
        });
    }
}

// Function to initialize API Usage Chart
function initializeApiUsageChart() {
    if (document.getElementById('api-usage-chart')) {
        const ctx = document.getElementById('api-usage-chart').getContext('2d');
        const apiUsageDataRaw = JSON.parse(document.getElementById('api-usage-data').textContent);

        // --- Data Processing for Chart.js ---
        // We need a consistent timeline (last 30 days) and datasets for each key (success/failure)
        const labels = []; // Array of dates for the X-axis
        const datasets = [];
        const today = new Date();
        const colors = [ // Define some colors for different keys
            { success: 'rgba(40, 167, 69, 0.8)', failure: 'rgba(220, 53, 69, 0.8)' }, // Green/Red
            { success: 'rgba(37, 117, 252, 0.8)', failure: 'rgba(255, 193, 7, 0.8)' }, // Blue/Yellow
            { success: 'rgba(106, 17, 203, 0.8)', failure: 'rgba(23, 162, 184, 0.8)' }, // Purple/Teal
            { success: 'rgba(253, 126, 20, 0.8)', failure: 'rgba(108, 117, 125, 0.8)' }, // Orange/Gray
        ];
        let colorIndex = 0;

        // Generate labels for the last 30 days
        for (let i = 29; i >= 0; i--) {
            const date = new Date(today);
            date.setDate(today.getDate() - i);
            labels.push(date.toISOString().split('T')[0]); // Format as YYYY-MM-DD
        }

        // Process data for each API key
        for (const keyName in apiUsageDataRaw) {
            const keyData = apiUsageDataRaw[keyName];
            const successData = new Array(30).fill(0); // Initialize with zeros
            const failureData = new Array(30).fill(0);

            // Map the fetched counts to the correct date index
            for (let i = 0; i < keyData.days.length; i++) {
                const day = keyData.days[i];
                const index = labels.indexOf(day);
                if (index !== -1) {
                    // Assuming success/failure arrays align with days array
                    if (keyData.success[i] !== undefined) successData[index] = keyData.success[i];
                    if (keyData.failure[i] !== undefined) failureData[index] = keyData.failure[i];
                }
            }

            const keyColors = colors[colorIndex % colors.length];
            colorIndex++;

            datasets.push({
                label: `${keyName} - Success`,
                data: successData,
                borderColor: keyColors.success,
                backgroundColor: keyColors.success.replace('0.8', '0.1'), // Lighter fill
                tension: 0.1,
                fill: false, // Or true if you want area chart
                type: 'line', // Can mix types, e.g., line for success, bar for failure
            });
            datasets.push({
                label: `${keyName} - Failure`,
                data: failureData,
                borderColor: keyColors.failure,
                backgroundColor: keyColors.failure.replace('0.8', '0.1'),
                tension: 0.1,
                fill: false,
                type: 'line',
            });
        }

        // --- Create Chart ---
        new Chart(ctx, {
            data: { labels: labels, datasets: datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: { y: { beginAtZero: true, ticks: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') }, grid: { color: 'rgba(200, 200, 200, 0.1)' } }, x: { ticks: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') }, grid: { color: 'rgba(200, 200, 200, 0.1)' } } },
                plugins: { legend: { position: 'bottom', labels: { color: getComputedStyle(document.documentElement).getPropertyValue('--text-color') } } }
            }
        });
    }
}
