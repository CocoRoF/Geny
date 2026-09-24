/**
 * MCP — tool servers running on this computer, offered to the agent.
 *
 * The app hosts the clients (stdio processes or HTTP endpoints) and the
 * agent calls their tools through the connector bridge, as
 * `mcp_<server>_<tool>`. Nothing here needs the server; it works signed out.
 */
import { useEffect, useState, type ReactNode } from 'react'

import type { MCPServerConfig, MCPServerStatus } from '../../../preload/index'
import { Icon } from '../chat/icons'
import {
  Button, Card, ConfirmButton, Empty, Field, Group, Hint, Segmented, Status, Switch, TextInput, type T,
} from './kit'

const kvToText = (o?: Record<string, string>, sep = '='): string =>
  Object.entries(o || {}).map(([k, v]) => `${k}${sep}${v}`).join('\n')

function textToKv(text: string, sep: '=' | ':'): Record<string, string> | undefined {
  const out: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const l = line.trim()
    if (!l) continue
    const i = l.indexOf(sep)
    if (i <= 0) continue
    out[l.slice(0, i).trim()] = l.slice(i + 1).trim()
  }
  return Object.keys(out).length ? out : undefined
}

const EMPTY_FORM: MCPServerConfig = { name: '', transport: 'stdio', command: '' }

