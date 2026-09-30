// dashboard/src/utils/toast.js

export function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    
    // Trigger reflow to ensure the transition plays
    toast.offsetHeight;
    
    requestAnimationFrame(() => toast.classList.add('toast--visible'));
    
    setTimeout(() => {
        toast.classList.remove('toast--visible');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
