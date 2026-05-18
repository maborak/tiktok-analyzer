/**
 * UserTikTokAddMonitorModal — credit-aware "Add a TikTok handle"
 * dialog. Surfaces:
 *
 *   - Current balance + the 1-credit cost.
 *   - Handle input (strips leading @, trims whitespace).
 *   - 402 / 409 backend errors as distinct toasts so the user knows
 *     whether to buy credits or pick a different handle.
 */

import { useState } from 'react';
import { Plus, Loader2, Wallet, AlertTriangle } from 'lucide-react';
import toast from 'react-hot-toast';

import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { userTikTokApi } from '../services/tiktok';

interface Props {
  balance: number;
  onClose: () => void;
  onAdded: () => void;
}

export function UserTikTokAddMonitorModal({ balance, onClose, onAdded }: Props) {
  const [handle, setHandle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cleanedHandle = handle.replace(/^@+/, '').trim();
  const canSubmit = cleanedHandle.length > 0 && balance >= 1 && !busy;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const res = await userTikTokApi.addMonitor(cleanedHandle);
      toast.success(
        res.credit_debited
          ? `Added @${res.sub.unique_id} (1 credit charged).`
          : `@${res.sub.unique_id} was already in your list.`,
      );
      onAdded();
    } catch (err: any) {
      const status = err?.response?.status;
      const detail =
        err?.response?.data?.detail ?? err?.message ?? 'Unknown error.';
      if (status === 402) {
        setError(
          `${detail} Top up your credit balance from /user/account/billing.`,
        );
      } else if (status === 409) {
        setError(
          `That handle is already monitored by another user. Pick a different one.`,
        );
      } else if (status === 400) {
        setError(detail);
      } else {
        setError(`Could not add monitor: ${detail}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      title="Add a TikTok Monitor"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!canSubmit}>
            {busy ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Plus className="h-4 w-4 mr-1" />
            )}
            Add (1 credit)
          </Button>
        </div>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="rounded-md border border-gray-200 bg-gray-50 p-3 flex items-start gap-3 text-sm">
          <Wallet className="h-4 w-4 text-gray-500 mt-0.5" aria-hidden />
          <div className="flex-1">
            <p className="text-gray-900">
              You have <span className="font-mono font-bold">{balance}</span>{' '}
              credit{balance === 1 ? '' : 's'}. Adding a monitor costs{' '}
              <span className="font-mono font-bold">1</span>.
            </p>
            <p className="text-xs text-gray-600 mt-1">
              You'll receive a full refund if you remove the monitor within
              24 hours.
            </p>
          </div>
        </div>

        <div>
          <label
            htmlFor="tiktok-handle"
            className="auth-mono-label text-[10px] block mb-1"
          >
            TikTok handle
          </label>
          <Input
            id="tiktok-handle"
            placeholder="e.g. luzy.pe (no @)"
            value={handle}
            onChange={(e) => {
              setHandle(e.target.value);
              setError(null);
            }}
            autoFocus
            disabled={busy}
            autoComplete="off"
            spellCheck={false}
          />
          {cleanedHandle && cleanedHandle !== handle && (
            <p className="text-xs text-gray-500 mt-1 font-mono">
              Will be saved as: @{cleanedHandle}
            </p>
          )}
        </div>

        {error ? (
          <div className="rounded-md border border-rose-200 bg-rose-50 dark:bg-rose-500/10 p-3 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 text-rose-600 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-rose-900">{error}</p>
          </div>
        ) : null}

        {balance < 1 ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 dark:bg-amber-500/10 p-3 text-sm text-amber-900">
            You need at least 1 credit to add a monitor. Visit your billing
            page to purchase credits.
          </div>
        ) : null}
      </form>
    </Modal>
  );
}

export default UserTikTokAddMonitorModal;
