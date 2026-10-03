import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'serverkit-sdk';
import { velaApi } from '../services/vela.js';

// Vela page — instance manager. Shell first (list + empty state); the create
// wizard and lifecycle actions mount on top of the same list state.
export default function VelaPage() {
    const { t } = useTranslation();
    const [instances, setInstances] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async () => {
        try {
            const data = await velaApi.listInstances();
            setInstances(Array.isArray(data?.instances) ? data.instances : []);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    return (
        <div className="vela-ext">
            <div className="vela-ext__header">
                <div>
                    <h2 className="vela-ext__title">{t('vela.page.title', 'Vela')}</h2>
                    <p className="vela-ext__subtitle">
                        {t('vela.page.subtitle', 'Named Vela instances, each with its own container, disk, domain and login.')}
                    </p>
                </div>
            </div>
            {loading && <p className="vela-ext__muted">{t('vela.page.loading', 'Loading desktops...')}</p>}
            {!loading && error && <p className="vela-ext__error">{error}</p>}
            {!loading && !error && instances.length === 0 && (
                <div className="vela-ext__empty">
                    <h3>{t('vela.empty.title', 'No desktops yet')}</h3>
                    <p className="vela-ext__muted">
                        {t('vela.empty.message', 'No desktops yet — create your first Vela. The "Create your first desktop" walkthrough walks you through it.')}
                    </p>
                </div>
            )}
            {!loading && !error && instances.length > 0 && (
                <ul className="vela-ext__list">
                    {instances.map((instance) => (
                        <li key={instance.slug}>{instance.name} — {instance.status}</li>
                    ))}
                </ul>
            )}
        </div>
    );
}
