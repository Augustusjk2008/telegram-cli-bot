window.__ModuleLoader__.load({
  id: 'dsh-orbit-workspace',
  factory(require) {
    const React = require('react');
    const h = React.createElement;
    const { useSyncExternalStore } = React;

    const NS = 'orbitWorkspace';
    const PANEL_ID = 'orbit-workspace';

    const dictionaries = {
      en: {
        panel: 'Orbit Workspace',
        eyebrow: 'DeepSeek Harness plugin',
        title: 'Workspace console',
        subtitle: 'Phase 1 shell: navigation and service readiness are connected.',
        stateLoading: 'Connecting to DSH services',
        stateLoadingDetail: 'The panel is waiting for the current connection snapshot.',
        stateError: 'DSH reported a connection error',
        stateErrorDetail: 'Reconnect from the DSH shell and this panel will refresh its diagnostics.',
        stateDisconnected: 'Disconnected from DSH',
        stateDisconnectedDetail: 'The panel will keep its shell and refresh when the connection returns.',
        stateReady: 'DSH shell ready',
        stateReadyDetail: 'The Phase 1 navigation surface is mounted.',
        capabilities: 'Service readiness',
        available: 'Available',
        unavailable: 'Unavailable',
        workspace: 'Workspace Remote',
        session: 'Session Remote',
        remote: 'Remote gateway',
        credentials: 'Credential Remote',
        settings: 'Settings Remote',
        emptyTitle: 'No Workspace selected',
        emptyDetail: 'Workspace and Session selection arrives in Phase 2.',
        phaseLabel: 'Current milestone',
        phaseValue: 'Phase 1 · Bundle skeleton and navigation',
        diagnostic: 'Diagnostics are metadata only; provider keys and tokens are never displayed.',
      },
      zh: {
        panel: 'Orbit 工作区',
        eyebrow: 'DeepSeek Harness 插件',
        title: '工作区控制台',
        subtitle: '第一阶段外壳：导航和服务就绪状态已经接入。',
        stateLoading: '正在连接 DSH 服务',
        stateLoadingDetail: '页面正在等待当前连接状态。',
        stateError: 'DSH 报告了连接错误',
        stateErrorDetail: '请从 DSH 外壳重连，页面会刷新诊断信息。',
        stateDisconnected: '已断开 DSH 连接',
        stateDisconnectedDetail: '页面会保留外壳，并在连接恢复后刷新。',
        stateReady: 'DSH 外壳已就绪',
        stateReadyDetail: '第一阶段导航界面已经挂载。',
        capabilities: '服务就绪状态',
        available: '可用',
        unavailable: '不可用',
        workspace: 'Workspace Remote',
        session: 'Session Remote',
        remote: 'Remote 网关',
        credentials: '凭据 Remote',
        settings: '设置 Remote',
        emptyTitle: '尚未选择 Workspace',
        emptyDetail: 'Workspace 和 Session 选择将在第二阶段接入。',
        phaseLabel: '当前里程碑',
        phaseValue: '第一阶段 · 组合包外壳与导航',
        diagnostic: '诊断信息只包含元数据，不会显示 Provider 密钥或令牌。',
      },
    };

    const styles = `
      .orbit-workspace-page {
        box-sizing: border-box;
        min-height: 100%;
        padding: 32px 40px 48px;
        color: var(--dsw-alias-label-primary);
        background: var(--dsw-alias-bg-layer-1);
        font-family: var(--ds-font-family-sans, system-ui, sans-serif);
      }
      .orbit-workspace-shell {
        width: min(960px, 100%);
        margin: 0 auto;
      }
      .orbit-workspace-eyebrow {
        margin: 0 0 8px;
        color: var(--dsw-alias-label-tertiary);
        font-size: 12px;
        letter-spacing: .08em;
        text-transform: uppercase;
      }
      .orbit-workspace-title {
        margin: 0;
        font-size: 28px;
        line-height: 36px;
        font-weight: 600;
      }
      .orbit-workspace-subtitle {
        max-width: 680px;
        margin: 8px 0 0;
        color: var(--dsw-alias-label-secondary);
        font-size: 14px;
        line-height: 22px;
      }
      .orbit-workspace-state,
      .orbit-workspace-empty,
      .orbit-workspace-meta {
        border: .5px solid var(--dsw-alias-border-l3);
        border-radius: var(--dsw-radius-lg);
        background: var(--dsw-alias-bg-layer-2);
      }
      .orbit-workspace-state {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        margin-top: 28px;
        padding: 16px;
      }
      .orbit-workspace-state[data-state='error'] {
        border-color: color-mix(in srgb, var(--dsw-alias-state-error-primary) 40%, transparent);
      }
      .orbit-workspace-state[data-state='disconnected'] {
        border-color: color-mix(in srgb, var(--dsw-alias-state-warn-primary) 40%, transparent);
      }
      .orbit-workspace-state-mark {
        width: 10px;
        height: 10px;
        flex: none;
        margin-top: 5px;
        border-radius: 50%;
        background: var(--dsw-alias-state-success-primary);
      }
      [data-state='loading'] .orbit-workspace-state-mark { background: var(--dsw-alias-state-business-primary); }
      [data-state='error'] .orbit-workspace-state-mark { background: var(--dsw-alias-state-error-primary); }
      [data-state='disconnected'] .orbit-workspace-state-mark { background: var(--dsw-alias-state-warn-primary); }
      .orbit-workspace-state-title,
      .orbit-workspace-empty-title,
      .orbit-workspace-section-title {
        margin: 0;
        font-size: 14px;
        line-height: 20px;
        font-weight: 600;
      }
      .orbit-workspace-state-detail,
      .orbit-workspace-empty-detail,
      .orbit-workspace-meta-value {
        margin: 4px 0 0;
        color: var(--dsw-alias-label-secondary);
        font-size: 13px;
        line-height: 20px;
      }
      .orbit-workspace-section {
        margin-top: 28px;
      }
      .orbit-workspace-section-title {
        margin-bottom: 10px;
      }
      .orbit-workspace-capabilities {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 8px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .orbit-workspace-capability {
        display: flex;
        min-width: 0;
        gap: 8px;
        align-items: center;
        padding: 11px 12px;
        border: .5px solid var(--dsw-alias-border-l3);
        border-radius: var(--dsw-radius-md);
        background: var(--dsw-alias-bg-layer-2);
      }
      .orbit-workspace-capability-mark {
        width: 7px;
        height: 7px;
        flex: none;
        border-radius: 50%;
        background: var(--dsw-alias-state-error-primary);
      }
      .orbit-workspace-capability[data-available='true'] .orbit-workspace-capability-mark {
        background: var(--dsw-alias-state-success-primary);
      }
      .orbit-workspace-capability-name {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        font-size: 13px;
      }
      .orbit-workspace-capability-status {
        margin-left: auto;
        color: var(--dsw-alias-label-tertiary);
        font-size: 11px;
        white-space: nowrap;
      }
      .orbit-workspace-empty {
        margin-top: 28px;
        padding: 28px 20px;
        text-align: center;
      }
      .orbit-workspace-meta {
        margin-top: 12px;
        padding: 12px 14px;
      }
      .orbit-workspace-meta-label {
        color: var(--dsw-alias-label-tertiary);
        font-size: 11px;
        letter-spacing: .04em;
        text-transform: uppercase;
      }
      .orbit-workspace-meta-value { margin-top: 2px; }
      @media (max-width: 700px) {
        .orbit-workspace-page { padding: 24px 16px 36px; }
        .orbit-workspace-title { font-size: 24px; line-height: 32px; }
      }
    `;

    function safeRead(callback) {
      try {
        return callback();
      } catch {
        return undefined;
      }
    }

    function connectionState(ctx) {
      const connection = safeRead(() => ctx.get('connection'));
      if (!connection) return 'disconnected';
      const snapshot = safeRead(() => connection.state?.getSnapshot?.()) || {};
      const value = String(snapshot.status || snapshot.phase || snapshot.kind || '').toLowerCase();
      if (/disconnect|offline|closed/.test(value)) return 'disconnected';
      if (/error|failed|failure/.test(value)) return 'error';
      if (/connect|loading|pending|retry/.test(value)) return 'loading';
      return 'ready';
    }

    function capabilitySnapshot(ctx) {
      const remote = safeRead(() => ctx.get('remote'));
      return {
        connection: connectionState(ctx),
        items: [
          { id: 'workspace', available: Boolean(safeRead(() => remote?.workspace)) },
          { id: 'session', available: Boolean(safeRead(() => remote?.session)) },
          { id: 'remote', available: Boolean(remote) },
          { id: 'credentials', available: Boolean(safeRead(() => remote?.credentials)) },
          { id: 'settings', available: Boolean(safeRead(() => remote?.settings)) },
        ],
      };
    }

    function createCapabilityStore(ctx) {
      let snapshot = capabilitySnapshot(ctx);
      let disposed = false;
      const listeners = new Set();
      const refresh = () => {
        if (disposed) return;
        const next = capabilitySnapshot(ctx);
        if (JSON.stringify(next) === JSON.stringify(snapshot)) return;
        snapshot = next;
        for (const listener of listeners) listener();
      };
      const disposers = [];
      if (typeof ctx.on === 'function') disposers.push(ctx.on('connection/reset', refresh));
      const state = safeRead(() => ctx.get('connection')?.state);
      if (typeof state?.subscribe === 'function') disposers.push(state.subscribe(refresh));
      return {
        getSnapshot: () => snapshot,
        subscribe(listener) {
          listeners.add(listener);
          return () => listeners.delete(listener);
        },
        dispose() {
          disposed = true;
          for (const dispose of disposers) if (typeof dispose === 'function') dispose();
          listeners.clear();
        },
      };
    }

    function OrbitPanelIcon({ size = 18 }) {
      return h('svg', {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.7,
        'aria-hidden': true,
      }, [
        h('circle', { key: 'outer', cx: 12, cy: 12, r: 8.2 }),
        h('path', { key: 'orbit', d: 'M4.8 14.4c2.9 1.8 7.6 1.7 11.5-.4 1.2-.7 2.2-1.6 2.9-2.6' }),
        h('circle', { key: 'core', cx: 12, cy: 12, r: 2.1, fill: 'currentColor', stroke: 'none' }),
      ]);
    }

    function stateCopy(t, state) {
      if (state === 'loading') return [t('stateLoading'), t('stateLoadingDetail')];
      if (state === 'error') return [t('stateError'), t('stateErrorDetail')];
      if (state === 'disconnected') return [t('stateDisconnected'), t('stateDisconnectedDetail')];
      return [t('stateReady'), t('stateReadyDetail')];
    }

    function OrbitWorkspacePage(props) {
      const t = props.t;
      const snapshot = useSyncExternalStore(
        props.capabilities.subscribe,
        props.capabilities.getSnapshot,
        props.capabilities.getSnapshot,
      );
      const [stateTitle, stateDetail] = stateCopy(t, snapshot.connection);
      const capabilityLabels = {
        workspace: t('workspace'),
        session: t('session'),
        remote: t('remote'),
        credentials: t('credentials'),
        settings: t('settings'),
      };
      return h('main', { className: 'orbit-workspace-page' }, [
        h('style', { key: 'style' }, styles),
        h('div', { key: 'shell', className: 'orbit-workspace-shell' }, [
          h('p', { key: 'eyebrow', className: 'orbit-workspace-eyebrow' }, t('eyebrow')),
          h('h1', { key: 'title', className: 'orbit-workspace-title' }, t('title')),
          h('p', { key: 'subtitle', className: 'orbit-workspace-subtitle' }, t('subtitle')),
          h('section', { key: 'state', className: 'orbit-workspace-state', 'data-state': snapshot.connection, 'aria-live': 'polite' }, [
            h('span', { key: 'mark', className: 'orbit-workspace-state-mark', 'aria-hidden': true }),
            h('div', { key: 'copy' }, [
              h('p', { key: 'state-title', className: 'orbit-workspace-state-title' }, stateTitle),
              h('p', { key: 'state-detail', className: 'orbit-workspace-state-detail' }, stateDetail),
            ]),
          ]),
          h('section', { key: 'capabilities', className: 'orbit-workspace-section' }, [
            h('h2', { key: 'heading', className: 'orbit-workspace-section-title' }, t('capabilities')),
            h('ul', { key: 'list', className: 'orbit-workspace-capabilities' }, snapshot.items.map((item) => h('li', {
              key: item.id,
              className: 'orbit-workspace-capability',
              'data-available': String(item.available),
            }, [
              h('span', { key: 'mark', className: 'orbit-workspace-capability-mark', 'aria-hidden': true }),
              h('span', { key: 'name', className: 'orbit-workspace-capability-name' }, capabilityLabels[item.id]),
              h('span', { key: 'status', className: 'orbit-workspace-capability-status' }, item.available ? t('available') : t('unavailable')),
            ]))),
          ]),
          h('section', { key: 'empty', className: 'orbit-workspace-empty' }, [
            h(OrbitPanelIcon, { key: 'icon', size: 28 }),
            h('h2', { key: 'empty-title', className: 'orbit-workspace-empty-title' }, t('emptyTitle')),
            h('p', { key: 'empty-detail', className: 'orbit-workspace-empty-detail' }, t('emptyDetail')),
          ]),
          h('section', { key: 'meta', className: 'orbit-workspace-meta' }, [
            h('div', { key: 'label', className: 'orbit-workspace-meta-label' }, t('phaseLabel')),
            h('div', { key: 'value', className: 'orbit-workspace-meta-value' }, t('phaseValue')),
            h('div', { key: 'diagnostic', className: 'orbit-workspace-meta-value' }, t('diagnostic')),
          ]),
        ]),
      ]);
    }

    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, dictionaries), 'dsh-orbit-workspace: dictionaries');
      const t = ctx.locale.bind(NS);
      const capabilities = createCapabilityStore(ctx);
      ctx.effect(() => () => capabilities.dispose(), 'dsh-orbit-workspace: capability store');

      ctx.slots.inject('main', function* () {
        yield ctx.slots.register({
          name: 'main',
          key: PANEL_ID,
          locale: NS,
          inject: () => ({ capabilities }),
        }, OrbitWorkspacePage);
      });

      ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({
        name: 'sidebar.panellist',
        id: PANEL_ID,
        order: 10,
        label: () => t('panel'),
        locale: NS,
      }, OrbitPanelIcon));
    }

    return {
      inject: ['slots', 'locale', 'layout'],
      apply,
    };
  },
});
