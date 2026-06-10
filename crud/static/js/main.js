// --- Lógica existente para confirmar el borrado ---
const btnDelete = document.querySelectorAll('.btn-borrar');
if (btnDelete) {
  const btnArray = Array.from(btnDelete);
  btnArray.forEach((btn) => {
    btn.addEventListener('click', (e) => {
      if (!confirm('¿Está seguro de querer borrar?')) {
        e.preventDefault();
      }
    });
  });
}

// --- Nueva lógica para el Selector de Tema Claro/Oscuro ---
document.addEventListener('DOMContentLoaded', () => {
  const themeLink = document.getElementById('theme-link');
  const themeSelect = document.getElementById('theme-select');

  // URLs de las hojas de estilo de Bootswatch
  const themes = {
    light: 'https://bootswatch.com/5/flatly/bootstrap.min.css',
    dark:  'https://bootswatch.com/5/darkly/bootstrap.min.css'
  };

  // 1. Cargar la preferencia almacenada (por defecto 'light' según la consigna)
  const savedTheme = localStorage.getItem('theme') || 'light';
  themeLink.setAttribute('href', themes[savedTheme]);

  // 2. Si el selector existe en pantalla (solo para usuarios logueados), sincronizar su valor
  if (themeSelect) {
    themeSelect.value = savedTheme;

    // 3. Escuchar cuando el usuario cambia la opción del desplegable
    themeSelect.addEventListener('change', (e) => {
      const selectedTheme = e.target.value; // Puede ser 'light' o 'dark'
      
      // Aplicar el nuevo archivo CSS de Bootswatch
      themeLink.setAttribute('href', themes[selectedTheme]);
      
      // Guardar la elección para que persista al navegar por el CRUD
      localStorage.setItem('theme', selectedTheme);
    });
  }
});