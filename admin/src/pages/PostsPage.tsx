import { useQuery } from '@tanstack/react-query';
import { getPosts } from '../api/client';

export function PostsPage() {
  const { data: posts, isLoading } = useQuery({
    queryKey: ['posts'],
    queryFn: () => getPosts(50).then((res) => res.data),
  });

  if (isLoading) {
    return <div className="text-gray-400">Loading...</div>;
  }

  return (
    <div>
      <h1 className="mb-8 text-2xl font-bold text-white">Posts</h1>
      <div className="space-y-4">
        {posts?.map((post) => (
          <div key={post.id} className="rounded-xl bg-gray-900 p-6">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                {post.channel && (
                  <a
                    href={`https://t.me/${post.channel.username}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-medium text-blue-400 hover:underline"
                  >
                    @{post.channel.username}
                  </a>
                )}
                <span className="text-xs text-gray-500">
                  Post #{post.post_id}
                </span>
              </div>
              <span className="text-xs text-gray-500">
                {new Date(post.created_at).toLocaleString()}
              </span>
            </div>

            {post.summary && (
              <div className="mb-4">
                <h3 className="mb-2 text-xs font-medium uppercase text-gray-500">
                  Summary
                </h3>
                <p className="text-sm text-gray-300">{post.summary}</p>
              </div>
            )}

            {post.content && (
              <details className="group">
                <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-400">
                  Show original content
                </summary>
                <p className="mt-2 text-xs text-gray-500">{post.content}</p>
              </details>
            )}

            <div className="mt-4">
              <a
                href={`https://t.me/${post.channel?.username}/${post.post_id}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:underline"
              >
                View original post →
              </a>
            </div>
          </div>
        ))}

        {(!posts || posts.length === 0) && (
          <div className="rounded-xl bg-gray-900 p-12 text-center text-gray-500">
            No posts processed yet
          </div>
        )}
      </div>
    </div>
  );
}
