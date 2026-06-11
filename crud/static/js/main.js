document.addEventListener('DOMContentLoaded', function () {
  const themeToggle = document.getElementById('theme-toggle');
  const themeCss = document.getElementById('theme-css');
  const themeIcon = themeToggle?.querySelector('i');

  // Función para aplicar tema
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      if (themeIcon) themeIcon.className = 'bi bi-moon-fill';
      document.body.classList.remove('light-theme');
      document.body.classList.add('dark-theme');
    } else {
      if (themeIcon) themeIcon.className = 'bi bi-sun-fill';
      document.body.classList.remove('dark-theme');
      document.body.classList.add('light-theme');
    }
  }

  // Cargar tema guardado o usar el tema preferido del usuario
  let savedTheme = localStorage.getItem('theme');
  if (IS_AUTHENTICATED) {
    // Si el usuario está autenticado, usar su preferencia de la base de datos
    savedTheme = USER_THEME === 1 ? 'dark' : 'light';
  } else {
    // Si no está autenticado, usar el tema guardado en localStorage o light por defecto
    savedTheme = savedTheme || 'dark';
  }
  applyTheme(savedTheme);

  // Cambiar tema al hacer click
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      let currentTheme = document.documentElement.getAttribute('data-theme');
      let newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(newTheme);
      localStorage.setItem('theme', newTheme);
      
      // Si el usuario está autenticado, guardar la preferencia en la base de datos
      if (IS_AUTHENTICATED) {
        fetch(UPDATE_THEME_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
          },
          body: `tema=${newTheme}`
        });
      }
    });
  } else {
    // Si no está el toggle (usuario no logueado), forzar oscuro
    applyTheme('dark');
  }
}); 