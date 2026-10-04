import { useCallback, useEffect, useRef, useState } from 'react';
import {
    Link,
    Modal,
    Pill,
    formatRelativeTime,
    statusKind,
    useConfirm,
    useNavigate,
    useParams,
    useToast,
    useTranslation,
} from 'serverkit-sdk';
import { velaApi } from '../services/vela.js';

// Statuses that mean "still coming up" — the page polls while one shows.
const TRANSIENT = new Set(['deploying', 'starting', 'restarting']);

function statusBase(status) {
    return String(status || 'unknown').split(':')[0].trim();
}

function statusLabel(instance) {
    return instance.status === 'deploying' && instance.deploy?.status
        ? `${instance.status} (${instance.deploy.status})`
        : instance.status;
}

function DetailItem({ label, children }) {
    return (
        <div className="vela-ext-detail__item">
            <dt>{label}</dt>
            <dd>{children}</dd>
        </div>
    );
}

export default function VelaInstancePage() {
    const { slug } = useParams();
    const { t } = useTranslation();
    const toast = useToast();
    const { confirm } = useConfirm();
    const navigate = useNavigate();

    const [instance, setInstance] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [busyAction, setBusyAction] = useState(null);

    const [showEdit, setShowEdit] = useState(false);
    const [editForm, setEditForm] = useState({ name: '', domain: '' });
    const [saving, setSaving] = useState(false);
    const pollRef = useRef(null);

    const load = useCallback(async (background = false) => {
        if (!background) setLoading(true);
        try {
            const data = await velaApi.getInstance(slug);
            setInstance(data?.instance || null);
            setError(null);
        } catch (err) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [slug]);

    useEffect(() => { load(); }, [load]);

    // Poll while the instance is still deploying/starting.
    const transient = instance && TRANSIENT.has(instance.status);
    useEffect(() => {
        if (!transient) return undefined;
        pollRef.current = setInterval(() => load(true), 10000);
        return () => clearInterval(pollRef.current);
    }, [transient, load]);

    const openInstance = () => {
        if (instance?.url) {
            window.open(instance.url, '_blank', 'noopener,noreferrer');
        }
    };

    const handleAction = async (action) => {
        setBusyAction(action);
        try {
            await velaApi.action(slug, action);
            toast.success(t('vela.action.success', '{{action}} sent to "{{name}}"', {
                action, name: instance.name }));
            await load(true);
        } catch (err) {
            toast.error(err.message);
        } finally {
            setBusyAction(null);
        }
    };

    const handleDelete = async () => {
        const ok = await confirm({
            title: t('vela.delete.title', 'Delete "{{name}}"?', { name: instance.name }),
            message: t(
                'vela.delete.message',
                "This removes the container, its data disk and the domain route through ServerKit. Backups already taken are kept. This can't be undone."),
            confirmText: t('vela.delete.confirm', 'Delete desktop'),
            variant: 'danger',
        });
        if (!ok) return;
        try {
            await velaApi.deleteInstance(slug);
            toast.success(t('vela.delete.success', 'Desktop "{{name}}" deleted', { name: instance.name }));
            navigate('/vela');
        } catch (err) {
            toast.error(err.message);
        }
    };

    const openEdit = () => {
        setEditForm({ name: instance.name || '', domain: instance.domain || '' });
        setShowEdit(true);
    };

    const handleEdit = async () => {
        const name = editForm.name.trim();
        if (!name) {
            toast.error(t('vela.edit.nameRequired', 'A name is required'));
            return;
        }
        setSaving(true);
        try {
            // An empty domain detaches it (the backend treats null/'' as detach).
            await velaApi.updateInstance(slug, { name, domain: editForm.domain.trim() });
            toast.success(t('vela.edit.success', 'Desktop updated'));
            setShowEdit(false);
            await load(true);
        } catch (err) {
            toast.error(err.message || t('vela.edit.failed', 'Failed to update the desktop'));
        } finally {
            setSaving(false);
        }
    };

    if (loading && !instance) {
        return (
            <div className="vela-ext">
                <p className="vela-ext__muted">{t('vela.page.loading', 'Loading desktops…')}</p>
            </div>
        );
    }

    if (error || !instance) {
        return (
            <div className="vela-ext">
                <Link to="/vela" className="vela-ext__back">
                    &larr; {t('vela.detail.back', 'All desktops')}
                </Link>
                <p className="vela-ext__error">
                    {error || t('vela.detail.notFound', 'This desktop does not exist anymore.')}
                </p>
            </div>
        );
    }

    const running = String(instance.status || '').startsWith('running');
    const stopped = ['stopped', 'exited'].includes(instance.status);
    const warnings = instance.warnings || [];

    return (
        <div className="vela-ext">
            <Link to="/vela" className="vela-ext__back">
                &larr; {t('vela.detail.back', 'All desktops')}
            </Link>

            <div className="vela-ext__header">
                <div className="vela-ext-detail__heading">
                    <h2 className="vela-ext__title">{instance.name}</h2>
                    <Pill kind={statusKind(statusBase(instance.status))}>
                        {statusLabel(instance)}
                    </Pill>
                    <span className="vela-ext__muted">{instance.slug}</span>
                </div>
                <div className="vela-ext-card__actions">
                    <button
                        type="button"
                        className="btn btn-primary btn-sm"
                        data-walkthrough="vela-open-desktop"
                        disabled={!instance.url}
                        title={instance.url ? undefined : t('vela.card.noUrl', 'Attach a domain to open this desktop')}
                        onClick={openInstance}
                    >
                        {t('vela.card.open', 'Open')}
                    </button>
                    {stopped && (
                        <button type="button" className="btn btn-ghost btn-sm"
                            disabled={busyAction !== null}
                            onClick={() => handleAction('start')}>
                            {t('vela.card.start', 'Start')}
                        </button>
                    )}
                    {running && (
                        <>
                            <button type="button" className="btn btn-ghost btn-sm"
                                disabled={busyAction !== null}
                                onClick={() => handleAction('restart')}>
                                {t('vela.card.restart', 'Restart')}
                            </button>
                            <button type="button" className="btn btn-ghost btn-sm"
                                disabled={busyAction !== null}
                                onClick={() => handleAction('stop')}>
                                {t('vela.card.stop', 'Stop')}
                            </button>
                        </>
                    )}
                    <button type="button" className="btn btn-ghost btn-sm" onClick={openEdit}>
                        {t('vela.detail.edit', 'Edit')}
                    </button>
                    <button type="button" className="btn btn-danger btn-sm" onClick={handleDelete}>
                        {t('vela.card.delete', 'Delete')}
                    </button>
                </div>
            </div>

            {warnings.length > 0 && (
                <div className="vela-ext-detail__warnings">
                    <strong>{t('vela.detail.warnings', 'Needs attention')}</strong>
                    <ul>
                        {warnings.map((warning) => <li key={warning}>{warning}</li>)}
                    </ul>
                </div>
            )}

            <div className="card vela-ext-detail">
                <dl className="vela-ext-detail__grid">
                    <DetailItem label={t('vela.detail.url', 'URL')}>
                        {instance.url ? (
                            <a href={instance.url} target="_blank" rel="noopener noreferrer">
                                {instance.url}
                            </a>
                        ) : '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.server', 'Server')}>
                        {instance.server_name || instance.server_id || '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.domain', 'Domain')}>
                        {instance.domain || '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.port', 'Port')}>
                        {instance.port ?? '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.created', 'Created')}>
                        {instance.created_at ? formatRelativeTime(instance.created_at) : '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.deploy', 'Deploy job')}>
                        {instance.deploy
                            ? `${instance.deploy.status || '—'} · ${instance.deploy.job_id}`
                            : '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.disk', 'Disk')}>
                        {instance.disk
                            ? [instance.disk.name, instance.disk.mount_path, instance.disk.declared_size]
                                .filter(Boolean).join(' · ')
                            : '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.backup', 'Backup')}>
                        {instance.backup
                            ? `${instance.backup.schedule_cron} · ${t('vela.detail.backupRetain', 'keep {{count}}', { count: instance.backup.retention_count })}`
                            : '—'}
                    </DetailItem>
                    <DetailItem label={t('vela.detail.password', 'First-start password')}>
                        {instance.initial_password ? (
                            <>
                                <code>{instance.initial_password.secret}</code>
                                <p className="vela-ext-form__hint">
                                    {t('vela.detail.passwordHint', "Reveal the value from ServerKit's manifest secret vault; it applies on first start only.")}
                                </p>
                            </>
                        ) : '—'}
                    </DetailItem>
                </dl>
            </div>

            <Modal
                open={showEdit}
                onClose={() => !saving && setShowEdit(false)}
                title={t('vela.edit.title', 'Edit "{{name}}"', { name: instance.name })}
            >
                <form onSubmit={(event) => { event.preventDefault(); handleEdit(); }}>
                    <div className="vela-ext-form__row">
                        <label className="form-label" htmlFor="vela-edit-name">
                            {t('vela.edit.name', 'Name')}
                        </label>
                        <input
                            id="vela-edit-name"
                            className="form-input"
                            type="text"
                            autoFocus
                            value={editForm.name}
                            onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
                        />
                        <p className="vela-ext-form__hint">
                            {t('vela.edit.nameHint', 'Display name only. The slug, container and disk names stay as created.')}
                        </p>
                    </div>
                    <div className="vela-ext-form__row">
                        <label className="form-label" htmlFor="vela-edit-domain">
                            {t('vela.edit.domain', 'Domain')}
                        </label>
                        <input
                            id="vela-edit-domain"
                            className="form-input"
                            type="text"
                            placeholder="vela.example.com"
                            value={editForm.domain}
                            onChange={(event) => setEditForm({ ...editForm, domain: event.target.value })}
                        />
                        <p className="vela-ext-form__hint">
                            {t('vela.edit.domainHint', 'Leave empty to detach the domain. Vela refuses to start without its public origin, so attach a domain before signing in.')}
                        </p>
                    </div>
                    <div className="vela-ext-card__actions">
                        <button type="submit" className="btn btn-primary" disabled={saving}>
                            {saving
                                ? t('vela.edit.saving', 'Saving…')
                                : t('vela.edit.submit', 'Save changes')}
                        </button>
                        <button
                            type="button"
                            className="btn btn-ghost"
                            disabled={saving}
                            onClick={() => setShowEdit(false)}
                        >
                            {t('vela.edit.cancel', 'Cancel')}
                        </button>
                    </div>
                </form>
            </Modal>
        </div>
    );
}
