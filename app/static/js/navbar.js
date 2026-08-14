// Theme toggle functionality
function toggleTheme() {
    const currentTheme = localStorage.getItem('theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    localStorage.setItem('theme', newTheme);
    document.documentElement.setAttribute('data-theme', newTheme);
    updateThemeIcon(newTheme);
}

function updateThemeIcon(theme) {
    const lightIcon = document.getElementById('theme-icon-light');
    const darkIcon = document.getElementById('theme-icon-dark');
    
    if (lightIcon && darkIcon) {
        if (theme === 'dark') {
            lightIcon.classList.add('hidden');
            darkIcon.classList.remove('hidden');
        } else {
            lightIcon.classList.remove('hidden');
            darkIcon.classList.add('hidden');
        }
    }
}

// Initialize theme icon on page load
document.addEventListener('DOMContentLoaded', function() {
    const currentTheme = localStorage.getItem('theme') || 'light';
    updateThemeIcon(currentTheme);
});

// Privacy Mode toggle - purely client-side on/off switch, meant to be
// flipped quickly right before and after taking a screenshot. What it
// actually blurs is configured server-side via Admin > Platform Settings
// (see the data-privacy-fields attribute on <html>, rendered from
// AppSettings.privacy_fields_string()); this only controls whether that
// configured set is currently active.
const PRIVACY_MODE_KEY = 'algomirror_privacy_mode_on';

function togglePrivacyMode() {
    const isActive = document.documentElement.classList.toggle('privacy-active');
    localStorage.setItem(PRIVACY_MODE_KEY, isActive ? 'true' : 'false');
    updatePrivacyIcon(isActive);
}

function updatePrivacyIcon(isActive) {
    const offIcon = document.getElementById('privacy-icon-off');
    const onIcon = document.getElementById('privacy-icon-on');

    if (offIcon && onIcon) {
        if (isActive) {
            offIcon.classList.add('hidden');
            onIcon.classList.remove('hidden');
        } else {
            offIcon.classList.remove('hidden');
            onIcon.classList.add('hidden');
        }
    }
}

// Initialize privacy icon on page load - the class itself was already
// applied pre-paint in base.html's inline script (avoids a flash of
// unmasked content), this just syncs the icon to match.
document.addEventListener('DOMContentLoaded', function() {
    const isActive = document.documentElement.classList.contains('privacy-active');
    updatePrivacyIcon(isActive);
});