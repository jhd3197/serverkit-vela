// The panel's ApiClient via the SDK singleton (JWT refresh, workspace headers,
// error normalization included) — this file is the extension's own Vela API
// client, in the same shape as serverkit-wordpress's services/wordpress.js.
import { api } from 'serverkit-sdk';

const BASE_PATH = '/vela/instances';

export const velaApi = {
    listInstances: () => api.request(BASE_PATH),

    getInstance: (slug) => api.request(`${BASE_PATH}/${encodeURIComponent(slug)}`),

    createInstance: (body) => api.request(BASE_PATH, {
        method: 'POST',
        body,
    }),

    action: (slug, action) => api.request(
        `${BASE_PATH}/${encodeURIComponent(slug)}/${action}`,
        { method: 'POST' },
    ),

    // The backend also accepts a JSON body; the query form keeps the call in
    // the shape every api.request DELETE in the panel already uses.
    deleteInstance: (slug) => api.request(
        `${BASE_PATH}/${encodeURIComponent(slug)}?confirm=${encodeURIComponent(slug)}`,
        { method: 'DELETE' },
    ),

    // Panel server list for the create form's server picker.
    getServers: () => api.request('/servers'),
};