export function McpPage({ t }: { t: T }): ReactNode {
  const [servers, setServers] = useState<MCPServerConfig[]>([])
  const [on, setOn] = useState(true)
  const [status, setStatus] = useState<Record<string, MCPServerStatus>>({})
  const [editing, setEditing] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [form, setForm] = useState<MCPServerConfig>(EMPTY_FORM)
  const [envText, setEnvText] = useState('')
  const [headersText, setHeadersText] = useState('')
  const [test, setTest] = useState<{ tone: 'ok' | 'err' | 'busy'; text: string } | null>(null)

  useEffect(() => {
    const m = window.connector?.mcp
    if (!m) return
    void m.listServers?.().then(setServers).catch(() => setServers([]))
    void m.getEnabled?.().then(setOn).catch(() => undefined)
    const apply = (rows: MCPServerStatus[]): void => {
      setStatus(Object.fromEntries((rows || []).map((r) => [r.name, r])))
    }
    void m.status?.().then(apply).catch(() => undefined)
    const off = m.onStatus?.(apply)
    return () => { try { off?.() } catch { /* already gone */ } }
  }, [])

  const formConfig = (): MCPServerConfig => {
    const cfg: MCPServerConfig = { ...form, name: form.name.trim() }
    if (cfg.transport === 'stdio') {
      cfg.env = textToKv(envText, '=')
      delete cfg.url
      delete cfg.headers
    } else {
      cfg.headers = textToKv(headersText, ':')
      delete cfg.command
      delete cfg.env
    }
    return cfg
  }

  const closeForm = (): void => {
    setFormOpen(false)
    setEditing(null)
    setForm(EMPTY_FORM)
    setEnvText('')
    setHeadersText('')
    setTest(null)
  }

  const openAdd = (): void => {
    closeForm()
    setFormOpen(true)
  }

  const openEdit = (s: MCPServerConfig): void => {
    setEditing(s.name)
    setForm({ ...s })
    setEnvText(kvToText(s.env, '='))
    setHeadersText(kvToText(s.headers, ': '))
    setTest(null)
    setFormOpen(true)
  }

  const save = async (): Promise<void> => {
    const cfg = formConfig()
    if (!cfg.name) return
    if (cfg.enabled === undefined) cfg.enabled = true
    const m = window.connector?.mcp
    const list = editing
      ? (await m?.updateServer?.(editing, cfg)) ?? (await m?.addServer(cfg)) ?? []
      : (await m?.addServer(cfg)) ?? []
    setServers(list)
    closeForm()
  }

  const remove = async (name: string): Promise<void> => {
    setServers((await window.connector?.mcp?.removeServer(name)) ?? [])
    if (editing === name) closeForm()
  }

  const toggleServer = async (s: MCPServerConfig, enabled: boolean): Promise<void> => {
    const next = { ...s, enabled }
    const m = window.connector?.mcp
    setServers((await m?.updateServer?.(s.name, next)) ?? (await m?.addServer(next)) ?? [])
  }

  const toggleMaster = async (enabled: boolean): Promise<void> => {
    setOn(enabled)
    await window.connector?.mcp?.setEnabled?.(enabled)
  }

  const runTest = async (): Promise<void> => {
    setTest({ tone: 'busy', text: t('mcp.testing') })
    const r = await window.connector?.mcp?.testServer(formConfig())
    setTest(r?.ok
      ? {
          tone: 'ok',
          text: t('mcp.testOkNames', {
            count: r.tools?.length ?? 0,
            names: (r.tools || []).slice(0, 8).map((x) => x.name).join(', '),
          }),
        }
      : { tone: 'err', text: t('mcp.testFail', { error: r?.error ?? t('mcp.testFailUnknown') }) })
  }

  const connected = Object.values(status).filter((s) => s.connected).length
  const tools = Object.values(status).reduce((n, s) => n + (s.connected ? s.toolCount : 0), 0)

  return (
    <>
      <Card icon={Icon.plug} title={t('mcp.serversCard')} desc={t('mcp.serversHint')}
        control={<Switch checked={on} onChange={(v) => void toggleMaster(v)} label={t('mcp.master')} />}>
        <Hint>{on ? t('mcp.summary', { servers: connected, tools }) : t('mcp.masterOffHint')}</Hint>
      </Card>

      <Group title={t('set.mcp.servers')} plain
        action={!formOpen && <Button size="sm" icon={Icon.plus} onClick={openAdd}>{t('mcp.addCard')}</Button>}>
        {servers.length === 0 ? (
          <div className="set-group-body"><Empty>{t('mcp.empty')}</Empty></div>
        ) : (
          <div className="set-list">
            {servers.map((s) => {
              const st = status[s.name]
              const enabled = s.enabled !== false
              const tone = !enabled ? 'idle' : st?.connected ? 'ok' : st?.error ? 'err' : 'idle'
              const state = !enabled ? t('mcp.rowDisabled')
                : st?.connected ? t('mcp.rowTools', { count: st.toolCount })
                  : st?.error ? t('set.mcp.failed') : t('mcp.rowIdle')
              return (
                <div key={s.name} className={`set-item ${enabled ? '' : 'off'}`}>
                  <div className="set-item-main">
                    <div className="set-item-title">
                      <Status tone={tone}>{s.name}</Status>
                      <span className="set-badge">{s.transport}</span>
                      <span className="set-muted">{state}</span>
                    </div>
                    <div className="set-item-sub">
                      <span className="set-mono">{s.transport === 'stdio' ? s.command : s.url}</span>
                    </div>
                    {enabled && st?.error && !st.connected && (
                      <div className="set-item-sub"><span className="set-inline-note err">{st.error}</span></div>
                    )}
                  </div>
                  <div className="set-item-actions">
                    <Button size="sm" variant="ghost" onClick={() => openEdit(s)}>{t('mcp.edit')}</Button>
                    <ConfirmButton size="sm" icon={Icon.trash} label={t('mcp.remove')}
                      confirmLabel={t('set.mcp.removeConfirm')} cancelLabel={t('set.cancel')}
                      onConfirm={() => remove(s.name)} />
                    <Switch checked={enabled} label={s.name} onChange={(v) => void toggleServer(s, v)} />
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Group>

      {formOpen && (
        <Group title={editing ? t('mcp.editCard', { name: editing }) : t('mcp.addCard')}>
          <div className="set-form">
            <Field label={t('set.mcp.name')} htmlFor="set-mcp-name">
              <TextInput id="set-mcp-name" value={form.name} placeholder={t('mcp.namePlaceholder')}
                onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))} />
            </Field>
            <Field label={t('set.mcp.transport')}>
              <div>
                <Segmented<'stdio' | 'http'> value={form.transport} label={t('set.mcp.transport')}
                  onChange={(v) => setForm((p) => ({ ...p, transport: v }))} options={[
                    { value: 'stdio', label: t('set.mcp.stdio') },
                    { value: 'http', label: 'HTTP' },
                  ]} />
              </div>
            </Field>
            {form.transport === 'stdio' ? (
              <>
                <Field label={t('set.mcp.command')} htmlFor="set-mcp-cmd">
                  <TextInput id="set-mcp-cmd" mono value={form.command ?? ''} placeholder={t('mcp.commandPlaceholder')}
                    onChange={(e) => setForm((p) => ({ ...p, command: e.target.value }))} />
                </Field>
                <Field label={t('mcp.envLabel')} htmlFor="set-mcp-env">
                  <textarea id="set-mcp-env" className="set-input mono" rows={3} placeholder={t('mcp.envPlaceholder')}
                    value={envText} onChange={(e) => setEnvText(e.target.value)} />
                </Field>
              </>
            ) : (
              <>
                <Field label="URL" htmlFor="set-mcp-url">
                  <TextInput id="set-mcp-url" mono value={form.url ?? ''} placeholder={t('mcp.urlPlaceholder')}
                    onChange={(e) => setForm((p) => ({ ...p, url: e.target.value }))} />
                </Field>
                <Field label={t('mcp.headersLabel')} htmlFor="set-mcp-headers">
                  <textarea id="set-mcp-headers" className="set-input mono" rows={3} placeholder={t('mcp.headersPlaceholder')}
                    value={headersText} onChange={(e) => setHeadersText(e.target.value)} />
                </Field>
              </>
            )}
            <div className="set-actions">
              <Button variant="primary" disabled={!form.name.trim()} onClick={() => void save()}>
                {editing ? t('mcp.save') : t('mcp.add')}
              </Button>
              <Button disabled={!form.name.trim() || test?.tone === 'busy'} onClick={() => void runTest()}>
                {t('set.mcp.test')}
              </Button>
              <Button variant="ghost" onClick={closeForm}>{t('set.cancel')}</Button>
            </div>
            {test && (
              <Hint tone={test.tone === 'busy' ? undefined : test.tone}>{test.text}</Hint>
            )}
            <Hint>{t('set.mcp.naming')}</Hint>
          </div>
        </Group>
      )}
    </>
  )
}
