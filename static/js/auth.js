// static/js/auth.js
const USERS = {
    'admin@aeroflot.ru': {
        password: 'admin123',
        role: 'admin',
        name: 'Администратор системы',
        avatar: '👨‍💼'
    },
    'dispatcher@aeroflot.ru': {
        password: 'disp123',
        role: 'dispatcher',
        name: 'Иванов А.А.',
        avatar: '👨‍✈️',
        shift: 'Дневная смена'
    },
    'engineer@aeroflot.ru': {
        password: 'eng123',
        role: 'engineer',
        name: 'Петров С.А.',
        avatar: '🔧',
        specialization: 'Двигатели',
        id: 'eng_1'
    }
};

document.addEventListener('DOMContentLoaded', function() {
    const session = sessionStorage.getItem('userSession');
    if (session) {
        try {
            const user = JSON.parse(session);
            redirectToDashboard(user.role);
            return;
        } catch (e) {
            sessionStorage.removeItem('userSession');
        }
    }
    
    const form = document.getElementById('loginForm');
    if (form) {
        form.addEventListener('submit', handleLogin);
    }
});

function handleLogin(e) {
    e.preventDefault();
    
    const email = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value.trim();
    
    const user = USERS[email];
    
    if (!user || user.password !== password) {
        showError('Неверный email или пароль');
        return;
    }
    
    const userData = { ...user, email: email };
    delete userData.password;
    
    sessionStorage.setItem('userSession', JSON.stringify(userData));
    redirectToDashboard(user.role);
}

function redirectToDashboard(role) {
    const dashboards = {
        'admin': '/admin/dashboard.html',
        'dispatcher': '/dispatcher/dashboard.html',
        'engineer': '/engineer/dashboard.html'
    };
    window.location.href = dashboards[role] || '/login.html';
}

function showError(message) {
    const oldError = document.querySelector('.error-message');
    if (oldError) oldError.remove();
    
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-message';
    errorDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i><span>${message}</span>`;
    errorDiv.style.cssText = `
        background: #FFEBEE;
        color: #C62828;
        padding: 12px 16px;
        border-radius: 10px;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 14px;
        animation: fadeInUp 0.3s ease-out;
    `;
    
    const form = document.getElementById('loginForm');
    form.insertBefore(errorDiv, form.firstChild);
    
    setTimeout(() => {
        if (errorDiv.parentNode) errorDiv.remove();
    }, 4000);
}

function togglePassword() {
    const input = document.getElementById('password');
    const icon = document.querySelector('.toggle-password i');
    
    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'fas fa-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'fas fa-eye';
    }
}

function fillDemo(email, password) {
    document.getElementById('email').value = email;
    document.getElementById('password').value = password;
    
    const emailField = document.getElementById('email');
    const passField = document.getElementById('password');
    emailField.style.borderColor = '#4CAF50';
    passField.style.borderColor = '#4CAF50';
    
    setTimeout(() => {
        emailField.style.borderColor = '';
        passField.style.borderColor = '';
    }, 2000);
    
    setTimeout(() => {
        document.getElementById('loginForm').dispatchEvent(new Event('submit'));
    }, 500);
}

function logout() {
    sessionStorage.removeItem('userSession');
    window.location.href = '/login.html';
}