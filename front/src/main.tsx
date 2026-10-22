import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import { App } from './app/App.tsx';
import { withPublicBase } from './utils/publicBase';
import './index.css';
import { applyResolvedAppearance } from './theme/appearanceRuntime';
import { BUILTIN_THEME, resolveAppearance } from './theme/resolveAppearance';
import { readStoredUiTheme } from './theme';

readStoredUiTheme();
applyResolvedAppearance(resolveAppearance(BUILTIN_THEME));

document.documentElement.style.setProperty(
  "--workbench-empty-mask-image",
  `url("${withPublicBase("/assets/workbench-editor-empty-mask.png?v=20260531-2")}")`,
);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
