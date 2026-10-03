import { useCallback, useEffect, useRef, useState } from 'react';
import {
    Modal,
    emitWalkthroughSignal,
    useConfirm,
    useToast,
    useTranslation,
} from 'serverkit-sdk';
import { velaApi } from '../services/vela.js';

const EMPTY_FORM = { server_id: 'local', name: '', domain: '' };

// Statuses that mean "still coming up" — the list polls while any show.
const TRANSIENT = new Set(['deploying', 'starting', 'restarting']);

function statusClass(status) {
    return `vela-ext-pill vela-ext-pill--${String(status || 'unknown').replace(':', '-')}`;
}

export default function VelaPage() {
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();

    const [instances, setInstances] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showCreate, setShowCreate] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [servers, setServers] = useState(null);
    const [creating, setCreating] = useState(false);
    const [busySlug, setBusySlug] = useState(null);
    const pollRef = useRef(null);

    const load = useCallback(async (background = false) => {
        if (!background) setLoading(true);
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

    // Poll while any instance is still deploying/starting.
    const anyTransient = instances.some((i) => TRANSIENT.has(i.status));
    useEffect(() => {
        if (!anyTransient) return undefined;
        pollRef.current = setInterval(() => load(true), 10000);
        return () => clearInterval(pollRef.current);
    }, [anyTransient, load]);

    const openCreate = async () => {
        setForm(EMPTY_FORM);
        setShowCreate(true);
        if (servers === null) {
            try {
                const list = await velaApi.getServers();
                setServers(Array.isArray(list) ? list : []);
            } catch {
                setServers([]);
            }
        }
    };

    const handleCreate = async () => {
        if (!form.name.trim()) {
            toast.error(t('vela.create.nameRequired', 'A name is required'));
            return;
        }
        setCreating(true);
        try {
            const result = await velaApi.createInstance({
                server_id: form.server_id,
                name: form.name.trim(),
                domain: form.domain.trim() || undefined,
            });
            const instance = result?.instance || {};
            toast.success(t('vela.create.success', 'Desktop "{{name}}" is deploying', { name: instance.name || form.name }));
            emitWalkthroughSignal('vela.desktop-created', { slug: instance.slug });
            setShowCreate(false);
            setForm(EMPTY_FORM);
            await load(true);
        } catch (err) {
            toast.error(err.message || t('vela.create.failed', 'Failed to create the desktop'));
        } finally {
            setCreating(false);
        }
    };

    const handleAction = async (instance, action) => {
        setBusySlug(instance.slug);
        try {
            await velaApi.action(instance.slug, action);
            toast.success(t('vela.action.success', '{{action}} sent to "{{name}}"', {
                action, name: instance.name }));
            await load(true);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setBusySlug(null);
        }
    };

    const handleDelete = async (instance) => {
        const ok = await confirm({
            title: t('vela.delete.title', 'Delete "{{name}}"?', { name: instance.name }),
            message: t(
                'vela.delete.message',
                'This removes the container, its data disk and the domain route through ServerKit. Backups already taken are kept. This cannot be undone.'),
            confirmText: t('vela.delete.confirm', 'Delete desktop'),
            variant: 'danger',
        });
        if (!ok) return;
        setBusySlug(instance.slug);
        try {
            await velaApi.deleteInstance(instance.slug);
            toast.success(t('vela.delete.success', 'Desktop "{{name}}" deleted', { name: instance.name }));
            await load(true);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setBusySlug(null);
        }
    };

    const openInstance = (instance) => {
        if (instance.url) {
            window.open(instance.url, '_blank', 'noopener,noreferrer');
        }
    };

    return (
        <div className="vela-ext">
            <div className="vela-ext__header">
                <div>
                    <h2 className="vela-ext__title">{t('vela.page.title', 'Vela')}</h2>
                    <p className="vela-ext__subtitle">
                        {t('vela.page.subtitle', 'Named Vela instances, each with its own container, disk, domain and login.')}
                    </p>
                </div>
                <div className="vela-ext-card__actions">
                    <button type="button" className="btn btn-ghost" onClick={() => load()}>
                        {t('vela.page.refresh', 'Refresh')}
                    </button>
                    <button
                        type="button"
                        className="btn btn-primary"
                        data-walkthrough="vela-create-desktop"
                        onClick={openCreate}
                    >
                        {t('vela.page.newDesktop', 'New desktop')}
                    </button>
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
                    <button
                        type="button"
                        className="btn btn-primary"
                        data-walkthrough="vela-create-desktop"
                        onClick={openCreate}
                    >
                        {t('vela.page.newDesktop', 'New desktop')}
                    </button>
                </div>
            )}

            {!loading && !error && instances.length > 0 && (
                <div className="vela-ext__grid">
                    {instances.map((instance) => {
                        const busy = busySlug === instance.slug;
                        const running = String(instance.status || '').startsWith('running');
                        const stopped = ['stopped', 'exited'].includes(instance.status);
                        return (
                            <div className="card vela-ext-card" key={instance.slug}>
                                <div className="vela-ext-card__row">
                                    <div className="vela-ext-card__meta">
                                        <strong>{instance.name}</strong>
                                        <span className="vela-ext__muted">
                                            {instance.server_name || instance.server_id}
                                            {instance.domain ? ` · ${instance.domain}` : ''}
                                        </span>
                                    </div>
                                    <span className={statusClass(instance.status)}>
                                        {instance.status === 'deploying' && instance.deploy?.status
                                            ? `${instance.status} (${instance.deploy.status})`
                                            : instance.status}
                                    </span>
                                </div>
                                {instance.url && (
                                    <div className="vela-ext-card__row">
                                        <a href={instance.url} target="_blank" rel="noopener noreferrer">
                                            {instance.url}
                                        </a>
                                    </div>
                                )}
                                <div className="vela-ext-card__actions">
                                    <button
                                        type="button"
                                        className="btn btn-primary btn-sm"
                                        data-walkthrough="vela-open-desktop"
                                        disabled={!instance.url}
                                        title={instance.url ? undefined : t('vela.card.noUrl', 'Attach a domain to open this desktop')}
                                        onClick={() => openInstance(instance)}
                                    >
                                        {t('vela.card.open', 'Open')}
                                    </button>
                                    {stopped && (
                                        <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                                            onClick={() => handleAction(instance, 'start')}>
                                            {t('vela.card.start', 'Start')}
                                        </button>
                                    )}
                                    {running && (
                                        <>
                                            <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                                                onClick={() => handleAction(instance, 'restart')}>
                                                {t('vela.card.restart', 'Restart')}
                                            </button>
                                            <button type="button" className="btn btn-ghost btn-sm" disabled={busy}
                                                onClick={() => handleAction(instance, 'stop')}>
                                                {t('vela.card.stop', 'Stop')}
                                            </button>
                                        </>
                                    )}
                                    <button
                                        type="button"
                                        className="btn btn-danger btn-sm"
                                        disabled={busy}
                                        onClick={() => handleDelete(instance)}
                                    >
                                        {t('vela.card.delete', 'Delete')}
                                    </button>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            <Modal
                open={showCreate}
                onClose={() => !creating && setShowCreate(false)}
                title={t('vela.create.title', 'New Vela desktop')}
            >
                <form
                    data-walkthrough="vela-create-form"
                    onSubmit={(event) => { event.preventDefault(); handleCreate(); }}
                >
                    <div className="vela-ext-form__row">
                        <label className="form-label" htmlFor="vela-create-server">
                            {t('vela.create.server', 'Server')}
                        </label>
                        <select
                            id="vela-create-server"
                            className="form-select"
                            value={form.server_id}
                            onChange={(event) => setForm({ ...form, server_id: event.target.value })}
                        >
                            <option value="local">{t('vela.create.thisServer', 'This server (panel host)')}</option>
                            {(servers || []).map((server) => (
                                <option key={server.id} value={server.id} disabled>
                                    {server.name} — {t('vela.create.remoteSoon', 'remote deploys are not supported yet')}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div className="vela-ext-form__row">
                        <label className="form-label" htmlFor="vela-create-name">
                            {t('vela.create.name', 'Name')}
                        </label>
                        <input
                            id="vela-create-name"
                            className="form-input"
                            type="text"
                            autoFocus
                            placeholder={t('vela.create.namePlaceholder', 'Home')}
                            value={form.name}
                            onChange={(event) => setForm({ ...form, name: event.target.value })}
                        />
                        <p className="vela-ext-form__hint">
                            {t('vela.create.nameHint', 'Becomes the instance, container and disk name: "Home" turns into vela-home.')}
                        </p>
                    </div>
                    <div className="vela-ext-form__row">
                        <label className="form-label" htmlFor="vela-create-domain">
                            {t('vela.create.domain', 'Domain (optional)')}
                        </label>
                        <input
                            id="vela-create-domain"
                            className="form-input"
                            type="text"
                            placeholder="vela.example.com"
                            value={form.domain}
                            onChange={(event) => setForm({ ...form, domain: event.target.value })}
                        />
                        <p className="vela-ext-form__hint">
                            {t('vela.create.domainHint', 'Vela refuses to start without its public origin, so attach a domain before first sign-in.')}
                        </p>
                    </div>
                    <div className="vela-ext-card__actions">
                        <button
                            type="submit"
                            className="btn btn-primary"
                            data-walkthrough="vela-create-submit"
                            disabled={creating}
                        >
                            {creating
                                ? t('vela.create.creating', 'Creating...')
                                : t('vela.create.submit', 'Create desktop')}
                        </button>
                        <button
                            type="button"
                            className="btn btn-ghost"
                            disabled={creating}
                            onClick={() => setShowCreate(false)}
                        >
                            {t('vela.create.cancel', 'Cancel')}
                        </button>
                    </div>
                </form>
            </Modal>
        </div>
    );
}
