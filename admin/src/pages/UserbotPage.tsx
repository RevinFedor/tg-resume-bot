import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Bot, Phone, Key, Lock, LogOut, CheckCircle, AlertCircle, Loader2 } from 'lucide-react';
import {
  getUserbotStatus,
  startUserbotAuth,
  confirmUserbotCode,
  confirmUserbotPassword,
  logoutUserbot,
  type UserbotState,
} from '../api/client';

const stateConfig: Record<UserbotState, { color: string; icon: typeof CheckCircle; label: string }> = {
  not_started: { color: 'text-gray-400', icon: AlertCircle, label: 'Не авторизован' },
  waiting_code: { color: 'text-yellow-400', icon: Loader2, label: 'Ожидание кода' },
  waiting_password: { color: 'text-yellow-400', icon: Lock, label: 'Требуется 2FA' },
  authorized: { color: 'text-green-400', icon: CheckCircle, label: 'Авторизован' },
  error: { color: 'text-red-400', icon: AlertCircle, label: 'Ошибка' },
};

export function UserbotPage() {
  const queryClient = useQueryClient();
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data: status, isLoading } = useQuery({
    queryKey: ['userbot-status'],
    queryFn: () => getUserbotStatus().then((res) => res.data),
    refetchInterval: 5000,
  });

  const startAuth = useMutation({
    mutationFn: startUserbotAuth,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['userbot-status'] });
      setError(null);
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Ошибка отправки кода');
    },
  });

  const confirmCode = useMutation({
    mutationFn: confirmUserbotCode,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['userbot-status'] });
      setCode('');
      setError(null);
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Неверный код');
    },
  });

  const confirmPwd = useMutation({
    mutationFn: confirmUserbotPassword,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['userbot-status'] });
      setPassword('');
      setError(null);
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Неверный пароль');
    },
  });

  const logout = useMutation({
    mutationFn: logoutUserbot,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['userbot-status'] });
      setPhone('');
      setCode('');
      setPassword('');
      setError(null);
    },
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  const state = status?.state || 'not_started';
  const config = stateConfig[state];
  const StateIcon = config.icon;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-8 text-2xl font-bold text-white">Userbot</h1>

      {/* Status Card */}
      <div className="mb-6 rounded-xl bg-gray-900 p-6">
        <div className="flex items-center gap-4">
          <div className={`rounded-full p-3 ${state === 'authorized' ? 'bg-green-900/50' : 'bg-gray-800'}`}>
            <Bot className={`h-8 w-8 ${config.color}`} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <StateIcon className={`h-5 w-5 ${config.color} ${state === 'waiting_code' || state === 'waiting_password' ? 'animate-spin' : ''}`} />
              <span className={`font-medium ${config.color}`}>{config.label}</span>
            </div>
            <p className="mt-1 text-sm text-gray-400">{status?.message}</p>
            {status?.phone && (
              <p className="mt-1 text-sm text-gray-500">Телефон: {status.phone}</p>
            )}
          </div>
        </div>
      </div>

      {/* Not configured warning */}
      {status && !status.configured && (
        <div className="mb-6 rounded-xl border border-yellow-600/50 bg-yellow-900/20 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-yellow-400" />
            <div className="text-sm text-yellow-200">
              <p className="font-medium">API credentials не настроены</p>
              <p className="mt-1 text-yellow-300/80">
                Добавьте переменные окружения TELEGRAM_API_ID и TELEGRAM_API_HASH.
                Получить их можно на{' '}
                <a
                  href="https://my.telegram.org/apps"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-yellow-100"
                >
                  my.telegram.org/apps
                </a>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error message */}
      {error && (
        <div className="mb-6 rounded-xl border border-red-600/50 bg-red-900/20 p-4">
          <div className="flex items-center gap-3">
            <AlertCircle className="h-5 w-5 text-red-400" />
            <span className="text-sm text-red-200">{error}</span>
          </div>
        </div>
      )}

      {/* Auth Forms */}
      <div className="rounded-xl bg-gray-900 p-6">
        {/* Step 1: Phone number */}
        {(state === 'not_started' || state === 'error') && status?.configured && (
          <div>
            <h2 className="mb-4 text-lg font-semibold text-white">Шаг 1: Номер телефона</h2>
            <p className="mb-4 text-sm text-gray-400">
              Введите номер телефона Telegram аккаунта, который будет использоваться для парсинга каналов.
            </p>
            <div className="flex gap-3">
              <div className="relative flex-1">
                <Phone className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-500" />
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+7 900 123 4567"
                  className="w-full rounded-lg border border-gray-700 bg-gray-800 py-2 pl-10 pr-4 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => startAuth.mutate(phone)}
                disabled={!phone || startAuth.isPending}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {startAuth.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  'Отправить код'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Confirmation code */}
        {state === 'waiting_code' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold text-white">Шаг 2: Код подтверждения</h2>
            <p className="mb-4 text-sm text-gray-400">
              Введите код, который пришёл в Telegram (или SMS).
            </p>
            <div className="flex gap-3">
              <div className="relative flex-1">
                <Key className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-500" />
                <input
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="12345"
                  maxLength={6}
                  className="w-full rounded-lg border border-gray-700 bg-gray-800 py-2 pl-10 pr-4 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => confirmCode.mutate(code)}
                disabled={!code || confirmCode.isPending}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {confirmCode.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  'Подтвердить'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: 2FA Password */}
        {state === 'waiting_password' && (
          <div>
            <h2 className="mb-4 text-lg font-semibold text-white">Шаг 3: Пароль 2FA</h2>
            <p className="mb-4 text-sm text-gray-400">
              На аккаунте включена двухфакторная аутентификация. Введите пароль.
            </p>
            <div className="flex gap-3">
              <div className="relative flex-1">
                <Lock className="absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-500" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Пароль"
                  className="w-full rounded-lg border border-gray-700 bg-gray-800 py-2 pl-10 pr-4 text-white placeholder-gray-500 focus:border-blue-500 focus:outline-none"
                />
              </div>
              <button
                onClick={() => confirmPwd.mutate(password)}
                disabled={!password || confirmPwd.isPending}
                className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 font-medium text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {confirmPwd.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  'Войти'
                )}
              </button>
            </div>
          </div>
        )}

        {/* Authorized state */}
        {state === 'authorized' && (
          <div>
            <div className="mb-6 flex items-center gap-3 rounded-lg bg-green-900/30 p-4">
              <CheckCircle className="h-6 w-6 text-green-400" />
              <div>
                <p className="font-medium text-green-300">Userbot активен</p>
                <p className="text-sm text-green-400/80">
                  Голосовые и кружки из каналов будут автоматически транскрибироваться.
                </p>
              </div>
            </div>
            <button
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
              className="flex items-center gap-2 rounded-lg border border-red-600/50 bg-red-900/20 px-4 py-2 font-medium text-red-400 transition-colors hover:bg-red-900/40 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {logout.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <>
                  <LogOut className="h-4 w-4" />
                  Выйти из аккаунта
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* Info section */}
      <div className="mt-6 rounded-xl bg-gray-900 p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">Как это работает</h2>
        <ul className="space-y-2 text-sm text-gray-400">
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
            Userbot подписывается на все каналы пользователей
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
            Получает доступ к голосовым сообщениям и видео-кружкам
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
            Транскрибирует аудио через Whisper API
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-blue-400" />
            Создаёт резюме и отправляет подписчикам
          </li>
        </ul>
        <div className="mt-4 rounded-lg bg-yellow-900/20 p-3 text-sm text-yellow-300/80">
          <strong>Важно:</strong> Используйте отдельный Telegram аккаунт, а не основной.
          Telegram может ограничить аккаунт за автоматизацию.
        </div>
      </div>
    </div>
  );
}
