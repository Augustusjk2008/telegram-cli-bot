import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { App } from './app/App.tsx';
import './index.css';
import './theme/illustrations.css';
import { applyResolvedAppearance } from './theme/appearanceRuntime';
import { BUILTIN_THEME, resolveAppearance } from './theme/resolveAppearance';
import { readStoredUiTheme } from './theme';

readStoredUiTheme();
applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
