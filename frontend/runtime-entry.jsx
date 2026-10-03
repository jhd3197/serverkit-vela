// Runtime-ESM entry for ServerKit's no-rebuild loader (same pattern as
// serverkit-gui). Same exports as index.js, but the CSS is imported as a
// STRING (?inline) and injected at module load, so the single dist/index.mjs
// the panel blob-imports carries its own styles. Shared libs are externalized
// by vite.config and resolved to the panel's singletons via its import map.
import css from './styles/vela.css?inline';
import VelaPage from './components/VelaPage.jsx';

// Translations. Registered against the PANEL's i18next singleton, additively
// and under this extension's own `vela` namespace — never init() or
// changeLanguage(), which the panel owns. The English bundle mirrors the
// inline t('key', 'English') defaults, so a key with no bundle still renders
// its default.
import i18next from 'i18next';
import en from './locales/en.json';
import es from './locales/es.json';

for (const [language, bundle] of Object.entries({ en, es })) {
    i18next.addResourceBundle(language, 'translation', bundle, true, false);
}

if (typeof document !== 'undefined' && !document.getElementById('serverkit-vela-styles')) {
    const style = document.createElement('style');
    style.id = 'serverkit-vela-styles';
    style.textContent = css;
    document.head.appendChild(style);
}

export { VelaPage as VelaExtension };
