import { useQuery } from '@tanstack/react-query';
import { Users, Radio, Bell, FileText, Bot, CheckCircle, AlertCircle } from 'lucide-react';
import { Link } from 'react-router-dom';
import { getStats, getUserbotStatus } from '../api/client';
import { StatsCard } from '../components/StatsCard';

export function Dashboard() {
  const { data: stats, isLoading } = useQuery({
    queryKey: ['stats'],
    queryFn: () => getStats().then((res) => res.data),
  });

  const { data: userbotStatus } = useQuery({
    queryKey: ['userbot-status'],
    queryFn: () => getUserbotStatus().then((res) => res.data),
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-gray-400">Loading...</div>
      </div>
    );
  }

  const isUserbotActive = userbotStatus?.state === 'authorized';

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

      {/* Userbot Status Card */}
      <div className="mt-8 rounded-xl bg-gray-900 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className={`rounded-full p-3 ${isUserbotActive ? 'bg-green-900/50' : 'bg-gray-800'}`}>
              <Bot className={`h-6 w-6 ${isUserbotActive ? 'text-green-400' : 'text-gray-500'}`} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">Userbot</h2>
              <div className="flex items-center gap-2 text-sm">
                {isUserbotActive ? (
                  <>
                    <CheckCircle className="h-4 w-4 text-green-400" />
                    <span className="text-green-400">Активен</span>
                    <span className="text-gray-500">— голосовые и кружки обрабатываются</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-4 w-4 text-yellow-400" />
                    <span className="text-yellow-400">Не авторизован</span>
                    <span className="text-gray-500">— только текстовые посты</span>
                  </>
                )}
              </div>
            </div>
          </div>
          <Link
            to="/userbot"
            className="rounded-lg bg-gray-800 px-4 py-2 text-sm font-medium text-gray-300 transition-colors hover:bg-gray-700 hover:text-white"
          >
            {isUserbotActive ? 'Управление' : 'Настроить'}
          </Link>
        </div>
      </div>

      <div className="mt-6 rounded-xl bg-gray-900 p-6">
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
            <span className="text-gray-300">Scheduler:</span> Checks channels every 30 seconds
          </p>
          <p>
            <span className="text-gray-300">AI Model:</span> Gemma 3 27B (text + vision)
          </p>
          <p>
            <span className="text-gray-300">Transcription:</span> OpenAI Whisper (voice, video, audio)
          </p>
          <p>
            <span className="text-gray-300">Supported:</span> Text, Photos, Albums, Voice, Video, Video Notes
          </p>
        </div>
      </div>
    </div>
  );
}
