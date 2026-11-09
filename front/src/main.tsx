import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { App } from './app/App.tsx';
import './index.css';
import './theme/illustrations.css';
import { applyResolvedAppearance } from './theme/appearanceRuntime';
import { BUILTIN_THEME, resolveAppearance } from './theme/resolveAppearance';
import { readStoredUiTheme } from './theme';

// A stale tab may request chunks removed by an upgrade; reload once to fetch the new bundle.
window.addEventListener('vite:preloadError', (event) => {
  const key = 'orbit:preload-reload-at';
  try {
    if (Date.now() - Number(sessionStorage.getItem(key) || 0) < 60_000) return;
    sessionStorage.setItem(key, String(Date.now()));
  } catch {
    return;
  }
  event.preventDefault();
  window.location.reload();
});

readStoredUiTheme();
applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
