import { useQuery } from '@tanstack/react-query';
import { Users, Radio, Bell, FileText } from 'lucide-react';
import { getStats } from '../api/client';
import { StatsCard } from '../components/StatsCard';

export function Dashboard() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => getStats().then((res) => res.data),
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  return (
    <div>
      <h1 className="mb-8 text-2xl font-bold text-white">Dashboard</h1>
      <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Total Users"
          value={stats?.total_users ?? 0}
          icon={Users}
          color="bg-blue-600"
        />
        <StatsCard
          title="Total Channels"
          value={stats?.total_channels ?? 0}
          icon={Radio}
          color="bg-green-600"
        />
        <StatsCard
          title="Subscriptions"
          value={stats?.total_subscriptions ?? 0}
          icon={Bell}
          color="bg-purple-600"
        />
        <StatsCard
          title="Posts Processed"
          value={stats?.total_posts ?? 0}
          icon={FileText}
          color="bg-orange-600"
        />
      </div>

      <div className="mt-8 rounded-xl bg-gray-900 p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">Quick Info</h2>
        <div className="space-y-3 text-sm text-gray-400">
          <p>
            <span className="text-gray-300">Bot:</span>{' '}
            <a
              href="https://t.me/chanresume_bot"
              target="_blank"
              rel="noopener noreferrer"
              className="text-blue-400 hover:underline"
            >
              @chanresume_bot
            </a>
          </p>
          <p>
            <span className="text-gray-300">Scheduler:</span> Checks channels every 5 minutes
          </p>
          <p>
            <span className="text-gray-300">AI Model:</span> Gemini 2.0 Flash
          </p>
        </div>
      </div>
    </div>
  );
}
