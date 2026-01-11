import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUsers, deleteUser } from '../api/client';
import type { User } from '../api/client';
import { DataTable } from '../components/DataTable';

export function UsersPage() {
  const queryClient = useQueryClient();

  const { data: users, isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: () => getUsers().then((res) => res.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['users'] });
      queryClient.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  const columns = [
    { key: 'id', title: 'ID' },
    { key: 'telegram_id', title: 'Telegram ID' },
    { key: 'username', title: 'Username', render: (u: User) => u.username ? `@${u.username}` : '-' },
    { key: 'first_name', title: 'Name' },
    {
      key: 'interests',
      title: 'Interests 🔥',
      render: (u: User) => (
        u.interests ? (
          <span className="text-orange-400 max-w-xs truncate block" title={u.interests}>
            {u.interests.length > 30 ? u.interests.slice(0, 30) + '...' : u.interests}
          </span>
        ) : (
          <span className="text-gray-500">-</span>
        )
      ),
    },
    {
      key: 'is_admin',
      title: 'Admin',
      render: (u: User) => (
        <span className={u.is_admin ? 'text-green-400' : 'text-gray-500'}>
          {u.is_admin ? 'Yes' : 'No'}
        </span>
      ),
    },
    {
      key: 'created_at',
      title: 'Created',
      render: (u: User) => new Date(u.created_at).toLocaleDateString(),
    },
  ];

  if (isLoading) {
    return <div className="text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="mb-8 text-2xl font-bold text-white">Users</h1>
      <DataTable
        columns={columns}
        data={users ?? []}
        onDelete={(user) => {
          if (confirm(`Delete user ${user.username || user.telegram_id}?`)) {
            deleteMutation.mutate(user.id);
          }
        }}
      />
    </div>
  );
}
