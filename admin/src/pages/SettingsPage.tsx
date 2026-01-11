import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Cpu,
  CheckCircle,
  AlertCircle,
  Loader2,
  RefreshCw,
  ExternalLink,
  Zap,
} from 'lucide-react';
import {
  getAISettings,
  updateAISettings,
  getAIStatus,
  getAvailableModels,
} from '../api/client';

// Рекомендуемые модели с хорошими лимитами
const RECOMMENDED_MODELS = [
  'gemma-3-27b-it',
  'gemini-2.5-flash',
  'gemini-2.5-flash-lite',
  'gemini-2.0-flash',
];

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [selectedModel, setSelectedModel] = useState<string>('');

  // Получаем текущие настройки
  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ['ai-settings'],
    queryFn: () => getAISettings().then((res) => res.data),
  });

  // Получаем статус модели
  const { data: status, isLoading: statusLoading, refetch: refetchStatus } = useQuery({
    queryKey: ['ai-status'],
    queryFn: () => getAIStatus().then((res) => res.data),
    refetchInterval: 30000, // Проверять каждые 30 сек
  });

  // Получаем список доступных моделей
  const { data: modelsData, isLoading: modelsLoading } = useQuery({
    queryKey: ['ai-models'],
    queryFn: () => getAvailableModels().then((res) => res.data),
  });

  // Инициализируем выбранную модель из настроек
  useEffect(() => {
    if (settings && !selectedModel) {
      setSelectedModel(settings.gemini_model);
    }
  }, [settings, selectedModel]);

  // Мутация для обновления модели
  const updateModel = useMutation({
    mutationFn: (model: string) => updateAISettings({ gemini_model: model }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings'] });
      queryClient.invalidateQueries({ queryKey: ['ai-status'] });
    },
  });

  const handleModelChange = (model: string) => {
    setSelectedModel(model);
    updateModel.mutate(model);
  };

  if (settingsLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
      </div>
    );
  }

  const isModelOk = status?.status === 'ok';
  const isRateLimited = status?.status === 'rate_limited';

  // Фильтруем и сортируем модели
  const models = modelsData?.models || [];
  const sortedModels = [...models].sort((a, b) => {
    const aRecommended = RECOMMENDED_MODELS.includes(a.name);
    const bRecommended = RECOMMENDED_MODELS.includes(b.name);
    if (aRecommended && !bRecommended) return -1;
    if (!aRecommended && bRecommended) return 1;
    return a.name.localeCompare(b.name);
  });

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-8 text-2xl font-bold text-white">AI Settings</h1>

      {/* Status Card */}
      <div className="mb-6 rounded-xl bg-gray-900 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div
              className={`rounded-full p-3 ${
                isModelOk
                  ? 'bg-green-900/50'
                  : isRateLimited
                  ? 'bg-yellow-900/50'
                  : 'bg-red-900/50'
              }`}
            >
              <Cpu
                className={`h-8 w-8 ${
                  isModelOk
                    ? 'text-green-400'
                    : isRateLimited
                    ? 'text-yellow-400'
                    : 'text-red-400'
                }`}
              />
            </div>
            <div>
              <div className="flex items-center gap-2">
                {statusLoading ? (
                  <Loader2 className="h-5 w-5 animate-spin text-gray-400" />
                ) : isModelOk ? (
                  <>
                    <CheckCircle className="h-5 w-5 text-green-400" />
                    <span className="font-medium text-green-400">Работает</span>
                  </>
                ) : isRateLimited ? (
                  <>
                    <AlertCircle className="h-5 w-5 text-yellow-400" />
                    <span className="font-medium text-yellow-400">Rate Limited</span>
                  </>
                ) : (
                  <>
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <span className="font-medium text-red-400">Ошибка</span>
                  </>
                )}
              </div>
              <p className="mt-1 text-sm text-gray-400">
                Модель: <span className="text-white">{status?.model || selectedModel}</span>
              </p>
              {status?.message && (
                <p className="mt-1 text-sm text-gray-500">{status.message}</p>
              )}
            </div>
          </div>
          <button
            onClick={() => refetchStatus()}
            disabled={statusLoading}
            className="rounded-lg bg-gray-800 p-2 text-gray-400 transition-colors hover:bg-gray-700 hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-5 w-5 ${statusLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Rate Limited Warning */}
      {isRateLimited && (
        <div className="mb-6 rounded-xl border border-yellow-600/50 bg-yellow-900/20 p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-yellow-400" />
            <div className="text-sm text-yellow-200">
              <p className="font-medium">Лимит запросов исчерпан</p>
              <p className="mt-1 text-yellow-300/80">
                Выберите другую модель или подождите сброса лимитов.{' '}
                <a
                  href="https://aistudio.google.com/usage"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 underline hover:text-yellow-100"
                >
                  Проверить лимиты <ExternalLink className="h-3 w-3" />
                </a>
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Model Selection */}
      <div className="rounded-xl bg-gray-900 p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">Выбор модели</h2>
        <p className="mb-4 text-sm text-gray-400">
          Выберите модель для суммаризации. Рекомендуемые модели отмечены значком.
        </p>

        {modelsLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
          </div>
        ) : (
          <div className="space-y-2">
            {sortedModels.map((model) => {
              const isRecommended = RECOMMENDED_MODELS.includes(model.name);
              const isSelected = selectedModel === model.name;
              const isCurrent = settings?.gemini_model === model.name;

              return (
                <button
                  key={model.name}
                  onClick={() => handleModelChange(model.name)}
                  disabled={updateModel.isPending}
                  className={`flex w-full items-center justify-between rounded-lg border p-4 text-left transition-colors ${
                    isSelected
                      ? 'border-blue-500 bg-blue-900/20'
                      : 'border-gray-700 bg-gray-800 hover:border-gray-600'
                  } ${updateModel.isPending ? 'opacity-50' : ''}`}
                >
                  <div className="flex items-center gap-3">
                    <div
                      className={`h-4 w-4 rounded-full border-2 ${
                        isSelected
                          ? 'border-blue-500 bg-blue-500'
                          : 'border-gray-500'
                      }`}
                    >
                      {isSelected && (
                        <div className="flex h-full w-full items-center justify-center">
                          <div className="h-1.5 w-1.5 rounded-full bg-white" />
                        </div>
                      )}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-white">{model.name}</span>
                        {isRecommended && (
                          <span className="flex items-center gap-1 rounded bg-green-900/50 px-1.5 py-0.5 text-xs text-green-400">
                            <Zap className="h-3 w-3" />
                            Рекомендуется
                          </span>
                        )}
                        {isCurrent && (
                          <span className="rounded bg-blue-900/50 px-1.5 py-0.5 text-xs text-blue-400">
                            Текущая
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 text-xs text-gray-500">
                        {model.displayName} • {(model.inputTokenLimit / 1000).toFixed(0)}K input
                      </p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {updateModel.isPending && (
          <div className="mt-4 flex items-center gap-2 text-sm text-gray-400">
            <Loader2 className="h-4 w-4 animate-spin" />
            Сохранение...
          </div>
        )}
      </div>

      {/* Info section */}
      <div className="mt-6 rounded-xl bg-gray-900 p-6">
        <h2 className="mb-4 text-lg font-semibold text-white">О моделях</h2>
        <ul className="space-y-2 text-sm text-gray-400">
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-green-400" />
            <span>
              <strong className="text-gray-300">gemma-3-27b-it</strong> — мультимодальная, хорошие
              лимиты (14,400 RPD)
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-green-400" />
            <span>
              <strong className="text-gray-300">gemini-2.5-flash</strong> — быстрая, качественная
              (1,500 RPD)
            </span>
          </li>
          <li className="flex items-start gap-2">
            <span className="mt-1 h-1.5 w-1.5 flex-shrink-0 rounded-full bg-yellow-400" />
            <span>
              <strong className="text-gray-300">gemini-3-*-preview</strong> — новые, но низкие
              лимиты (10-20 RPD)
            </span>
          </li>
        </ul>
        <div className="mt-4">
          <a
            href="https://aistudio.google.com/usage"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 text-sm text-blue-400 hover:text-blue-300"
          >
            <ExternalLink className="h-4 w-4" />
            Открыть AI Studio для проверки лимитов
          </a>
        </div>
      </div>
    </div>
  );
}
