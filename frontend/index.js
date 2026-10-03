// Plugin entry — discovered by ServerKit's PluginLoader / contributions.
// The named exports match the manifest's contributions.routes components.
import VelaPage from './components/VelaPage.jsx';
import VelaInstancePage from './components/VelaInstancePage.jsx';
import './styles/vela.css';

export { VelaPage as VelaExtension, VelaInstancePage as VelaInstanceExtension };
