import { useQuery } from '@tanstack/react-query';
import { getSubscriptions } from '../api/client';
import type { Subscription } from '../api/client';
import { DataTable } from '../components/DataTable';

export function SubscriptionsPage() {
  const { data: subscriptions, isLoading } = useQuery({
    queryKey: ['subscriptions'],
    queryFn: () => getSubscriptions().then((res) => res.data),
  });

  const columns = [
    { key: 'id', title: 'ID' },
    {
      key: 'user',
      title: 'User',
      render: (s: Subscription) =>
        s.user?.username ? `@${s.user.username}` : `ID: ${s.user_id}`,
    },
    {
      key: 'channel',
      title: 'Channel',
      render: (s: Subscription) =>
        s.channel ? (
          <a
            href={`https://t.me/${s.channel.username}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-400 hover:underline"
          >
            @{s.channel.username}
          </a>
        ) : (
          `ID: ${s.channel_id}`
        ),
    },
    {
      key: 'created_at',
      title: 'Subscribed At',
      render: (s: Subscription) => new Date(s.created_at).toLocaleString(),
    },
  ];

  if (isLoading) {
    return <div className="text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="mb-8 text-2xl font-bold text-white">Subscriptions</h1>
      <DataTable columns={columns} data={subscriptions ?? []} />
    </div>
  );
}
