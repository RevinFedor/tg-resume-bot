import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getChannels, deleteChannel, toggleChannel } from '../api/client';
import type { Channel } from '../api/client';
import { DataTable } from '../components/DataTable';

export function ChannelsPage() {
  const queryClient = useQueryClient();

  const { data: channels, isLoading } = useQuery({
    queryKey: ['channels'],
    queryFn: () => getChannels().then((res) => res.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteChannel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, is_active }: { id: number; is_active: boolean }) =>
      toggleChannel(id, is_active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['channels'] });
    },
  });

  const columns = [
    { key: 'id', title: 'ID' },
    {
      key: 'username',
      title: 'Channel',
      render: (c: Channel) => (
        <a
          href={`https://t.me/${c.username}`}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:underline"
        >
          @{c.username}
        </a>
      ),
    },
    { key: 'title', title: 'Title' },
    { key: 'last_post_id', title: 'Last Post ID' },
    {
      key: 'is_active',
      title: 'Status',
      render: (c: Channel) => (
        <button
          onClick={() => toggleMutation.mutate({ id: c.id, is_active: !c.is_active })}
          className={`rounded px-2 py-1 text-xs font-medium ${
            c.is_active
              ? 'bg-green-600/20 text-green-400'
              : 'bg-red-600/20 text-red-400'
          }`}
        >
          {c.is_active ? 'Active' : 'Inactive'}
        </button>
      ),
    },
    {
      key: 'last_checked_at',
      title: 'Last Checked',
      render: (c: Channel) =>
        c.last_checked_at
          ? new Date(c.last_checked_at).toLocaleString()
          : 'Never',
    },
  ];

  if (isLoading) {
    return <div className="text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="mb-8 text-2xl font-bold text-white">Channels</h1>
      <DataTable
        columns={columns}
        data={channels ?? []}
        onDelete={(channel) => {
          if (confirm(`Delete channel @${channel.username}?`)) {
            deleteMutation.mutate(channel.id);
          }
        }}
      />
    </div>
  );
}
