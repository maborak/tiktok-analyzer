import { useEffect, useState } from 'react';
import { Gift as GiftIcon, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';

import { Button } from '@/components/ui/Button';
import { PageShell, PageHeader } from '@/components/ui/PageShell';
import { tiktokApi, type TikTokGift } from '@admin/services/tiktok';

export function TikTokGifts() {
  const [gifts, setGifts] = useState<TikTokGift[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const data = await tiktokApi.listGifts();
      setGifts(data);
    } catch (e) {
      console.error(e);
      toast.error('Failed to load gifts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  return (
    <PageShell>
      <PageHeader
        title="Gift Catalog"
        icon={<GiftIcon className="w-5 h-5" />}
        description="Every TikTok gift observed across monitored creators. Updates as new gifts appear in any live."
        actions={
          <Button variant="ghost" onClick={refresh} disabled={loading}>
            <RefreshCw className={loading ? 'animate-spin w-4 h-4' : 'w-4 h-4'} />
          </Button>
        }
      />

      <div className="rounded-lg border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-4 py-2 text-left auth-mono-label" style={{ width: 60 }}></th>
              <th className="px-4 py-2 text-left auth-mono-label">Name</th>
              <th className="px-4 py-2 text-right auth-mono-label">Diamonds</th>
              <th className="px-4 py-2 text-left auth-mono-label">Streakable</th>
              <th className="px-4 py-2 text-left auth-mono-label">First seen</th>
              <th className="px-4 py-2 text-left auth-mono-label">Last seen</th>
              <th className="px-4 py-2 text-left auth-mono-label">ID</th>
            </tr>
          </thead>
          <tbody>
            {gifts.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                  {loading ? 'Loading…' : 'No gifts captured yet.'}
                </td>
              </tr>
            )}
            {gifts.map((g) => (
              <tr key={g.gift_id} className="border-t border-gray-200">
                <td className="px-4 py-2">
                  {g.icon_url ? (
                    <img
                      src={g.icon_url}
                      alt={g.name ?? ''}
                      className="w-8 h-8 rounded"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-8 h-8 rounded bg-gray-100 flex items-center justify-center">
                      <GiftIcon className="w-4 h-4 text-gray-400" />
                    </div>
                  )}
                </td>
                <td className="px-4 py-2 font-medium">{g.name ?? '—'}</td>
                <td className="px-4 py-2 text-right font-mono tabular-nums">
                  {g.diamond_count ?? '—'}
                </td>
                <td className="px-4 py-2 text-xs text-gray-600">
                  {g.streakable === null ? '—' : g.streakable ? 'yes' : 'no'}
                </td>
                <td className="px-4 py-2 text-xs text-gray-600 font-mono">
                  {g.first_seen_at ? formatDate(g.first_seen_at) : '—'}
                </td>
                <td className="px-4 py-2 text-xs text-gray-600 font-mono">
                  {g.last_seen_at ? formatDate(g.last_seen_at) : '—'}
                </td>
                <td className="px-4 py-2 text-xs text-gray-500 font-mono">{g.gift_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageShell>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pad(n: number): string {
  return n.toString().padStart(2, '0');
}
