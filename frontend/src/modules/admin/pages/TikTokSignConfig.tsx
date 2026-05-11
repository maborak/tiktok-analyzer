import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  Cloud,
  Eye,
  EyeOff,
  Key,
  Loader2,
  LogIn,
  Save,
  Server,
  ShieldAlert,
  ShieldCheck,
  TestTube,
  UserCheck,
  XCircle,
} from 'lucide-react';
import toast from 'react-hot-toast';

import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import {
  type TikTokSignConfig,
  type TikTokSignProvider,
  isElectronClient,
  tiktokApi,
} from '@admin/services/tiktok';

/**
 * Admin page for switching the TikTok sign engine.
 *
 * Two providers:
 *   - euler   — Use EulerStream (third-party). Free tier is rate-limited;
 *               an API key raises the budget significantly.
 *   - session — Pass a TikTok `sessionid` cookie through TikTokLive. The
 *               sign request still goes through EulerStream but is
 *               authenticated as your account, getting better quotas + a
 *               cleaner connection. Tied to one TikTok account.
 *
 * Values write to the typed-config DB table; on save they take effect on
 * the next listener reconnect — no process restart required.
 */
export function TikTokSignConfig() {
  const [cfg, setCfg] = useState<TikTokSignConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [provider, setProvider] = useState<TikTokSignProvider>('euler');
  const [apiKey, setApiKey] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [ttIdc, setTtIdc] = useState('');
  const [revealApiKey, setRevealApiKey] = useState(false);
  const [revealSessionId, setRevealSessionId] = useState(false);
  const [localUrl, setLocalUrl] = useState('http://127.0.0.1:21214');
  const [testing, setTesting] = useState(false);
  const [signingIn, setSigningIn] = useState(false);
  // Result of the most recent /sign/test probe (so the user gets feedback
  // even when they navigate the page after a test).
  const [testResult, setTestResult] = useState<{
    ok: boolean;
    nickname?: string | null;
    unique_id?: string | null;
    user_id?: string | null;
    error?: string | null;
  } | null>(null);
  const electron = isElectronClient();

  // Load on mount.
  useEffect(() => {
    let cancelled = false;
    tiktokApi
      .getSignConfig()
      .then((d) => {
        if (cancelled) return;
        setCfg(d);
        setProvider(d.provider);
        setTtIdc(d.session_tt_target_idc ?? '');
        setLocalUrl(d.local_sign_url ?? 'http://127.0.0.1:21214');
      })
      .catch(() => {
        toast.error('Failed to load sign engine config');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const r = await tiktokApi.testSignConfig();
      setTestResult(r);
      if (r.ok) {
        toast.success(
          r.nickname
            ? `OK — signed in as ${r.nickname}${r.unique_id ? ` (@${r.unique_id})` : ''}`
            : 'Sign engine OK'
        );
      } else {
        toast.error(r.error ?? 'Test failed');
      }
    } catch (e) {
      console.error(e);
      toast.error('Test failed');
    } finally {
      setTesting(false);
    }
  };

  const onElectronSignIn = async () => {
    if (!window.api?.login || !window.api?.getSessionCookies) return;
    setSigningIn(true);
    try {
      const loginRes = (await window.api.login()) as { logged_in?: boolean; error?: string };
      if (!loginRes?.logged_in) {
        toast.error(loginRes?.error || 'Sign-in did not complete');
        return;
      }
      const cookies = await window.api.getSessionCookies();
      if (!cookies?.session_id) {
        toast.error('Logged in, but no sessionid cookie found.');
        return;
      }
      // Persist directly: provider=session + the captured cookies.
      const updated = await tiktokApi.saveSignConfig({
        provider: 'session',
        session_id: cookies.session_id,
        session_tt_target_idc: cookies.tt_target_idc ?? '',
      });
      setCfg(updated);
      setProvider('session');
      setSessionId('');  // already saved; clear the editor
      setTtIdc(cookies.tt_target_idc ?? '');
      toast.success('Captured TikTok session — click Test to verify.');
    } catch (e) {
      console.error(e);
      toast.error('Failed to capture session from Electron');
    } finally {
      setSigningIn(false);
    }
  };

  const onSave = async () => {
    setSaving(true);
    try {
      // Only send fields the user actually edited; empty string IS sent
      // (means "clear"), undefined means "leave unchanged".
      const body: {
        provider: TikTokSignProvider;
        euler_api_key?: string;
        session_id?: string;
        session_tt_target_idc?: string;
        local_sign_url?: string;
      } = { provider };
      if (apiKey !== '') body.euler_api_key = apiKey;
      if (sessionId !== '') body.session_id = sessionId;
      if (ttIdc !== (cfg?.session_tt_target_idc ?? '')) {
        body.session_tt_target_idc = ttIdc;
      }
      if (localUrl !== (cfg?.local_sign_url ?? '')) {
        body.local_sign_url = localUrl;
      }

      const updated = await tiktokApi.saveSignConfig(body);
      setCfg(updated);
      setApiKey('');
      setSessionId('');
      toast.success('Sign engine settings saved. Takes effect on next listener reconnect.');
    } catch (e) {
      console.error(e);
      toast.error('Failed to save sign engine settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <PageShell>
        <div className="py-16 text-center text-sm text-gray-500">
          <Loader2 className="w-5 h-5 inline mr-2 animate-spin" />
          Loading sign engine config…
        </div>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader
        title="TikTok Sign Engine"
        icon={<Key className="w-5 h-5" />}
        description="How the listener pool obtains signed WebSocket URLs for TikTok live streams."
      />

      {/* Provider selector */}
      <section className="card">
        <h2 className="auth-mono-label mb-3">Engine</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <ProviderCard
            id="euler"
            active={provider === 'euler'}
            onClick={() => setProvider('euler')}
            icon={<Cloud className="w-5 h-5" />}
            title="EulerStream"
            subtitle="Third-party sign service"
            description="Default. The TikTokLive Python lib's standard signer. Free tier is harshly rate-limited; an API key raises the budget. Sign up at eulerstream.com."
            tone="primary"
          />
          <ProviderCard
            id="session"
            active={provider === 'session'}
            onClick={() => setProvider('session')}
            icon={<UserCheck className="w-5 h-5" />}
            title="Session-authenticated EulerStream"
            subtitle="Better quotas via your account"
            description="Sends your TikTok sessionid to EulerStream so requests are authenticated as you. Better quotas + connection quality, tied to one account. EulerStream is still in the loop."
            tone="success"
          />
          <ProviderCard
            id="local"
            active={provider === 'local'}
            onClick={() => setProvider('local')}
            icon={<Server className="w-5 h-5" />}
            title="Local sign broker"
            subtitle="Zero third-party"
            description="The Electron client hosts a local sign broker that intercepts the WS URL TikTok's own JS builds. No EulerStream involvement at all. Requires the Electron app to be running."
            tone="emerald"
          />
        </div>
      </section>

      {/* Provider-specific fields */}
      {provider === 'euler' && (
        <section className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="auth-mono-label flex items-center gap-2">
              <Key className="w-4 h-4" />
              EulerStream API key
            </h2>
            {cfg?.euler_api_key_set ? (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-mono bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                <ShieldCheck className="w-3 h-3" />
                set
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-mono bg-amber-50 text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
                <ShieldAlert className="w-3 h-3" />
                using free tier
              </span>
            )}
          </div>

          <div className="space-y-2">
            <SecretInput
              value={apiKey}
              onChange={setApiKey}
              reveal={revealApiKey}
              onToggleReveal={() => setRevealApiKey((v) => !v)}
              placeholder={cfg?.euler_api_key ?? 'euler_…'}
              ariaLabel="EulerStream API key"
            />
            <p className="text-xs text-gray-500">
              {cfg?.euler_api_key_set
                ? 'A key is currently configured. Type a new one to replace it, or leave blank to keep the existing value.'
                : 'No key configured — running on the free tier. Paste a key from eulerstream.com to raise the rate limit.'}
            </p>
            <p className="text-xs text-gray-500">
              Once saved here, you can remove <code className="font-mono">PHOVEU_BACKEND_TIKTOK_EULER_API_KEY</code> from your <code className="font-mono">.env</code> — the DB-stored value takes precedence.
            </p>
          </div>
        </section>
      )}

      {provider === 'session' && (
        <section className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="auth-mono-label flex items-center gap-2">
              <UserCheck className="w-4 h-4" />
              TikTok session cookie
            </h2>
            {cfg?.session_id_set ? (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-mono bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300">
                <ShieldCheck className="w-3 h-3" />
                set
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-mono bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300">
                <ShieldAlert className="w-3 h-3" />
                missing — required for session mode
              </span>
            )}
          </div>

          <div className="space-y-3">
            {/* Auto-capture from Electron client (zero copy/paste) */}
            {electron && (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/30 p-3 flex items-start gap-3">
                <UserCheck className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm text-emerald-900 dark:text-emerald-100">
                    Sign in directly from this app
                  </div>
                  <p className="text-xs text-emerald-800 dark:text-emerald-200 mt-0.5">
                    Click below — a TikTok login window opens, you scan the QR / log in normally,
                    and the session cookie is captured automatically and saved here. No DevTools.
                  </p>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onElectronSignIn}
                  disabled={signingIn}
                >
                  {signingIn ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                      Waiting…
                    </>
                  ) : (
                    <>
                      <LogIn className="w-4 h-4 mr-1" />
                      Sign in to TikTok
                    </>
                  )}
                </Button>
              </div>
            )}

            <div>
              <label className="auth-mono-label block mb-1">
                sessionid
                {!electron && <span className="ml-2 text-gray-400 normal-case">(manual paste)</span>}
              </label>
              <SecretInput
                value={sessionId}
                onChange={setSessionId}
                reveal={revealSessionId}
                onToggleReveal={() => setRevealSessionId((v) => !v)}
                placeholder={cfg?.session_id ?? 'paste your sessionid cookie value'}
                ariaLabel="TikTok sessionid cookie"
              />
              <p className="text-xs text-gray-500 mt-1">
                {electron ? (
                  <>Or use the button above to capture it automatically. Manual: </>
                ) : null}
                Open <code className="font-mono">tiktok.com</code> in your browser, log in, then in DevTools → Application → Cookies, copy the value of the <code className="font-mono">sessionid</code> cookie. Tied to your account; rotate on suspected ban risk.
              </p>
            </div>
            <div>
              <label className="auth-mono-label block mb-1">tt-target-idc <span className="text-gray-400 normal-case">(optional)</span></label>
              <Input
                value={ttIdc}
                onChange={(e) => setTtIdc(e.target.value)}
                placeholder="useast2a, useast1a, alisg, …"
              />
              <p className="text-xs text-gray-500 mt-1">
                Some accounts (typically EU/UK) need this paired with the sessionid. If unsure leave blank — the default works for most.
              </p>
            </div>
          </div>
        </section>
      )}

      {provider === 'local' && (
        <section className="card">
          <div className="flex items-center justify-between mb-3">
            <h2 className="auth-mono-label flex items-center gap-2">
              <Server className="w-4 h-4" />
              Local sign broker
            </h2>
          </div>

          <div className="space-y-3">
            <div className="rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/30 p-3 flex items-start gap-3 text-sm text-amber-800 dark:text-amber-200">
              <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
              <div>
                <div className="font-medium">Requires the Electron client to be running.</div>
                <div className="text-xs mt-0.5">
                  The broker listens on the URL below and is provided by the bundled Electron app.
                  If the app isn't running, this provider will fail.
                  Click <b>Test</b> to confirm the broker is reachable.
                </div>
              </div>
            </div>
            <div>
              <label className="auth-mono-label block mb-1">Broker URL</label>
              <Input
                value={localUrl}
                onChange={(e) => setLocalUrl(e.target.value)}
                placeholder="http://127.0.0.1:21214"
                className="font-mono"
              />
              <p className="text-xs text-gray-500 mt-1">
                Default port <code className="font-mono">21214</code> — change only if you've reconfigured the broker port in the Electron client.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Test result strip */}
      {testResult && (
        <div
          className={
            'rounded-lg border p-3 flex items-start gap-3 text-sm ' +
            (testResult.ok
              ? 'border-emerald-200 bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/30'
              : 'border-rose-200 bg-rose-50 dark:bg-rose-500/10 dark:border-rose-500/30')
          }
        >
          {testResult.ok ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          ) : (
            <XCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          )}
          <div className="flex-1 min-w-0">
            {testResult.ok ? (
              <>
                <div className="font-semibold">Sign engine OK</div>
                <div className="text-xs text-gray-700 dark:text-gray-300 mt-0.5">
                  {testResult.nickname && <span className="font-medium">{testResult.nickname}</span>}
                  {testResult.unique_id && (
                    <span className="ml-1 font-mono text-gray-500">@{testResult.unique_id}</span>
                  )}
                  {testResult.user_id && (
                    <span className="ml-2 font-mono text-[10px] text-gray-400">
                      ID: {testResult.user_id}
                    </span>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="font-semibold">Sign engine NOT working</div>
                <div className="text-xs text-rose-700 dark:text-rose-300 mt-0.5">
                  {testResult.error}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Save / Test */}
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onTest} disabled={testing || saving}>
          {testing ? (
            <>
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              Testing…
            </>
          ) : (
            <>
              <TestTube className="w-4 h-4 mr-1" />
              Test
            </>
          )}
        </Button>
        <Button variant="primary" onClick={onSave} disabled={saving || testing}>
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Save className="w-4 h-4 mr-1" />
              Save
            </>
          )}
        </Button>
      </div>

      {/* Info card */}
      <section className="rounded-lg border border-gray-200 bg-gray-50 dark:bg-gray-100/30 p-4 text-sm text-gray-700">
        <h3 className="font-semibold mb-1">When does the change take effect?</h3>
        <p>
          Settings are stored in the typed-config DB table and read by the listener
          on every connect. The next time a session reconnects (a TikTok stream
          ends and starts, or the supervisor cycles), the new provider is used.
          To force an immediate switch, restart the worker (<code className="font-mono">./build.sh worker</code>) or the API process.
        </p>
      </section>
    </PageShell>
  );
}

// ─── small bits ────────────────────────────────────────────────────

interface ProviderCardProps {
  id: string;
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  description: string;
  tone: 'primary' | 'success' | 'emerald';
}
function ProviderCard({
  active, onClick, icon, title, subtitle, description, tone,
}: ProviderCardProps) {
  const ring =
    tone === 'primary'
      ? 'ring-primary-500'
      : tone === 'emerald'
        ? 'ring-emerald-600'
        : 'ring-emerald-500';
  const bg =
    tone === 'primary'
      ? 'bg-primary-50 dark:bg-primary-500/10'
      : 'bg-emerald-50 dark:bg-emerald-500/10';
  const iconColor =
    tone === 'primary' ? 'text-primary-600' : 'text-emerald-600';
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'text-left p-4 rounded-lg border-2 transition-all ' +
        (active
          ? `${bg} border-transparent ring-2 ${ring}`
          : 'border-gray-200 hover:border-gray-300 bg-white')
      }
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={iconColor}>{icon}</span>
        <span className="font-semibold">{title}</span>
        {active && (
          <span className="ml-auto text-[10px] font-mono px-1.5 py-0.5 rounded bg-gray-900 text-white">
            ACTIVE
          </span>
        )}
      </div>
      <div className="text-xs font-mono text-gray-500 mb-1.5">{subtitle}</div>
      <p className="text-xs text-gray-600 leading-relaxed">{description}</p>
    </button>
  );
}

interface SecretInputProps {
  value: string;
  onChange: (v: string) => void;
  reveal: boolean;
  onToggleReveal: () => void;
  placeholder: string;
  ariaLabel: string;
}
function SecretInput({
  value, onChange, reveal, onToggleReveal, placeholder, ariaLabel,
}: SecretInputProps) {
  return (
    <div className="relative">
      <Input
        type={reveal ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        autoComplete="off"
        spellCheck={false}
        className="font-mono pr-12"
      />
      <button
        type="button"
        onClick={onToggleReveal}
        className="absolute inset-y-0 right-0 px-3 text-gray-400 hover:text-gray-600"
        aria-label={reveal ? 'Hide value' : 'Show value'}
      >
        {reveal ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  );
}
